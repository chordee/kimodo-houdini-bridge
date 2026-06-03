# HDA Library

[繁體中文](README.zh-TW.md)

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
| API Server URL | `http://localhost:8001` | URL of the running `kimodo_server` FastAPI service. Change only if you moved the server to a different host or port. If you started the server with a custom `KIMODO_PORT`, set this to match (e.g. `http://localhost:8002`). |
| Host Output Dir | _(your kimodo output path)_ | The host-side directory that is volume-mounted to `/workspace/output` inside Docker. The server writes NPZ files here and returns their in-container path; the node rewrites the prefix so Houdini can read the file directly. Must match the volume mount in `docker-compose.hybrid.yaml`. |
| Prompt | `a person walks forward` | Natural language description of the desired motion. Be specific: body part, direction, speed, and style all influence the result. Examples: `"a person jogs in a circle"`, `"someone waves with their right hand"`. |
| Duration (s) | `3.0` | Length of the generated motion in seconds. At 30 fps, 3 s = 90 frames. Longer clips take more inference time. |
| Model | `Kimodo-SOMA-RP-v1.1` | Kimodo model variant. `RP` (Reference Pose) conditions on a rest pose; `SEED` uses a fixed random seed for reproducibility. |
| **Generate** | — | Sends a POST request to `<API Server URL>/generate`, waits for the server to run inference, then writes the result to **NPZ Path** and recooks the node. Houdini will appear frozen during inference — this is expected. |
| Timeout (s) | `900` | Maximum seconds to wait for the server to respond. The default (15 min) covers first-run model loading from HuggingFace. Reduce on fast machines; increase if you see timeout errors. |
| NPZ Path | _(auto-set by Generate)_ | Path on the **host** to the `.npz` file produced by Kimodo. Set automatically by **Generate**; you can also set it manually to load any pre-existing NPZ file (e.g. a clip generated via the CLI) without pressing Generate. The node recooks whenever this path changes. |

#### What is an NPZ file?

An NPZ file (NumPy compressed archive) is the output format of Kimodo inference. Each file contains a complete motion clip as arrays:

| Key | Shape | Content |
|-----|-------|---------|
| `posed_joints` | `(T, 77, 3)` | World-space joint positions in metres, T frames |
| `local_rot_mats` | `(T, 77, 3, 3)` | Local rotation matrices — drives `localtransform` |
| `global_rot_mats` | `(T, 77, 3, 3)` | Global rotation matrices |
| `root_positions` | `(T, 3)` | Root (Hips) world position |
| `foot_contacts` | `(T, 6)` | Boolean foot-contact labels (6 SOMA contact points) |

You can load any Kimodo NPZ directly — paste its host path into **NPZ Path** and the node will rebuild the skeleton for that clip.

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
