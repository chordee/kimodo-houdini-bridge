# kimodo-houdini-bridge

A personal research and development project that bridges [NVIDIA Kimodo](https://github.com/nv-tlabs/kimodo) — a text-driven 3D human motion generation model — with SideFX Houdini, enabling animators to generate skeleton animation directly from a natural language prompt inside a Houdini node.

> **Scope:** This project is built and tested for personal use. It is shared openly in case others find it useful, but it comes with no guarantees of stability or completeness. Contributions and issues are welcome.

---

## What is NVIDIA Kimodo?

[Kimodo](https://github.com/nv-tlabs/kimodo) is a diffusion-based text-to-motion model developed by NVIDIA Research. Given a natural language description (e.g. `"a person jogs forward"`), it generates a 3D human motion sequence as a 77-joint SOMA skeleton animation. The model runs locally via Docker and requires an NVIDIA GPU.

---

## What this project does

The bridge provides:

- **`docker-compose.hybrid.yaml`** — deploys Kimodo in Hybrid mode (diffusion on GPU, text encoder on CPU) with a FastAPI inference server
- **`docker-compose.resident.yaml`** — an alternative deployment that preloads the model once at startup and serves inference in-process (no per-request reload), for faster iteration when you have VRAM to spare — locally or on a remote GPU box
- **`kimodo_server.py`** — a FastAPI wrapper that exposes `/generate`, `/health` and a per-job NPZ download endpoint; supports mock mode for development without running inference, and a `subprocess` (default) or `resident` inference mode
- **`kimodo_motion` HDA** — a Houdini SOP node that sends a prompt to the server, receives the output NPZ, and reconstructs the SOMA77 skeleton as KineFX-compatible geometry. It has two outputs — a per-frame animated skeleton and a static T-pose rest skeleton — with bones drawn as polyline primitives and joint `transform` / `localtransform` attributes in Houdini's row-vector convention (see [HDA Documentation](hda/README.md) for the full attribute layout)
- **`kimodo_motion_remote` HDA** — the same node for the resident deployment; it downloads the NPZ over HTTP instead of reading a mounted volume, so the server can run locally or on another machine

---

## Deployment options

The server runs in one of two modes — pick one before you deploy. The
[Setup Guide](docs/setup.md) has the step-by-step for each.

| | Hybrid (default) | Resident |
|---|---|---|
| Inference | new subprocess per request; model reloaded each call (~1–3 min overhead) | model preloaded once; every generation skips the reload |
| VRAM | used only during a generation, freed afterwards | model stays resident in VRAM while the server runs |
| Server location | local — Houdini reads the NPZ from a mounted volume | local **or** remote — Houdini downloads the NPZ over HTTP |
| Houdini node | `kimodo_motion` | `kimodo_motion_remote` |
| Compose file | `docker-compose.hybrid.yaml` | `docker-compose.resident.yaml` |

**Which to use:** start with **Hybrid** — it's the simplest and keeps VRAM free for
Houdini / Karma on the same box. Switch to **Resident** if you generate frequently and
have VRAM to spare (or a dedicated / remote GPU box): preloading removes the per-request
reload, so iteration is much faster — just keep an eye on VRAM, since the model stays loaded.

Only one runs at a time on a machine (same port / container name); switch by stopping one
compose and starting the other.

---

## Possible use cases

- Rapid motion prototyping — generate a reference clip from a description, then refine by hand
- AI-assisted animation starting point — use the generated skeleton as a base pose or keyframe reference
- Research and pipeline testing — evaluate Kimodo output inside a real DCC environment
- Pre-visualization — batch generate rough motion clips for storyboard or layout work

---

## Current limitations

- **English prompts only** — Kimodo's text encoder was trained on English descriptions
- **Slow first generation** — the first `/generate` call in production mode downloads model weights from HuggingFace (~10 min) and loads the model into GPU memory; subsequent calls within the same server session are faster. Identical requests (same prompt, duration, model) are served from cache and return instantly
- **Per-request model reload (Hybrid mode)** — the default `subprocess` inference mode spawns a new process per request, reloading the model each time (~1–3 min overhead). The `resident` mode avoids this by keeping the model in memory, at the cost of resident VRAM — see [Deployment options](#deployment-options). Background: [#1](../../issues/1)
- **SOMA77 skeleton only** — retargeting to other rigs (e.g. UE5 Mannequin, Mixamo) requires an additional step not covered here
- **GPU required** — Hybrid mode needs an NVIDIA GPU with ≥ 3 GB VRAM; CPU-only inference is not supported by Kimodo
- **Mock mode ignores prompt** — when `MOCK_MODE=1`, the server always returns the same `dev_reference.npz` regardless of the prompt; switch to `MOCK_MODE=0` for real generation

---

## Architecture

```
Houdini (kimodo_motion SOP)
    │  HTTP POST /generate
    ▼
kimodo_server (FastAPI, port 8001)
    │  subprocess: python -m kimodo.scripts.generate
    ├──► text-encoder service (CPU, port 9550)  — encodes the prompt
    └──► Kimodo diffusion (GPU)  — generates motion
    │  returns .npz path
    ▼
kimodo_motion SOP reads NPZ → outputs 77-point SOMA skeleton per frame
```

**Hybrid mode:** diffusion runs on GPU (< 3 GB VRAM); text encoding is offloaded to CPU to reduce VRAM pressure.

---

## Quick links

- [Setup Guide](docs/setup.md) ([繁體中文](docs/setup.zh-TW.md)) — step-by-step environment setup, Docker deployment, and HDA installation
- [HDA Documentation](hda/README.md) — node parameters, output attributes, NPZ format explanation
- [HDA Documentation (繁體中文)](hda/README.zh-TW.md)

---

## License

This project (bridge code, HDA, scripts) is released for personal and research use with no restrictions.

The NVIDIA Kimodo model is subject to its own license — see the [Kimodo repository](https://github.com/nv-tlabs/kimodo) for terms before use.
