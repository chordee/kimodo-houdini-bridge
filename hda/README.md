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

### Outputs

The node has **two outputs**, both producing a 77-joint SOMA skeleton.
Polyline primitives connect each parent-child pair for bone visualization.

| Output | Content | Time-dependent |
|--------|---------|----------------|
| **output0** | Animated skeleton — rebuilds every frame from the NPZ file | Yes (`$F`) |
| **output1** | T-pose (rest) skeleton — static, does not depend on the NPZ | No |

World rotations are stored in Houdini's row-vector convention (transposed from
Kimodo's column-vector matrices), so both outputs are consistent and ready for KineFX.

**output0 (animated)** carries:

| Attribute | Type | Description |
|-----------|------|-------------|
| `name` | string | Joint name (e.g. `Hips`, `LeftArm`) |
| `path` | string | Full hierarchy path (e.g. `/Hips/Spine1/Spine2`) |
| `parent_id` | int | Parent joint index; -1 for root (`Hips`) |
| `transform` | float[9] | World-space rotation (row-major 3×3) |
| `localtransform` | float[16] | Local 4×4 transform relative to parent (row-major) |

**output1 (T-pose)** carries `name` and `transform` (float[9] world-space rotation);
joint positions are the SOMA77 neutral pose from Kimodo's skeleton definition.

Connect output0 to **Rig Pose SOP** for KineFX rig binding. Use output1 as the rest skeleton input for **Bone Capture** or **Skin SOP**.

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| API Server URL | `http://localhost:8001` | URL of the running `kimodo_server` FastAPI service. Change only if you moved the server to a different host or port. If you started the server with a custom `KIMODO_PORT`, set this to match (e.g. `http://localhost:8002`). |
| Host Output Dir | _(your kimodo output path)_ | The host-side directory that is volume-mounted to `/workspace/output` inside Docker. The server writes NPZ files here and returns their in-container path; the node rewrites the prefix so Houdini can read the file directly. Must match the volume mount in `docker-compose.hybrid.yaml`. |
| Prompt | `a person walks forward` | Natural language description of the desired motion. Be specific: body part, direction, speed, and style all influence the result. Examples: `"a person jogs in a circle"`, `"someone waves with their right hand"`. |
| Duration (s) | `3.0` | Length of the generated motion in seconds. At 30 fps, 3 s = 90 frames. Longer clips take more inference time. |
| Model | `Kimodo-SOMA-RP-v1.1` | Kimodo model variant. `RP` (Reference Pose) conditions on a rest pose; `SEED` uses a fixed random seed for reproducibility. |
| Force Regenerate | `off` | Bypass the server cache and re-run inference even if a clip with the same prompt, duration, and model already exists. See [Caching](#caching). |
| **Generate** | — | Submits the prompt to `<API Server URL>/generate` and returns immediately with a job ID. Inference runs on the server while a background thread polls for progress, so **Houdini stays responsive**. When the job finishes, **NPZ Path** is updated and the node recooks automatically. |
| **Cancel** | — | Cancels the currently running job (terminates the server-side inference process). Only meaningful while a job is in progress. |
| Status | _(read-only)_ | Shows the live job state: `Queued`, `Running... (Ns)` with elapsed seconds, `Done (Ns)` — or `Done (Ns) (cached)` on a cache hit — `Failed`, or `Cancelled`. Updated by the background poll thread. |
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

### Caching

The server caches results by an MD5 of `prompt + duration + model`, using that hash as the output filename (e.g. `a872d0b….npz`) with a sibling `.json` metadata file (prompt, duration, model, frame count, timestamp). Pressing **Generate** with parameters that match an existing clip returns it instantly — the **Status** field shows `Done (cached)` and no inference runs.

To force a fresh run (e.g. for a `SEED` model variant, or to get a different take), enable **Force Regenerate**. To clear the cache, delete the `.npz`/`.json` files from your **Host Output Dir**.

### Prerequisites

The following Docker services must be running before pressing **Generate**:

```bash
# Inside the kimodo/ directory
docker compose -f docker-compose.hybrid.yaml up text-encoder -d  # wait until healthy
docker compose -f docker-compose.hybrid.yaml up api -d
```

---

## Rebuilding the HDA

If you need to regenerate the HDA (e.g. after editing the cook scripts embedded in `scripts/create_hda.py`):

```bash
# 1. Rebuild the packed HDA at the repo root
hython scripts/create_hda.py "<npz_default>" "<host_output_dir>"

# 2. Add the help card and save the unpacked HDA to hda/
hython scripts/_add_help.py
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
