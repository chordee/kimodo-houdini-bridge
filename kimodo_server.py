from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time as _time
import uuid
from typing import Optional

import pathlib
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

log = logging.getLogger("kimodo_server")
logging.basicConfig(level=logging.INFO)

OUTPUT_DIR = pathlib.Path(os.environ.get("OUTPUT_DIR", "/workspace/output"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DEV_REFERENCE = OUTPUT_DIR / "dev_reference.npz"
MOCK_MODE = os.environ.get("MOCK_MODE", "1") == "1"

# Model to preload at startup; empty falls back to kimodo.DEFAULT_MODEL.
RESIDENT_MODEL = os.environ.get("KIMODO_MODEL", "")

_jobs: dict[str, dict] = {}

# Resident-mode state: a single-slot model cache and a lock that serialises
# inference (one GPU → one generation at a time).
_model = None
_model_key: Optional[str] = None
_model_lock = asyncio.Lock()


def _ensure_model(name: str):
    """Load (or reuse) the resident Kimodo model. The cache key is the resolved
    canonical model name, so aliases (e.g. an empty preload default and the HDA's
    "Kimodo-SOMA-RP-v1.1") map to the same key and reuse the loaded model instead
    of reloading. Single slot: a different model replaces the previous one to
    bound VRAM to one model at a time."""
    global _model, _model_key
    import torch
    from kimodo import load_model
    from kimodo.model.registry import resolve_model_name

    key = resolve_model_name(name or "", default_family="Kimodo")
    if _model is not None and _model_key == key:
        return _model
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    log.info("[RESIDENT] loading model %s on %s ...", key, device)
    model, resolved = load_model(
        key, device=device, default_family="Kimodo", return_resolved_name=True
    )
    _model, _model_key = model, key
    log.info("[RESIDENT] model ready: %s", resolved)
    return model


def _infer_resident(req: "GenerateRequest", out_path: pathlib.Path) -> None:
    """Blocking in-process inference. Mirrors kimodo/scripts/generate.py main()."""
    from kimodo.exports.motion_io import save_kimodo_npz

    from kimodo.constraints import load_constraints_lst

    model = _ensure_model(req.model)
    texts = [req.prompt]
    num_frames = [int(float(req.duration) * model.fps)]
    constraint_lst = (
        load_constraints_lst(req.constraints, model.skeleton) if req.constraints else []
    )
    output = model(
        texts,
        num_frames,
        num_denoising_steps=100,
        num_samples=1,
        multi_prompt=True,
        num_transition_frames=5,
        post_processing=True,
        constraint_lst=constraint_lst,
        return_numpy=True,
    )
    n = int(output["posed_joints"].shape[0])
    single = {
        k: (v[0] if hasattr(v, "shape") and len(v.shape) > 0 and v.shape[0] == n else v)
        for k, v in output.items()
    }
    save_kimodo_npz(str(out_path), single)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not MOCK_MODE:
        # Preload the model now so the first /generate skips the load.
        await asyncio.to_thread(_ensure_model, RESIDENT_MODEL)
    yield


app = FastAPI(title="Kimodo API", lifespan=lifespan)


class GenerateRequest(BaseModel):
    prompt: str
    duration: float = 3.0
    model: str = "soma-rp"
    num_samples: int = 1
    force: bool = False          # bypass the cache and re-run inference
    constraints: Optional[list] = None   # Kimodo constraint dicts (type/frame_indices/...)


class JobStatus(BaseModel):
    job_id: str
    status: str          # queued | running | done | failed | cancelled
    npz_path: Optional[str] = None
    prompt: Optional[str] = None
    frames: Optional[int] = None
    joints: Optional[int] = None
    error: Optional[str] = None
    elapsed: Optional[float] = None
    cached: Optional[bool] = None    # True if served from a cached NPZ


def _cache_key(prompt: str, duration: float, model: str, constraints=None) -> str:
    payload = json.dumps(
        {"prompt": prompt, "duration": duration, "model": model, "constraints": constraints},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "mock_mode": MOCK_MODE}


@app.get("/jobs/{job_id}/download")
def download_job(job_id: str) -> FileResponse:
    """Serve a finished job's NPZ over HTTP (used by the remote HDA, since a
    remote Houdini cannot read the server's filesystem via a path rewrite)."""
    if job_id not in _jobs:
        raise HTTPException(404, f"Job {job_id} not found.")
    npz = _jobs[job_id].get("npz_path")
    if not npz:
        raise HTTPException(409, f"Job {job_id} has no output (status={_jobs[job_id]['status']}).")
    path = pathlib.Path(npz).resolve()
    if not path.is_relative_to(OUTPUT_DIR.resolve()):
        raise HTTPException(403, "Output path is outside the output directory.")
    if not path.exists():
        raise HTTPException(404, "Output file is missing.")
    return FileResponse(str(path), media_type="application/octet-stream", filename=path.name)


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
        cached=job.get("cached"),
    )


@app.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> JobStatus:
    if job_id not in _jobs:
        raise HTTPException(404, f"Job {job_id} not found.")
    job = _jobs[job_id]
    if job["status"] not in ("queued", "running"):
        return job_status(job_id)
    # In-process inference can't be hard-interrupted: mark cancelled so a queued
    # job is skipped and a finished result is discarded.
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

        out_path = OUTPUT_DIR / f"{_cache_key(req.prompt, req.duration, req.model, req.constraints)}.npz"

        if not req.force and out_path.exists():
            data = np.load(out_path)
            T, J = data["posed_joints"].shape[:2]
            log.info("[CACHE] %s → %s", job_id[:8], out_path.name)
            job.update(status="done", npz_path=str(out_path), frames=T, joints=J,
                       cached=True, elapsed=round(_time.monotonic() - job["started_at"], 1))
            return

        # In-process inference, serialised on the single GPU. Cannot be hard-
        # cancelled mid-run; a cancel marks the job and the result is discarded.
        async with _model_lock:
            if job.get("status") == "cancelled":
                job["elapsed"] = round(_time.monotonic() - job["started_at"], 1)
                return
            log.info("[GEN] %s prompt=%r", job_id[:8], req.prompt)
            await asyncio.to_thread(_infer_resident, req, out_path)
        if job.get("status") == "cancelled":  # cancelled while inference ran
            job["elapsed"] = round(_time.monotonic() - job["started_at"], 1)
            return

        elapsed = round(_time.monotonic() - job["started_at"], 1)
        if not out_path.exists():
            job.update(status="failed", error="Output file not found after inference.", elapsed=elapsed)
            return

        data = np.load(out_path)
        T, J = data["posed_joints"].shape[:2]
        out_path.with_suffix(".json").write_text(json.dumps({
            "prompt": req.prompt, "duration": req.duration, "model": req.model,
            "frames": int(T), "joints": int(J), "created": _time.time(),
        }, indent=2))
        log.info("[DONE] %s — %d frames, %d joints, %.1fs", job_id[:8], T, J, elapsed)
        job.update(status="done", npz_path=str(out_path), frames=T, joints=J,
                   cached=False, elapsed=elapsed)
    except Exception as exc:  # never leave a job stuck in "running"
        if job.get("status") != "cancelled":
            log.exception("[FAIL] %s", job_id[:8])
            job.update(status="failed", error=str(exc)[-500:],
                       elapsed=round(_time.monotonic() - job["started_at"], 1))
