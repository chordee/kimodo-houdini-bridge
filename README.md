# kimodo-houdini-bridge

A bridge that connects [NVIDIA Kimodo](https://github.com/nv-tlabs/kimodo) — a text-driven 3D human motion generation model — to SideFX Houdini, so animators can generate skeleton animation directly from a Houdini node by typing a natural-language prompt.

---

## Architecture: Hybrid Inference Mode

This project runs Kimodo in **Hybrid mode** by default: the diffusion model runs on the GPU while the text encoder is offloaded to CPU via Kimodo's official `TEXT_ENCODER_DEVICE=cpu` flag. This keeps GPU VRAM usage below 3 GB, making the setup accessible on mid-range cards.

| Mode | GPU VRAM | Speed | Suitable hardware |
|------|:--------:|-------|-------------------|
| **Hybrid** (default) | < 3 GB | Near full-GPU (text encoding cached after first run) | Any NVIDIA GPU with >= 3 GB VRAM; >= 16 GB system RAM recommended |
| **Full GPU** | ~17 GB | Fastest | High-end GPUs with >= 24 GB VRAM |

To switch to Full GPU mode, remove `TEXT_ENCODER_DEVICE=cpu` from `docker-compose.hybrid.yaml` and give the text-encoder service a GPU reservation.

---

## Prerequisites

### Software

| Dependency | Notes |
|------------|-------|
| Docker Desktop (Windows/Mac) or Docker Engine (Linux) | Enable WSL2 backend on Windows |
| NVIDIA Driver (latest stable) | Required even for Hybrid mode — diffusion runs on GPU |
| [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) | Enables `--gpus` flag in Docker |
| Houdini H20.5 or later | Provides `hython` (Python 3.10/3.11) |
| Python 3.x (system) | For running `scripts/check_env.py` only; no venv needed |

### Hardware

- NVIDIA GPU with >= 3 GB VRAM (Hybrid mode)
- >= 16 GB system RAM (text encoder runs on CPU)
- >= 50 GB free disk space (model checkpoints + Docker images)

### Accounts / Tokens

- HuggingFace account and access token — required to download Kimodo model weights
- Accept the Kimodo model license on its HuggingFace page before downloading

---

## Step 0: Environment Validation

Clone this repo and run the pre-flight check:

```bash
git clone https://github.com/<your-org>/kimodo-houdini-bridge.git
cd kimodo-houdini-bridge
python scripts/check_env.py
```

The script checks Docker availability, GPU pass-through, system RAM, and port availability. Fix any `FAIL` items before continuing.

Expected output when everything is ready:

```
[PASS] Docker CLI found
[PASS] Docker daemon running
[PASS] Docker GPU pass-through (nvidia-smi visible in container)
[PASS] System RAM >= 16 GB — XX.X GB detected
[PASS] Port 8000 available
[PASS] Port 9550 available

Result: 6/6 checks passed. Ready for Phase 1.
```

---

## Step 1: Clone Kimodo & Build Docker Image

```bash
# Clone Kimodo (e.g. alongside this repo)
git clone https://github.com/nv-tlabs/kimodo.git
cd kimodo

# Clone the Kimodo-specific Viser fork — required before building
git clone https://github.com/nv-tlabs/kimodo-viser.git
```

**Windows only:** Git may convert shell script line endings to CRLF, which breaks the Docker entrypoint. Fix before building:

```bash
sed -i 's/\r//' kimodo/scripts/docker-entrypoint.sh
```

```bash
# Build the image — uses Kimodo's official CUDA-based Dockerfile
# First build downloads the base image (~10 GB) and installs all dependencies
docker build -t kimodo:1.0 .
```

> The base image is `nvcr.io/nvidia/pytorch:24.10-py3`. A fast internet connection or NGC access is required.

---

## Step 2: Start Services & Generate a Motion Clip

Copy `docker-compose.hybrid.yaml` from this repo into the `kimodo/` directory and create the output folder:

```bash
cp ../kimodo-houdini-bridge/docker-compose.hybrid.yaml .
mkdir -p output
```

Export your HuggingFace token so the container can download model weights:

```bash
# Option A: if you have already run `hf auth login`, read it from the cache
export HUGGING_FACE_HUB_TOKEN=$(cat ~/.cache/huggingface/token)

# Option B: paste your token directly
export HUGGING_FACE_HUB_TOKEN=hf_...
```

Start the text-encoder service (runs on CPU, stays up between generations):

```bash
docker compose -f docker-compose.hybrid.yaml up text-encoder -d

# Wait until status shows "healthy"
# First start downloads the LLM2Vec text encoder model and loads it on CPU — allow ~5-10 minutes
docker compose -f docker-compose.hybrid.yaml ps
```

Run one generation (diffusion runs on GPU):

```bash
docker compose -f docker-compose.hybrid.yaml run --rm demo
```

Verify the output:

```bash
ls -lh output/test.npz
```

```python
# In Houdini Python Shell or any Python
import numpy as np
data = np.load("output/test.npz")
print(list(data.keys()))
# ['local_rot_mats', 'global_rot_mats', 'posed_joints', 'root_positions',
#  'smooth_root_pos', 'foot_contacts', 'global_root_heading']

joints = data["posed_joints"]
print(joints.shape)       # (T, 77, 3)  — T = frames, 77 = SOMA joints
print(data["local_rot_mats"].shape)   # (T, 77, 3, 3)
print(data["foot_contacts"].shape)    # (T, 6) bool — 6 contact points in SOMA skeleton
```

Save a copy as the development reference file:

```bash
cp output/test.npz output/dev_reference.npz
```

---

## Step 3: Houdini Python Setup

Install required packages into Houdini's bundled Python:

```bash
# Linux / macOS
$HFS/bin/hython -m pip install requests scipy numpy

# Windows (adjust HFS path to your Houdini installation)
"C:\Program Files\Side Effects Software\Houdini 21.0.xxx\bin\hython.exe" -m pip install requests scipy numpy
```

Verify inside the Houdini Python Shell:

```python
import numpy as np
import requests
import scipy
print(np.__version__, requests.__version__, scipy.__version__)
```

All three should print version strings without import errors.

---

## Step 4: Start the API Server

Copy `kimodo_server.py` from this repo into the `kimodo/` directory alongside the compose file:

```bash
cp ../kimodo-houdini-bridge/kimodo_server.py .
```

Start the API service (mock mode — returns `dev_reference.npz` without re-running inference):

```bash
docker compose -f docker-compose.hybrid.yaml up api -d
```

Verify:

```bash
curl http://localhost:8001/health
# {"status":"ok","mock_mode":true}

curl -X POST http://localhost:8001/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "a person walks forward", "duration": 3.0}'
# {"npz_path":"/workspace/output/dev_reference.npz","prompt":"...","frames":90,"joints":77}
```

> **Port note:** Port 8000 is reserved by Docker Desktop on Windows. The API runs on **8001**.

## Step 5: Connect from Houdini

In the Houdini Python Shell:

```python
import requests

resp = requests.post(
    "http://localhost:8001/generate",
    json={"prompt": "a person walks forward", "duration": 3.0},
    timeout=30,
)
resp.raise_for_status()
data = resp.json()
print(data["npz_path"])  # /workspace/output/dev_reference.npz
print(data["frames"])    # 90
print(data["joints"])    # 77
```

Load the NPZ (Docker `/workspace/output/` maps to `./output/` on the host):

```python
import numpy as np

host_path = data["npz_path"].replace("/workspace/output", "D:/dev/kimodo/output")
motion = np.load(host_path)
print(motion["posed_joints"].shape)  # (90, 77, 3)
```

---

## Next Steps

- **Phase 3** — HDA development: build a Houdini Digital Asset that drives skeleton animation from NPZ output
- **Phase 4** — Caching, error handling, and UI polish

---

## License

This project is an integration bridge and does not redistribute Kimodo model weights.
Kimodo is subject to its own license — see the [Kimodo repository](https://github.com/nv-tlabs/kimodo) for details.
