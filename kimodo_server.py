from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

log = logging.getLogger("kimodo_server")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Kimodo API")

OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "/workspace/output"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DEV_REFERENCE = OUTPUT_DIR / "dev_reference.npz"
MOCK_MODE = os.environ.get("MOCK_MODE", "1") == "1"
TEXT_ENCODER_URL = os.environ.get("TEXT_ENCODER_URL", "http://text-encoder:9550/")


class GenerateRequest(BaseModel):
    prompt: str
    duration: float = 3.0
    model: str = "soma-rp"
    num_samples: int = 1


class GenerateResponse(BaseModel):
    npz_path: str
    prompt: str
    duration: float
    frames: int
    joints: int


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "mock_mode": MOCK_MODE}


@app.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest) -> GenerateResponse:
    if MOCK_MODE:
        if not DEV_REFERENCE.exists():
            raise HTTPException(500, f"dev_reference.npz not found at {DEV_REFERENCE}")
        log.info("[MOCK] prompt='%s' → %s", req.prompt, DEV_REFERENCE)
        data = np.load(DEV_REFERENCE)
        T, J = data["posed_joints"].shape[:2]
        return GenerateResponse(
            npz_path=str(DEV_REFERENCE),
            prompt=req.prompt,
            duration=req.duration,
            frames=T,
            joints=J,
        )

    out_path = OUTPUT_DIR / f"{uuid.uuid4().hex}.npz"
    cmd = [
        sys.executable, "-m", "kimodo.scripts.generate",
        req.prompt,
        "--duration", str(req.duration),
        "--output", str(out_path),
    ]
    log.info("[GEN] %s", " ".join(cmd))

    env = os.environ.copy()
    env["TEXT_ENCODER_URL"] = TEXT_ENCODER_URL

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        log.error("Kimodo failed:\n%s", stderr.decode())
        raise HTTPException(500, f"Kimodo inference failed: {stderr.decode()[-500:]}")

    if not out_path.exists():
        raise HTTPException(500, "Inference completed but output file not found.")

    data = np.load(out_path)
    T, J = data["posed_joints"].shape[:2]
    return GenerateResponse(
        npz_path=str(out_path),
        prompt=req.prompt,
        duration=req.duration,
        frames=T,
        joints=J,
    )
