from __future__ import annotations

import asyncio
import logging
import os
import sys
import time as _time
import uuid
from typing import Optional

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

log = logging.getLogger("kimodo_server")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Kimodo API")

OUTPUT_DIR = __import__("pathlib").Path(os.environ.get("OUTPUT_DIR", "/workspace/output"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DEV_REFERENCE = OUTPUT_DIR / "dev_reference.npz"
MOCK_MODE = os.environ.get("MOCK_MODE", "1") == "1"
TEXT_ENCODER_URL = os.environ.get("TEXT_ENCODER_URL", "http://text-encoder:9550/")

_jobs: dict[str, dict] = {}


class GenerateRequest(BaseModel):
    prompt: str
    duration: float = 3.0
    model: str = "soma-rp"
    num_samples: int = 1


class JobStatus(BaseModel):
    job_id: str
    status: str          # queued | running | done | failed
    npz_path: Optional[str] = None
    prompt: Optional[str] = None
    frames: Optional[int] = None
    joints: Optional[int] = None
    error: Optional[str] = None
    elapsed: Optional[float] = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "mock_mode": MOCK_MODE}


@app.post("/generate", status_code=202)
async def generate(req: GenerateRequest) -> JobStatus:
    job_id = uuid.uuid4().hex
    _jobs[job_id] = {"status": "queued", "started_at": _time.monotonic(), "prompt": req.prompt}
    asyncio.create_task(_run_job(job_id, req))
    log.info("[JOB] %s queued — prompt='%s'", job_id[:8], req.prompt)
    return JobStatus(job_id=job_id, status="queued", prompt=req.prompt)


@app.get("/jobs/{job_id}")
def job_status(job_id: str) -> JobStatus:
    if job_id not in _jobs:
        raise HTTPException(404, f"Job {job_id} not found.")
    job = _jobs[job_id]
    elapsed = job.get("elapsed")
    if elapsed is None and "started_at" in job:
        elapsed = _time.monotonic() - job["started_at"]
    return JobStatus(
        job_id=job_id,
        status=job["status"],
        npz_path=job.get("npz_path"),
        prompt=job.get("prompt"),
        frames=job.get("frames"),
        joints=job.get("joints"),
        error=job.get("error"),
        elapsed=round(elapsed, 1) if elapsed is not None else None,
    )


@app.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> JobStatus:
    if job_id not in _jobs:
        raise HTTPException(404, f"Job {job_id} not found.")
    job = _jobs[job_id]
    if job["status"] not in ("queued", "running"):
        return job_status(job_id)
    proc = job.get("proc")
    if proc and proc.returncode is None:
        proc.terminate()
    job["status"] = "cancelled"
    job["elapsed"] = round(_time.monotonic() - job.get("started_at", _time.monotonic()), 1)
    log.info("[CANCEL] %s", job_id[:8])
    return job_status(job_id)


async def _run_job(job_id: str, req: GenerateRequest) -> None:
    job = _jobs[job_id]
    if job.get("status") == "cancelled":  # cancelled while still queued
        job["elapsed"] = round(_time.monotonic() - job["started_at"], 1)
        return
    job["status"] = "running"

    try:
        if MOCK_MODE:
            if not DEV_REFERENCE.exists():
                job.update(status="failed", error=f"dev_reference.npz not found at {DEV_REFERENCE}")
                return
            log.info("[MOCK] %s → %s", job_id[:8], DEV_REFERENCE)
            data = np.load(DEV_REFERENCE)
            T, J = data["posed_joints"].shape[:2]
            job.update(status="done", npz_path=str(DEV_REFERENCE), frames=T, joints=J,
                       elapsed=round(_time.monotonic() - job["started_at"], 1))
            return

        out_path = OUTPUT_DIR / f"{uuid.uuid4().hex}.npz"
        cmd = [
            sys.executable, "-m", "kimodo.scripts.generate",
            req.prompt,
            "--model", req.model,
            "--duration", str(req.duration),
            "--output", str(out_path),
        ]
        log.info("[GEN] %s %s", job_id[:8], " ".join(cmd))

        env = os.environ.copy()
        env["TEXT_ENCODER_URL"] = TEXT_ENCODER_URL

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        job["proc"] = proc
        stdout, stderr = await proc.communicate()
        elapsed = round(_time.monotonic() - job["started_at"], 1)

        if job.get("status") == "cancelled":  # cancel terminated the subprocess
            job["elapsed"] = elapsed
            return
        if proc.returncode != 0:
            log.error("[FAIL] %s\n%s", job_id[:8], stderr.decode())
            job.update(status="failed", error=stderr.decode()[-500:], elapsed=elapsed)
            return
        if not out_path.exists():
            job.update(status="failed", error="Output file not found after inference.", elapsed=elapsed)
            return

        data = np.load(out_path)
        T, J = data["posed_joints"].shape[:2]
        log.info("[DONE] %s — %d frames, %d joints, %.1fs", job_id[:8], T, J, elapsed)
        job.update(status="done", npz_path=str(out_path), frames=T, joints=J, elapsed=elapsed)
    except Exception as exc:  # never leave a job stuck in "running"
        if job.get("status") != "cancelled":
            log.exception("[FAIL] %s", job_id[:8])
            job.update(status="failed", error=str(exc)[-500:],
                       elapsed=round(_time.monotonic() - job["started_at"], 1))
