# HDA Library

This directory contains Houdini Digital Assets for the Kimodo-Houdini bridge.
Each HDA is stored in **unpacked (VCS-friendly) format** — a directory ending in `.hda/`
that can be diffed and reviewed in git.

---

## kimodo_motion.hda

**Type:** `Sop/kimodo_motion`  
**Context:** SOP (geometry network)  
**Houdini:** H20.5+

A SOP node that generates 3D human motion from a natural language prompt via
the [NVIDIA Kimodo](https://github.com/nv-tlabs/kimodo) model, outputting a
77-joint SOMA skeleton compatible with Houdini KineFX.

### Output geometry

| Attribute | Type | Description |
|-----------|------|-------------|
| `name` | string | Joint name (e.g. `Hips`, `LeftArm`) |
| `parent_id` | int | Parent joint index; -1 for root (`Hips`) |
| `localtransform` | float[16] | Local rotation matrix + position (row-major 4×4) |

77 points per frame. Connect to **Rig Pose SOP** for KineFX rig binding.

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| API Server URL | `http://localhost:8001` | Running `kimodo_server` FastAPI service |
| Host Output Dir | _(your kimodo output path)_ | Host path mapped to `/workspace/output` in Docker |
| Prompt | `a person walks forward` | Natural language motion description |
| Duration (s) | `3.0` | Motion length in seconds |
| Model | `Kimodo-SOMA-RP-v1.1` | Kimodo model variant |
| **Generate** | — | POST to API, update NPZ, recook |
| NPZ Path | _(auto-set by Generate)_ | Path to the output `.npz` file |

### Prerequisites

The following Docker services must be running before pressing **Generate**:

```bash
# Inside the kimodo/ directory
docker compose -f docker-compose.hybrid.yaml up text-encoder -d  # wait until healthy
docker compose -f docker-compose.hybrid.yaml up api -d
```

---

## Rebuilding the HDA

If you need to regenerate the HDA (e.g. after modifying `scripts/sop_cook.py`):

```bash
# 1. Rebuild the packed HDA
hython scripts/create_hda.py "<npz_default>" "<host_output_dir>"

# 2. Add the help card and save to hda/
hython scripts/_add_help.py

# 3. Unpack to VCS-friendly format
mkdir hda/kimodo_motion.hda
hotl -t hda/kimodo_motion.hda hda/kimodo_motion_packed.hda
rm hda/kimodo_motion_packed.hda
```

---

## Installing in Houdini

### Option A — Houdini Package (recommended)

Copy the included package file to your Houdini packages directory:

```bash
# Windows
copy kimodo-houdini-bridge.json %HOUDINI_USER_PREF_DIR%\packages\

# Linux / macOS
cp kimodo-houdini-bridge.json ~/houdiniXX.Y/packages/
```

Edit `kimodo-houdini-bridge.json` to set `KIMODO_BRIDGE_ROOT` to the absolute
path of this repo. Restart Houdini — the `kimodo_motion` SOP will appear
in the Tab menu under **Kimodo**.

### Option B — Manual install

In Houdini: **Assets → Install Asset Library…** → select this directory
(`hda/kimodo_motion.hda/`).
