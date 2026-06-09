# HDA Library

[繁體中文](README.zh-TW.md)

This directory contains the Houdini Digital Asset for the Kimodo-Houdini bridge,
stored in **unpacked (VCS-friendly) format** — a directory ending in `.hda/`.

---

## kimodo_motion.hda

**Type:** `Sop/kimodo_motion`  
**Context:** SOP (geometry network)  
**Houdini:** H20.5+

A SOP node that generates 3D human motion from a natural language prompt via the
[NVIDIA Kimodo](https://github.com/nv-tlabs/kimodo) model. It sends the prompt to a
running `kimodo_server`, downloads the resulting NPZ over HTTP, and rebuilds the
77-joint SOMA motion as KineFX-compatible geometry — animated skeleton, rest
skeletons, and a skinned body mesh.

### Outputs

Four outputs. World rotations use Houdini's row-vector / row-major convention
(transposed from Kimodo's column-vector matrices). Skeletons connect each
parent-child joint pair with a polyline primitive.

| # | Label | Content |
|---|-------|---------|
| 0 | **Animated Pose** | Per-frame animated skeleton. `name`, `path`, `parent_id`, `transform` (float[9] world rotation), `localtransform` (float[16] local 4×4). |
| 1 | **Capture Pose** | The A-pose rest skeleton the body mesh is bound to (feet on floor). `name`, `transform`. |
| 2 | **Rest Geometry** | The SOMA77 body mesh in its bind pose, with a KineFX `boneCapture` attribute (weights + bind from Kimodo's skinning). |
| 3 | **T-Pose** | A T-pose skeleton (`name`, `transform`) for reference / retargeting. |

**To deform the body**, drop a **`kinefx::jointdeform`** (Labs/KineFX Joint Deform) and wire:
input 0 = **Rest Geometry** (output 2), input 1 = **Capture Pose** (output 1),
input 2 = **Animated Pose** (output 0). The mesh follows the animation and returns to
the bind pose at rest. (output 0 also drives a **Rig Pose / Bone Deform** workflow directly.)

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| API Server URL | `http://localhost:8001` | URL of the running `kimodo_server`. Point at the GPU host if the server runs elsewhere. |
| Download Dir | `$HIP/kimodo_cache` | Local folder where finished NPZ files are downloaded from the server over HTTP. |
| Prompt | `a person walks forward` | Natural language description of the motion. Be specific about body part, direction, speed and style. |
| Duration (s) | `3.0` | Length of the clip in seconds. At 30 fps, 3 s = 90 frames. |
| Model | `Kimodo-SOMA-RP-v1.1` | Kimodo model variant. `RP` conditions on a rest pose; `SEED` uses a fixed seed for reproducibility. |
| Force Regenerate | `off` | Bypass the server cache and re-run inference even if a matching clip exists. |
| Constraints File | _(empty)_ | Optional [Kimodo constraints](https://research.nvidia.com/labs/sil/projects/kimodo/docs/key_concepts/constraints.html) JSON file (`*.json`). See [Constraints](#constraints-optional). |
| Constraints JSON | _(empty)_ | Optional inline constraints JSON; takes precedence over Constraints File. |
| **Generate** | — | Submits the prompt to `<API Server URL>/generate` and returns immediately with a job ID. A background thread polls for progress, so Houdini stays responsive. When done, the NPZ is downloaded to **Download Dir**, **NPZ Path** is set, and the node recooks. |
| **Cancel** | — | Cancels the job. A resident server can't interrupt an already-running generation — Cancel stops a queued job or discards the result. |
| Status | _(read-only)_ | Live job state: `Queued`, `Running... (Ns)`, `Downloading...`, `Done (Ns)`, `Failed`, `Cancelled`. |
| NPZ Path | _(empty)_ | The `.npz` the node reads to build the skeleton — a **file field** (browse, `*.npz`). Set by Generate; you can also point it at any compatible NPZ by hand (no Generate/server needed). Empty = empty geometry until set. |

#### What is an NPZ file?

An NPZ file (NumPy compressed archive) is Kimodo's inference output. The node reads:

| Key | Shape | Content |
|-----|-------|---------|
| `posed_joints` | `(T, 77, 3)` | World-space joint positions in metres — **read by the node** (joint placement) |
| `global_rot_mats` | `(T, 77, 3, 3)` | World-space joint rotations — **read by the node**; `transform` / `localtransform` are derived from these |
| `local_rot_mats` | `(T, 77, 3, 3)` | Local rotation matrices (Kimodo output; not required by the node) |
| `root_positions` | `(T, 3)` | Root (Hips) world position |
| `foot_contacts` | `(T, 6)` | Boolean foot-contact labels |

The node only needs **`posed_joints`** and **`global_rot_mats`** (SOMA77 joint order) to
rebuild the skeleton. Any compatible NPZ works regardless of how it was produced — set
**NPZ Path** to it. **Download Dir** is only used by **Generate**.

### Constraints (optional)

[Kimodo constraints](https://research.nvidia.com/labs/sil/projects/kimodo/docs/key_concepts/constraints.html)
steer the generated motion to hit spatial targets: a root 2D path or waypoints,
full-body keyframes, or end-effector (hand/foot) targets. Supply a JSON **list of
constraint dicts** — point **Constraints File** at a `*.json` (e.g. one exported from
the Kimodo demo) or paste it into **Constraints JSON** (which wins when non-empty).
Leave both empty for unconstrained generation.

Targets use Kimodo's coordinate space: **Y-up, metres, +Z forward, root at XZ = (0, 0)
on frame 0** — the same world space this node outputs. The simplest type is a `root2d`
waypoint set (`frame_indices` + `[x, z]` pairs):

```json
[{"type": "root2d", "frame_indices": [0, 90], "smooth_root_2d": [[0, 0], [2, 1]]}]
```

Other types (`fullbody`, `left-hand`/`right-hand`/`left-foot`/`right-foot`) also need
per-joint rotations; author them in the Kimodo demo and export the JSON. Constraints are
part of the cache key, so a new constraint set triggers a fresh generation.

### Caching

The server caches results by a SHA-256 hash of `prompt + duration + model + constraints`.
Re-running with identical settings returns instantly (Status shows `Done (cached)`); enable
**Force Regenerate** to bypass it.

### Prerequisites

A running `kimodo_server`. From the kimodo dir (see [Setup Guide](../docs/setup.md)):

```bash
docker compose -f docker-compose.bridge.yaml up text-encoder -d   # wait until healthy
MOCK_MODE=0 docker compose -f docker-compose.bridge.yaml up api -d
```

The model is preloaded from the local HuggingFace cache (offline), so the weights must
be cached first (`huggingface-cli download nvidia/Kimodo-SOMA-RP-v1.1`). It then stays
resident in VRAM while the api container runs — stop it to free VRAM.

---

## Rebuilding the HDA

If you edit the cook scripts or skinning, regenerate the HDA:

```bash
# 1. Build the embedded skin geometry (mesh + capture, A-pose skeleton)
hython scripts/build_skin.py

# 2. Rebuild the packed HDA at the repo root (embeds the skin sections)
hython scripts/create_hda.py

# 3. Add the help card and save the unpacked HDA to hda/
hython scripts/_add_help.py
```

---

## Installing in Houdini

### Option A — Houdini Package (recommended)

Copy the package file to your Houdini packages directory, then edit
`KIMODO_BRIDGE_ROOT` to the absolute path of this repo:

```bash
# Windows
copy kimodo-houdini-bridge.json %HOUDINI_USER_PREF_DIR%\packages\
# Linux / macOS
cp kimodo-houdini-bridge.json ~/houdiniXX.Y/packages/
```

Restart Houdini — the `kimodo_motion` SOP appears in the Tab menu under **Kimodo**.

### Option B — Manual install

In Houdini: **Assets → Install Asset Library…** → select `hda/kimodo_motion.hda/`.
