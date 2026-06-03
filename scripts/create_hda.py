"""
Create kimodo_motion.hda via hython (no GUI needed).

Usage:
    hython scripts/create_hda.py [npz_default] [host_output_default]

Output: kimodo_motion.hda in the repo root.
"""
import os
import sys
import hou

_HERE     = os.path.dirname(os.path.abspath(__file__))
_REPO     = os.path.dirname(_HERE)
_HDA_PATH = os.path.join(_REPO, "kimodo_motion.hda")

_NPZ_DEFAULT        = sys.argv[1] if len(sys.argv) > 1 else ""
_HOST_OUTPUT_DEFAULT = sys.argv[2] if len(sys.argv) > 2 else ""

# Cook script runs inside the subnet's Python SOP.
# hou.pwd() = the Python SOP; .parent() = the subnet = the HDA node.
_COOK_SCRIPT = r"""
import numpy as np
import hou

SOMA77_JOINTS = [
    "Hips","Spine1","Spine2","Chest","Neck1","Neck2","Head","HeadEnd",
    "Jaw","LeftEye","RightEye",
    "LeftShoulder","LeftArm","LeftForeArm","LeftHand",
    "LeftHandThumb1","LeftHandThumb2","LeftHandThumb3","LeftHandThumbEnd",
    "LeftHandIndex1","LeftHandIndex2","LeftHandIndex3","LeftHandIndex4","LeftHandIndexEnd",
    "LeftHandMiddle1","LeftHandMiddle2","LeftHandMiddle3","LeftHandMiddle4","LeftHandMiddleEnd",
    "LeftHandRing1","LeftHandRing2","LeftHandRing3","LeftHandRing4","LeftHandRingEnd",
    "LeftHandPinky1","LeftHandPinky2","LeftHandPinky3","LeftHandPinky4","LeftHandPinkyEnd",
    "RightShoulder","RightArm","RightForeArm","RightHand",
    "RightHandThumb1","RightHandThumb2","RightHandThumb3","RightHandThumbEnd",
    "RightHandIndex1","RightHandIndex2","RightHandIndex3","RightHandIndex4","RightHandIndexEnd",
    "RightHandMiddle1","RightHandMiddle2","RightHandMiddle3","RightHandMiddle4","RightHandMiddleEnd",
    "RightHandRing1","RightHandRing2","RightHandRing3","RightHandRing4","RightHandRingEnd",
    "RightHandPinky1","RightHandPinky2","RightHandPinky3","RightHandPinky4","RightHandPinkyEnd",
    "LeftLeg","LeftShin","LeftFoot","LeftToeBase","LeftToeEnd",
    "RightLeg","RightShin","RightFoot","RightToeBase","RightToeEnd",
]
SOMA77_PARENTS = [
    -1,0,1,2,3,4,5,6,6,6,6,
    3,11,12,13,14,15,16,17,14,19,20,21,22,14,24,25,26,27,14,29,30,31,32,14,34,35,36,37,
    3,39,40,41,42,43,44,45,42,47,48,49,50,42,52,53,54,55,42,57,58,59,60,42,62,63,64,65,
    0,67,68,69,70,0,72,73,74,75,
]

def _make_mat4(rot, pos):
    # Store as tuple[16] — Houdini interprets float[16] as matrix4 for localtransform
    return (
        float(rot[0,0]),float(rot[0,1]),float(rot[0,2]),0.,
        float(rot[1,0]),float(rot[1,1]),float(rot[1,2]),0.,
        float(rot[2,0]),float(rot[2,1]),float(rot[2,2]),0.,
        float(pos[0]),  float(pos[1]),  float(pos[2]),  1.,
    )

node     = hou.pwd()
hda_node = node.parent()     # subnet SOP = the HDA wrapper

npz_path = hda_node.parm("npz_path").eval()
if not npz_path:
    raise hou.NodeError("npz_path is empty — set it or press Generate first.")

geo = node.geometry()
data       = np.load(npz_path)
posed      = data["posed_joints"]    # (T, 77, 3)
local_rots = data["local_rot_mats"]  # (T, 77, 3, 3)
T          = posed.shape[0]

frame = hda_node.parm("frame_ref").eval() - 1
frame = max(0, min(frame, T - 1))

frame_pos  = posed[frame]
frame_rots = local_rots[frame]

_ID16 = (1.,0.,0.,0., 0.,1.,0.,0., 0.,0.,1.,0., 0.,0.,0.,1.)
geo.addAttrib(hou.attribType.Point, "name",           "")
geo.addAttrib(hou.attribType.Point, "parent_id",      -1)
geo.addAttrib(hou.attribType.Point, "localtransform", _ID16)

for i, (name, parent) in enumerate(zip(SOMA77_JOINTS, SOMA77_PARENTS)):
    pt = geo.createPoint()
    pt.setPosition(hou.Vector3(frame_pos[i].tolist()))
    pt.setAttribValue("name",           name)
    pt.setAttribValue("parent_id",      parent)
    pt.setAttribValue("localtransform", _make_mat4(frame_rots[i], frame_pos[i]))
"""

_GENERATE_CB = r"""
import threading, time, requests, hou

node        = kwargs["node"]
url         = node.parm("server_url").eval().rstrip("/")
host_output = node.parm("host_output_dir").eval().rstrip("/")

try:
    resp = requests.post(
        f"{url}/generate",
        json={
            "prompt":   node.parm("prompt").eval(),
            "duration": node.parm("duration").eval(),
            "model":    node.parm("model").evalAsString(),
        },
        timeout=30,
    )
    resp.raise_for_status()
except Exception as e:
    hou.ui.displayMessage(str(e), severity=hou.severityType.Error, title="Kimodo")
    node.parm("status").set(f"Error: {e}")
else:
    job_id = resp.json()["job_id"]
    node.parm("job_id").set(job_id)
    node.parm("status").set(f"Queued ({job_id[:8]}...)")

    def _poll():
        # HOM/UI calls are not thread-safe: marshal them to the main thread.
        import hdefereval
        def _set(parm, val):
            hdefereval.executeInMainThreadWithResult(lambda: node.parm(parm).set(val))
        def _msg(text, severity=None):
            if severity is None:
                hdefereval.executeDeferred(lambda: hou.ui.displayMessage(text, title="Kimodo"))
            else:
                hdefereval.executeDeferred(lambda: hou.ui.displayMessage(text, severity=severity, title="Kimodo"))
        fails = 0
        while True:
            time.sleep(5)
            # stop if a newer Generate has replaced this job
            if hdefereval.executeInMainThreadWithResult(lambda: node.parm("job_id").eval()) != job_id:
                break
            try:
                r = requests.get(f"{url}/jobs/{job_id}", timeout=10)
                if r.status_code == 404:
                    _set("status", "Job lost (server restarted?)")
                    _set("job_id", "")
                    break
                r.raise_for_status()
                data = r.json()
                fails = 0
            except Exception as e:
                fails += 1
                _set("status", f"Poll error ({fails}/3): {e}")
                if fails >= 3:
                    break
                continue
            status  = data["status"]
            elapsed = data.get("elapsed")
            elapsed_str = f" ({int(elapsed)}s)" if elapsed else ""
            if status == "done":
                npz = data["npz_path"].replace("/workspace/output", host_output)
                frames, joints = data["frames"], data["joints"]
                def _finish():
                    node.parm("status").set(f"Done{elapsed_str}")
                    node.parm("npz_path").set(npz)
                    node.parm("job_id").set("")
                    node.cook(force=True)
                hdefereval.executeInMainThreadWithResult(_finish)
                _msg(f"Generated {frames} frames ({joints} joints){elapsed_str}.")
                break
            elif status in ("failed", "cancelled"):
                err = data.get("error")
                _set("status", f"{status.capitalize()}: {err[:60]}" if err else status.capitalize())
                if status == "failed":
                    _msg(f"Generation failed:\n{err}", severity=hou.severityType.Error)
                break
            else:
                _set("status", f"Running...{elapsed_str}")

    threading.Thread(target=_poll, daemon=True).start()
    hou.ui.displayMessage(
        "Generation started in background.\nHoudini will update automatically when done.",
        title="Kimodo",
    )
"""

# ── build Houdini scene ──────────────────────────────────────────────────────
obj = hou.node("/obj")
geo = obj.createNode("geo", "kimodo_setup")
geo.deleteItems(geo.children())

# Subnet SOP acts as the HDA container
subnet = geo.createNode("subnet", "kimodo_subnet")

# Python SOP inside the subnet
inner = subnet.createNode("python", "gen_sop")
inner.parm("python").set(_COOK_SCRIPT)

inner.setDisplayFlag(True)
inner.setRenderFlag(True)
subnet.layoutChildren()

# ── create HDA from subnet ───────────────────────────────────────────────────
hda_node = subnet.createDigitalAsset(
    name="kimodo_motion",
    hda_file_name=_HDA_PATH,
    description="Kimodo Motion Generator",
    min_num_inputs=0,
    max_num_inputs=0,
    version="1.0",
)

hda_def = hda_node.type().definition()
ptg     = hou.ParmTemplateGroup()   # start fresh — no inherited subnet parms

ptg.append(hou.SeparatorParmTemplate("sep_api"))
ptg.append(hou.StringParmTemplate(
    "server_url", "API Server URL", 1,
    default_value=("http://localhost:8001",),
))
ptg.append(hou.StringParmTemplate(
    "host_output_dir", "Host Output Dir", 1,
    default_value=(_HOST_OUTPUT_DEFAULT or "",),
    help="Host-side path mapped to /workspace/output inside Docker.",
))
ptg.append(hou.SeparatorParmTemplate("sep_gen"))
ptg.append(hou.StringParmTemplate(
    "prompt", "Prompt", 1,
    default_value=("a person walks forward",),
))
ptg.append(hou.FloatParmTemplate(
    "duration", "Duration (s)", 1,
    default_value=(3.0,), min=0.5, max=30.0,
))
ptg.append(hou.MenuParmTemplate(
    "model", "Model",
    ("Kimodo-SOMA-RP-v1.1", "Kimodo-SOMA-SEED-v1.1", "Kimodo-SOMA-RP-v1"),
    default_value=0,
))
_CANCEL_CB = r"""
import requests, hou

node   = kwargs["node"]
url    = node.parm("server_url").eval().rstrip("/")
job_id = node.parm("job_id").eval()
if not job_id:
    hou.ui.displayMessage("No active job to cancel.", title="Kimodo")
else:
    try:
        r = requests.post(f"{url}/jobs/{job_id}/cancel", timeout=10)
        r.raise_for_status()
    except Exception as e:
        hou.ui.displayMessage(str(e), severity=hou.severityType.Error, title="Kimodo")
    else:
        node.parm("status").set("Cancelled")
        node.parm("job_id").set("")
"""

ptg.append(hou.ButtonParmTemplate(
    "generate", "Generate",
    script_callback=_GENERATE_CB,
    script_callback_language=hou.scriptLanguage.Python,
    join_with_next=True,
))
ptg.append(hou.ButtonParmTemplate(
    "cancel", "Cancel",
    script_callback=_CANCEL_CB,
    script_callback_language=hou.scriptLanguage.Python,
))
ptg.append(hou.StringParmTemplate(
    "status", "Status", 1,
    default_value=("",),
    help="Current job status. Updated automatically by Generate.",
))
ptg.append(hou.StringParmTemplate(
    "job_id", "Job ID", 1,
    default_value=("",),
    is_hidden=True,
))
ptg.append(hou.SeparatorParmTemplate("sep_npz"))
ptg.append(hou.StringParmTemplate(
    "npz_path", "NPZ Path", 1,
    default_value=(_NPZ_DEFAULT or "",),
))

hda_def.setParmTemplateGroup(ptg)
hda_def.save(_HDA_PATH)

print(f"HDA saved: {_HDA_PATH}")
print(f"Parms: {[p.name() for p in hda_def.parmTemplateGroup().parmTemplates()]}")
