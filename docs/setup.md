# Setup Guide

[繁體中文](setup.zh-TW.md)

This project supports two deployment paths. Skim the roadmap, do the **Common Setup**,
then follow **only** the path you need.

## Deployment roadmap

| | Path A — Local (Hybrid) | Path B — Remote / Resident |
|---|---|---|
| Use when | Houdini and the GPU are on the same machine | the GPU lives on a separate / more powerful box |
| Compose file | `docker-compose.hybrid.yaml` | `docker-compose.resident.yaml` |
| Inference | one subprocess per request (model reloaded each call) | model preloaded once, served in-process |
| Houdini node | `kimodo_motion` | `kimodo_motion_remote` |
| NPZ → Houdini | mounted volume (path rewrite) | HTTP download |
| Extra requirement | — | model weights pre-cached (loads offline) |

Both paths share the same Docker image, `kimodo_server.py`, HDAs, and skeleton output —
they differ only in which compose you start and which node you use.

---

# Common Setup (both paths)

## 1. Environment validation

Clone this repo and run the pre-flight check:

```bash
git clone https://github.com/<your-org>/kimodo-houdini-bridge.git
cd kimodo-houdini-bridge
python scripts/check_env.py
```

The script checks Docker availability, GPU pass-through, system RAM, and port availability.
Fix any `FAIL` items before continuing.

## 2. Clone Kimodo & build the Docker image

```bash
# Clone Kimodo (e.g. alongside this repo)
git clone https://github.com/nv-tlabs/kimodo.git
cd kimodo

# Clone the Kimodo-specific Viser fork — required before building
git clone https://github.com/nv-tlabs/kimodo-viser.git
```

**Windows only:** Git may convert shell script line endings to CRLF, which breaks the
Docker entrypoint. Fix before building:

```bash
sed -i 's/\r//' kimodo/scripts/docker-entrypoint.sh
```

```bash
# Build the image — uses Kimodo's official CUDA-based Dockerfile.
# First build downloads the base image (~10 GB) and installs all dependencies.
docker build -t kimodo:1.0 .
```

> The base image is `nvcr.io/nvidia/pytorch:24.10-py3`. A fast internet connection or NGC access is required.

## 3. HuggingFace token

Export your token so the container can download model weights:

```bash
# Option A: if you have already run `hf auth login`, read it from the cache
export HUGGING_FACE_HUB_TOKEN=$(cat ~/.cache/huggingface/token)

# Option B: paste your token directly
export HUGGING_FACE_HUB_TOKEN=hf_...
```

## 4. Houdini Python packages

Install the packages the HDA needs into Houdini's bundled Python:

```bash
# Linux / macOS
$HFS/bin/hython -m pip install requests scipy numpy

# Windows (adjust HFS path to your Houdini installation)
"C:\Program Files\Side Effects Software\Houdini 21.0.xxx\bin\hython.exe" -m pip install requests scipy numpy
```

## 5. Install the HDAs

The repo ships both HDAs prebuilt under `hda/` — install them in Houdini
(**Assets → Install Asset Library…**, or use the package file). See
[hda/README.md](../hda/README.md) for full options. You only need the node for
your path: `kimodo_motion` (Path A) or `kimodo_motion_remote` (Path B).

> Developers who edit the cook scripts can rebuild both HDAs with
> `hython scripts/create_hda.py "<npz_default>" "<host_output_default>"` then
> `hython scripts/_add_help.py` — see [hda/README.md](../hda/README.md#rebuilding-the-hda).

---

# Path A — Local (Hybrid)

Houdini and the GPU are on the same machine; the node reads the NPZ from a mounted volume.

## A1. Deploy the server into the kimodo dir

```bash
cd /path/to/kimodo
cp /path/to/kimodo-houdini-bridge/docker-compose.hybrid.yaml .
cp /path/to/kimodo-houdini-bridge/kimodo_server.py .
mkdir -p output
```

## A2. Start the text-encoder (CPU, stays up between generations)

```bash
docker compose -f docker-compose.hybrid.yaml up text-encoder -d
# First start downloads the text encoder and loads it on CPU — allow ~5-10 minutes.
docker compose -f docker-compose.hybrid.yaml ps   # wait for "healthy"
```

## A3. Create a reference clip (enables mock mode + caches weights)

```bash
docker compose -f docker-compose.hybrid.yaml run --rm demo
cp output/test.npz output/dev_reference.npz
```

This runs one real generation on the GPU, which also downloads and caches the model weights.

## A4. Start the API server

```bash
# Mock mode (returns dev_reference.npz, no inference — handy for HDA development)
docker compose -f docker-compose.hybrid.yaml up api -d
curl http://localhost:8001/health     # {"status":"ok","mock_mode":true,"inference_mode":"subprocess"}

# Live mode (full diffusion each call; text-encoder must be healthy)
docker compose -f docker-compose.hybrid.yaml stop api
MOCK_MODE=0 docker compose -f docker-compose.hybrid.yaml up api -d
```

> **Port note:** Port 8000 is reserved by Docker Desktop on Windows; the API defaults to **8001**.
> Use another port with `KIMODO_PORT=8002 docker compose -f docker-compose.hybrid.yaml up api -d`
> and set the node's **API Server URL** to match.

## A5. Generate from Houdini

Drop a **`kimodo_motion`** node in a SOP network. Set **API Server URL** to
`http://localhost:8001`, **Host Output Dir** to your `kimodo/output/` path, then press **Generate**.

---

# Path B — Remote / Resident

The GPU lives on a separate box; the model is preloaded once and the node fetches the NPZ over HTTP.
Run B1–B3 **on the GPU box**.

## B1. Pre-cache the model weights (one time)

The resident server loads from the local HuggingFace cache and skips the network at startup
(`HF_HUB_OFFLINE=1`), so the weights must already be cached on this box. Either:

- you already ran a generation here (Path A leaves the weights cached), or
- download them explicitly:

```bash
huggingface-cli download nvidia/Kimodo-SOMA-RP-v1.1
```

(Repeat for any other model you select in the node, e.g. `nvidia/Kimodo-SOMA-SEED-v1.1`.)

## B2. Deploy the server into the kimodo dir

```bash
cd /path/to/kimodo
cp /path/to/kimodo-houdini-bridge/docker-compose.resident.yaml .
cp /path/to/kimodo-houdini-bridge/kimodo_server.py .
mkdir -p output
export HUGGING_FACE_HUB_TOKEN=$(cat ~/.cache/huggingface/token)
```

## B3. Start the text-encoder + resident API

```bash
docker compose -f docker-compose.resident.yaml up text-encoder -d   # wait for "healthy"
docker compose -f docker-compose.resident.yaml up api -d
```

The api preloads the model at startup (watch `docker logs kimodo-api` for
`[RESIDENT] model ready` → `Application startup complete`). Then:

```bash
curl http://<gpu-box>:8001/health    # {"status":"ok","mock_mode":false,"inference_mode":"resident"}
```

## B4. Generate from Houdini

Drop a **`kimodo_motion_remote`** node. Set **API Server URL** to
`http://<gpu-box>:8001`, leave **Download Dir** at `$HIP/kimodo_cache` (or any local
folder), then press **Generate** — the finished NPZ is downloaded there automatically.
