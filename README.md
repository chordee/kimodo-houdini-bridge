# kimodo-houdini-bridge

A personal research and development project that bridges [NVIDIA Kimodo](https://github.com/nv-tlabs/kimodo) — a text-driven 3D human motion generation model — with SideFX Houdini, enabling animators to generate skeleton animation directly from a natural language prompt inside a Houdini node.

> **Scope:** This project is built and tested for personal use. It is shared openly in case others find it useful, but it comes with no guarantees of stability or completeness. Contributions and issues are welcome.

---

## What is NVIDIA Kimodo?

[Kimodo](https://github.com/nv-tlabs/kimodo) is a diffusion-based text-to-motion model developed by NVIDIA Research. Given a natural language description (e.g. `"a person jogs forward"`), it generates a 3D human motion sequence as a 77-joint SOMA skeleton animation. The model runs locally via Docker and requires an NVIDIA GPU.

---

## What this project does

The bridge provides:

- **`docker-compose.bridge.yaml`** — deploys Kimodo with a FastAPI inference server. The model is preloaded once at startup and inference runs in-process (no per-request reload). The server can run on your workstation or a separate GPU box; the model stays resident in VRAM while it runs.
- **`kimodo_server.py`** — a FastAPI wrapper exposing `/generate`, `/health` and a per-job NPZ download endpoint. Supports a mock mode for development without a GPU.
- **`kimodo_motion` HDA** — a Houdini SOP node that sends a prompt to the server, downloads the resulting NPZ over HTTP, and rebuilds the SOMA77 motion as KineFX-compatible geometry. Four outputs:
  - **Animated Pose** — per-frame skeleton (`name`, `path`, `parent_id`, `transform`, `localtransform`)
  - **Capture Pose** — A-pose rest skeleton the body mesh is bound to (feet on floor)
  - **Rest Geometry** — skinned SOMA77 body mesh with a KineFX `boneCapture` attribute
  - **T-Pose** — a T-pose skeleton for reference / retargeting

  Drive the mesh with `kinefx::jointdeform` (Rest Geometry + Capture Pose + Animated Pose). See [HDA Documentation](hda/README.md) for parameters and the full attribute layout.

---

## Possible use cases

- Rapid motion prototyping — generate a reference clip from a description, then refine by hand
- AI-assisted animation starting point — use the generated skeleton as a base pose or keyframe reference
- Research and pipeline testing — evaluate Kimodo output inside a real DCC environment
- Pre-visualization — batch generate rough motion clips for storyboard or layout work
- Standalone SOMA loader — even without the inference server (so no generation), the `kimodo_motion` HDA reads any compatible SOMA77 NPZ produced elsewhere and reconstructs the skeleton motion as KineFX geometry in Houdini; just point **NPZ Path** at the file
- Controlled generation — steer the motion with optional [Kimodo constraints](https://research.nvidia.com/labs/sil/projects/kimodo/docs/key_concepts/constraints.html) (root 2D path/waypoints, full-body keyframes, hand/foot targets): supply them as JSON, connect a Houdini curve/points to drive a root path, or use the node's **Create Pose Rig** to pose and keyframe a skeleton for full-body / end-effector constraints — all on the node; see [HDA Documentation](hda/README.md#constraints-optional)

---

## Current limitations

- **English prompts only** — Kimodo's text encoder was trained on English descriptions
- **Slow server startup** — the server preloads the model at startup (and the text encoder loads on CPU); generations afterwards skip the load. The model is read from the local HuggingFace cache offline, so the weights must be cached first (a one-time `huggingface-cli download nvidia/Kimodo-SOMA-RP-v1.1`). Identical requests (same prompt, duration, model) are served from cache and return instantly.
- **Resident VRAM** — the model stays in VRAM while the `api` container runs; stop the container to free it. The in-process design (preload + serve) was tracked in [#1](../../issues/1).
- **SOMA77 skeleton only** — retargeting to other rigs (e.g. UE5 Mannequin, Mixamo) requires an additional step not covered here
- **GPU required** — needs an NVIDIA GPU with ≥ 4 GB VRAM (≥ 6 GB recommended if sharing with Houdini); CPU-only inference is not supported by Kimodo
- **Mock mode ignores prompt** — when `MOCK_MODE=1`, the server always returns the same `dev_reference.npz` regardless of the prompt; switch to `MOCK_MODE=0` for real generation

---

## Architecture

```
Houdini (kimodo_motion SOP)
    │  POST /generate ─────────────►  kimodo_server (FastAPI, port 8001)
    │                                   │  resident model (preloaded), inference in-process
    │                                   ├──► text-encoder service (CPU, 9550) — encodes prompt
    │                                   └──► Kimodo diffusion (GPU) — generates motion
    │  GET /jobs/{id}/download ◄──────  writes .npz to OUTPUT_DIR
    ▼
kimodo_motion SOP → 4 outputs: Animated Pose / Capture Pose / Rest Geometry / T-Pose
    └─► kinefx::jointdeform (mesh + skeletons) → deformed body
```

Diffusion runs on GPU (~3–4 GB VRAM resident); text encoding is offloaded to CPU to reduce VRAM pressure. The model stays resident in the `api` container's VRAM while it runs. Houdini fetches the NPZ over HTTP, so the server can live on a separate GPU box.

---

## Quick links

- [Setup Guide](docs/setup.md) ([繁體中文](docs/setup.zh-TW.md)) — step-by-step environment setup, Docker deployment, and HDA installation
- [HDA Documentation](hda/README.md) — node parameters, output attributes, NPZ format explanation
- [HDA Documentation (繁體中文)](hda/README.zh-TW.md)

---

## License

This project (bridge code, HDA, scripts) is released for personal and research use with no restrictions.

The NVIDIA Kimodo model is subject to its own license — see the [Kimodo repository](https://github.com/nv-tlabs/kimodo) for terms before use.
