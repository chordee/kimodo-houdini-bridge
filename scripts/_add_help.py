"""Add help cards to both kimodo HDAs and save them (unpacked) to hda/."""
import hou, os

_HERE = os.path.dirname(__file__)


def build_help(remote: bool) -> str:
    title = "Kimodo Motion Generator" + (" (Remote)" if remote else "")

    overview_extra = (
        "\n"
        "This is the remote/resident variant: it targets a `kimodo_server` running\n"
        "in resident mode (model preloaded — see docker-compose.resident.yaml) and\n"
        "downloads the finished NPZ over HTTP, so the server can live on another\n"
        "machine.\n"
        if remote else ""
    )

    transport_parm = (
        "Download Dir:\n"
        "    Local folder where finished NPZ files are downloaded from the server\n"
        "    over HTTP. Defaults to `$HIP/kimodo_cache`.\n"
        if remote else
        "Host Output Dir:\n"
        "    The host-side directory mapped to `/workspace/output` inside Docker.\n"
        "    Must contain `dev_reference.npz` when running in mock mode.\n"
    )

    generate_note = (
        "Generate:\n"
        "    Submits the prompt to `<Server URL>/generate` and returns immediately\n"
        "    with a job ID. A background thread polls for progress, so Houdini stays\n"
        "    responsive. When the job finishes the NPZ is downloaded to __Download\n"
        "    Dir__, __NPZ Path__ is set to the local copy, and the node recooks.\n"
        if remote else
        "Generate:\n"
        "    Submits the prompt to `<Server URL>/generate` and returns immediately\n"
        "    with a job ID. Inference runs on the server while a background thread\n"
        "    polls for progress, so Houdini stays responsive. When the job finishes,\n"
        "    __NPZ Path__ is updated and the node recooks automatically.\n"
    )

    cancel_note = (
        "Cancel:\n"
        "    Cancels the job. On a resident server an already-running generation\n"
        "    cannot be interrupted — Cancel stops a queued job or discards the result.\n"
        if remote else
        "Cancel:\n"
        "    Cancels the running job (terminates the server-side inference process).\n"
        "    Only meaningful while a job is in progress.\n"
    )

    return (
        f"= {title} =\n"
        "\n"
        "#type: node\n"
        "#context: sop\n"
        "#tags: kimodo, motion, ai, kinefx, animation\n"
        "\n"
        "Generates 3D human motion from a text prompt using NVIDIA Kimodo,\n"
        "outputting a 77-joint SOMA skeleton compatible with Houdini KineFX.\n"
        "\n"
        "== Overview ==\n"
        "\n"
        "The Kimodo Motion Generator node connects to a running\n"
        "[Kimodo|https://github.com/nv-tlabs/kimodo] inference server and\n"
        "generates skeleton animation from a natural language description.\n"
        f"{overview_extra}"
        "\n"
        "Press __Generate__ to send a POST request to the API server.\n"
        "The resulting NPZ file is loaded and the skeleton is rebuilt on every\n"
        "frame, driving 77 SOMA joints as points with KineFX `name`, `transform`,\n"
        "and `localtransform` attributes.\n"
        "\n"
        "== Quick Start ==\n"
        "\n"
        "# Start the Docker services (text-encoder + api) as described in the README.\n"
        "# Set __Prompt__ to describe the desired motion, and __Duration__ in seconds.\n"
        "# Press __Generate__. Watch __Status__ for progress; the node cooks automatically\n"
        "  when the NPZ is ready. Use __Cancel__ to abort a running job.\n"
        "# Set the Houdini frame range to match the clip length and play back.\n"
        "# Connect __output0__ to a __Rig Pose SOP__ (or any KineFX node) and use\n"
        "  __output1__ as the rest skeleton.\n"
        "\n"
        "== Parameters ==\n"
        "\n"
        "Server URL:\n"
        "    URL of the running `kimodo_server` FastAPI service.\n"
        "    Default: `http://localhost:8001`\n"
        "\n"
        f"{transport_parm}"
        "\n"
        "Prompt:\n"
        "    Natural language description of the desired motion.\n"
        '    Examples: "a person walks forward", "someone waves their hand".\n'
        "\n"
        "Duration (s):\n"
        "    Length of the generated motion in seconds. At 30 fps, 3 s = 90 frames.\n"
        "\n"
        "Model:\n"
        "    Kimodo model variant to use. Default: Kimodo-SOMA-RP-v1.1.\n"
        "\n"
        "Force Regenerate:\n"
        "    Bypass the server cache and re-run inference even if a clip with the\n"
        "    same prompt, duration, and model already exists.\n"
        "\n"
        f"{generate_note}"
        "\n"
        f"{cancel_note}"
        "\n"
        "Status:\n"
        "    Read-only. Shows the live job state: Queued, Running... (Ns) with elapsed\n"
        "    seconds, Done (Ns), Failed, or Cancelled.\n"
        "\n"
        "NPZ Path:\n"
        "    Path to the NPZ file from the last Generate call.\n"
        "    Can be set manually to load a pre-existing NPZ.\n"
        "\n"
        "== Output Geometry ==\n"
        "\n"
        "The node has two outputs, both 77-joint SOMA skeletons with polyline\n"
        "primitives connecting each parent-child pair. World rotations are stored\n"
        "in Houdini's row-vector convention (transposed from Kimodo's matrices).\n"
        "\n"
        ":output0:\n"
        "    Animated skeleton — rebuilds every frame from the NPZ file. Carries\n"
        "    `name`, `path`, `parent_id`, `transform` (float[9] world-space\n"
        "    rotation) and `localtransform` (float[16] local 4x4, row-major).\n"
        "\n"
        ":output1:\n"
        "    T-pose (rest) skeleton — static, does not depend on the NPZ. Carries\n"
        "    `name` and `transform` (float[9] world-space rotation); joint\n"
        "    positions are the SOMA77 neutral pose from Kimodo's skeleton definition.\n"
        "\n"
        "Connect output0 to a __Rig Pose SOP__ for KineFX rig binding; use output1\n"
        "as the rest skeleton for __Bone Capture__ or __Skin SOP__.\n"
        "\n"
        "== SOMA77 Skeleton Hierarchy ==\n"
        "\n"
        "{{{\n"
        "Hips (0)\n"
        "  Spine1-Spine2-Chest\n"
        "    Neck1-Neck2-Head-HeadEnd/Jaw/LeftEye/RightEye\n"
        "    LeftShoulder-LeftArm-LeftForeArm-LeftHand  [+ fingers 15-38]\n"
        "    RightShoulder-RightArm-RightForeArm-RightHand  [+ fingers 43-66]\n"
        "  LeftLeg-LeftShin-LeftFoot-LeftToeBase-LeftToeEnd  [67-71]\n"
        "  RightLeg-RightShin-RightFoot-RightToeBase-RightToeEnd  [72-76]\n"
        "}}}\n"
        "\n"
        "== Notes ==\n"
        "\n"
        "* The server runs in __mock mode__ by default (returns dev_reference.npz\n"
        "  without re-running inference). Set MOCK_MODE=0 in the Docker compose\n"
        "  environment to enable live generation.\n"
        "* Port 8000 is reserved by Docker Desktop on Windows; the API server runs\n"
        "  on port __8001__ by default.\n"
        "* Results are cached by prompt + duration + model. Re-running with identical\n"
        "  settings returns instantly (Status shows \"Done (cached)\"); enable\n"
        "  __Force Regenerate__ to bypass the cache.\n"
        "\n"
        "@related\n"
        "- [Rig Pose SOP|Node:sop/rigpose]\n"
        "- [Bone Deform SOP|Node:sop/bonedeform]\n"
    )


def install_and_help(name: str, remote: bool) -> None:
    src  = os.path.join(_HERE, "..", f"{name}.hda")
    dest = os.path.join(_HERE, "..", "hda", f"{name}.hda")
    hou.hda.installFile(src)
    hda_def = hou.hda.definitionsInFile(src)[0]
    hda_def.addSection("Help", build_help(remote))
    hda_def.save(dest)
    print(f"Saved: {dest}  (help {len(hda_def.embeddedHelp())} chars)")


install_and_help("kimodo_motion", remote=False)
install_and_help("kimodo_motion_remote", remote=True)
