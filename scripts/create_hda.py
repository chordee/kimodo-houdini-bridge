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
_HDA_PATH        = os.path.join(_REPO, "kimodo_motion.hda")
_HDA_REMOTE_PATH = os.path.join(_REPO, "kimodo_motion_remote.hda")

# Embedded geometry built by scripts/build_skin.py (run it first). When present,
# the remote HDA gains the A-pose skeleton (output1) and skin mesh (output2).
_SKIN_BGEO  = os.path.join(_REPO, "skin.bgeo.sc")
_APOSE_BGEO = os.path.join(_REPO, "apose.bgeo.sc")


def _skin_sections():
    if os.path.exists(_SKIN_BGEO) and os.path.exists(_APOSE_BGEO):
        return {
            "skin.bgeo.sc":  open(_SKIN_BGEO, "rb").read(),
            "apose.bgeo.sc": open(_APOSE_BGEO, "rb").read(),
        }
    return None

_NPZ_DEFAULT        = sys.argv[1] if len(sys.argv) > 1 else ""
_HOST_OUTPUT_DEFAULT = sys.argv[2] if len(sys.argv) > 2 else ""

from _soma_tpose import TPOSE_ROTS
_TPOSE_SRC = "TPOSE_ROTS = %r\n" % (TPOSE_ROTS,)

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

def _cook():
    node     = hou.pwd()
    hda_node = node.parent()

    npz_path = hda_node.parm("npz_path").eval()
    if not npz_path:
        return  # no NPZ yet — output empty geometry, wait for Generate

    geo = node.geometry()
    data        = np.load(npz_path)
    posed       = data["posed_joints"]    # (T, 77, 3) world positions
    global_rots = data["global_rot_mats"] # (T, 77, 3, 3) world rotations
    T           = posed.shape[0]

    frame = hda_node.parm("frame_ref").eval() - 1
    frame = max(0, min(frame, T - 1))

    pos  = posed[frame]
    grot = global_rots[frame]

    paths = []
    def _build_path(i):
        p = SOMA77_PARENTS[i]
        return ('/' + SOMA77_JOINTS[i]) if p < 0 else (_build_path(p) + '/' + SOMA77_JOINTS[i])
    paths = [_build_path(i) for i in range(len(SOMA77_JOINTS))]

    # Kimodo global_rot_mats are column-vector and world-axis-aligned at rest;
    # the T-pose offsets re-align each joint frame to its bone, so right-multiplying
    # gives a bone-aligned world orientation matching output1. Houdini KineFX is
    # row-vector / row-major, so we transpose; translation goes in the last row.
    tp = np.asarray(TPOSE_ROTS, dtype=float).reshape(-1, 3, 3)
    world_rot = [grot[i] @ tp[i] for i in range(len(SOMA77_JOINTS))]
    world_m = []
    for i in range(len(SOMA77_JOINTS)):
        m = np.identity(4)
        m[:3, :3] = world_rot[i].T
        m[3, :3]  = pos[i]
        world_m.append(m)

    _ID9  = (1.,0.,0.,0.,1.,0.,0.,0.,1.)
    _ID16 = (1.,0.,0.,0., 0.,1.,0.,0., 0.,0.,1.,0., 0.,0.,0.,1.)
    geo.addAttrib(hou.attribType.Point, "name",           "")
    geo.addAttrib(hou.attribType.Point, "path",           "")
    geo.addAttrib(hou.attribType.Point, "parent_id",      -1)
    geo.addAttrib(hou.attribType.Point, "transform",      _ID9)
    geo.addAttrib(hou.attribType.Point, "localtransform", _ID16)

    for i, (name, parent) in enumerate(zip(SOMA77_JOINTS, SOMA77_PARENTS)):
        # local 4x4 = world_i @ inverse(world_parent); root keeps its world matrix
        local_m = world_m[i] if parent < 0 else world_m[i] @ np.linalg.inv(world_m[parent])
        pt = geo.createPoint()
        pt.setPosition(hou.Vector3(pos[i].tolist()))
        pt.setAttribValue("name",           name)
        pt.setAttribValue("path",           paths[i])
        pt.setAttribValue("parent_id",      parent)
        pt.setAttribValue("transform",      tuple(float(v) for v in world_rot[i].T.flatten()))
        pt.setAttribValue("localtransform", tuple(float(v) for v in local_m.flatten()))

    pts = list(geo.points())
    for i, parent in enumerate(SOMA77_PARENTS):
        if parent >= 0:
            prim = geo.createPolygon()
            prim.setIsClosed(False)
            prim.addVertex(pts[parent])
            prim.addVertex(pts[i])

_cook()
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
            "force":    bool(node.parm("force").eval()),
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
                done_label = f"Done{elapsed_str}" + (" (cached)" if data.get("cached") else "")
                def _finish():
                    node.parm("status").set(done_label)
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

# Remote variant: identical submit + background poll, but the server may be on
# another machine, so on completion we fetch the NPZ over HTTP into a local
# cache dir instead of rewriting a host path.
_GENERATE_CB_REMOTE = r"""
import threading, time, requests, hou

node         = kwargs["node"]
url          = node.parm("server_url").eval().rstrip("/")
download_dir = node.parm("download_dir").eval()

try:
    resp = requests.post(
        f"{url}/generate",
        json={
            "prompt":   node.parm("prompt").eval(),
            "duration": node.parm("duration").eval(),
            "model":    node.parm("model").evalAsString(),
            "force":    bool(node.parm("force").eval()),
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
        import hdefereval, os
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
                frames, joints = data["frames"], data["joints"]
                done_label = f"Done{elapsed_str}" + (" (cached)" if data.get("cached") else "")
                try:
                    _set("status", f"Downloading...{elapsed_str}")
                    os.makedirs(download_dir, exist_ok=True)
                    local_npz = os.path.join(download_dir, f"{job_id}.npz")
                    with requests.get(f"{url}/jobs/{job_id}/download", timeout=120, stream=True) as dl:
                        dl.raise_for_status()
                        with open(local_npz, "wb") as fh:
                            for chunk in dl.iter_content(chunk_size=1 << 20):
                                fh.write(chunk)
                except Exception as e:
                    _set("status", f"Download failed: {e}")
                    _msg(f"NPZ download failed:\n{e}", severity=hou.severityType.Error)
                    break
                def _finish():
                    node.parm("status").set(done_label)
                    node.parm("npz_path").set(local_npz)
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

# Cancel is identical for both HDAs (same server endpoint).
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

_REST_SCRIPT = r"""
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
# World positions (meters, Y-up) — from kimodo/assets/skeletons/somaskel77/joints.p
NEUTRAL_JOINTS = [
    [0.0,0.0,0.0],[-0.00013727,0.05003763,-0.00053727],[-0.00013727,0.12129064,-0.00083552],
    [-0.00013728,0.19679127,-0.00899523],[-0.00195404,0.45990422,-0.01452871],
    [-0.00195407,0.53699819,0.00849715],[-0.00195412,0.59828735,0.02803423],
    [-0.00191814,0.75894137,0.00968044],[-0.00192775,0.60304327,0.05898364],
    [0.03010969,0.65208940,0.10390306],[-0.03417852,0.65190604,0.10361657],
    [0.01607924,0.42916291,0.04213891],[0.16527770,0.42916293,-0.01288435],
    [0.45267077,0.42916294,-0.01291023],[0.72361059,0.42916293,-0.01288414],
    [0.74637541,0.41524248,0.01902999],[0.78650377,0.39696121,0.03544653],
    [0.81448892,0.39696121,0.03544651],[0.84629685,0.39696117,0.03544655],
    [0.75608613,0.42384295,0.01007755],[0.81973192,0.42396355,0.01186355],
    [0.85635556,0.42396355,0.01186355],[0.87964798,0.42396359,0.01186359],
    [0.90724413,0.42215821,0.01073335],[0.75524554,0.43157273,-0.00288082],
    [0.81715334,0.42897995,-0.01290630],[0.86071854,0.42897991,-0.01290631],
    [0.89068731,0.42897983,-0.01290630],[0.91373018,0.42603414,-0.01322371],
    [0.75243702,0.42862641,-0.01610957],[0.81098243,0.42376438,-0.02984798],
    [0.85448821,0.42376438,-0.02984795],[0.88100142,0.42376445,-0.02984792],
    [0.90036247,0.42454132,-0.02984863],[0.75226559,0.42606288,-0.02888792],
    [0.80314407,0.41275146,-0.04660022],[0.83385381,0.41275150,-0.04660022],
    [0.84935053,0.41275150,-0.04660021],[0.86879946,0.41117348,-0.04602802],
    [-0.01393846,0.42859436,0.04314635],[-0.16431042,0.42859447,-0.01230969],
    [-0.45167682,0.42859449,-0.01233566],[-0.72301301,0.42859449,-0.01230953],
    [-0.74575333,0.41475461,0.01932174],[-0.78586762,0.39647994,0.03573088],
    [-0.81381698,0.39647990,0.03573085],[-0.84565550,0.39647995,0.03573086],
    [-0.75554567,0.42339392,0.01051913],[-0.81896484,0.42351863,0.01230178],
    [-0.85551355,0.42351855,0.01230178],[-0.87878941,0.42351855,0.01230179],
    [-0.90640731,0.42171199,0.01117101],[-0.75469407,0.43106042,-0.00229923],
    [-0.81650235,0.42847207,-0.01230818],[-0.85999136,0.42847207,-0.01230818],
    [-0.88999376,0.42847203,-0.01230821],[-0.91301896,0.42552834,-0.01262527],
    [-0.75186991,0.42791497,-0.01539812],[-0.81041190,0.42305367,-0.02913543],
    [-0.85379999,0.42305363,-0.02913543],[-0.88034903,0.42305359,-0.02913539],
    [-0.89968471,0.42382885,-0.02913591],[-0.75167726,0.42516653,-0.02815098],
    [-0.80259097,0.41184597,-0.04587483],[-0.83321762,0.41184593,-0.04587482],
    [-0.84868291,0.41184597,-0.04587484],[-0.86813410,0.41026880,-0.04530273],
    [0.10043214,-0.08434527,0.02595655],[0.10043213,-0.51656280,0.01792742],
    [0.10043214,-0.93811376,-0.01688781],[0.10043214,-0.98870848,0.11542748],
    [0.10033607,-1.00518468,0.18055765],[-0.10047278,-0.08295260,0.02620317],
    [-0.10047277,-0.51657466,0.01814761],[-0.10047275,-0.93774860,-0.01663637],
    [-0.10047275,-0.98854469,0.11620559],[-0.10037744,-1.00488848,0.18081150],
]
_ID9 = (1.,0.,0.,0.,1.,0.,0.,0.,1.)
def _t3(m):  # transpose a flat row-major 3x3 (Kimodo column-vector -> Houdini row-vector)
    return (m[0],m[3],m[6], m[1],m[4],m[7], m[2],m[5],m[8])
geo = hou.pwd().geometry()
geo.addAttrib(hou.attribType.Point, "name",      "")
geo.addAttrib(hou.attribType.Point, "transform", _ID9)
for i, name in enumerate(SOMA77_JOINTS):
    pt = geo.createPoint()
    pt.setPosition(hou.Vector3(NEUTRAL_JOINTS[i]))
    pt.setAttribValue("name",      name)
    pt.setAttribValue("transform", _t3(TPOSE_ROTS[i]))
pts = list(geo.points())
for i, parent in enumerate(SOMA77_PARENTS):
    if parent >= 0:
        prim = geo.createPolygon()
        prim.setIsClosed(False)
        prim.addVertex(pts[parent])
        prim.addVertex(pts[i])
"""

# Cook script for an output that loads geometry embedded in the HDA as a section
# (used for the A-pose skeleton and the skin mesh). Reads the section bytes from
# the HDA definition, writes them to a temp file, and loads them — avoids opdef:
# path resolution and keeps the HDA self-contained.
_SECTION_LOADER = '''import os, base64, tempfile, hou
node = hou.pwd()
name = "%s"
raw = node.parent().type().definition().sections()[name].contents()
data = base64.b64decode(raw)
path = os.path.join(tempfile.gettempdir(), "kimodo_" + name)
with open(path, "wb") as fh:
    fh.write(data)
node.geometry().loadFromFile(path)
'''


def build_hda(node_name, description, hda_path, generate_cb, fetch_mode, skin_sections=None):
    """Build one kimodo HDA. The two flavours share everything except the
    Generate callback and one transport parameter:
      fetch_mode="local"  -> host_output_dir (volume path rewrite)
      fetch_mode="remote" -> download_dir   (HTTP download to a local cache)

    skin_sections: optional {section_name: bytes}. When given, the HDA gets four
      outputs (0 animated, 1 A-pose rest skeleton, 2 skin mesh, 3 T-pose) with the
      skeleton/mesh geometry embedded as sections. When None, two outputs
      (0 animated, 1 T-pose).
    """
    obj = hou.node("/obj")
    geo = obj.createNode("geo", node_name + "_setup")
    geo.deleteItems(geo.children())

    subnet = geo.createNode("subnet", node_name + "_subnet")

    # Python SOPs share the TPOSE_ROTS table, injected as a literal prelude so
    # each embedded cook script stays self-contained.
    inner = subnet.createNode("python", "gen_sop")
    inner.parm("python").set(_TPOSE_SRC + _COOK_SCRIPT)
    rest_sop = subnet.createNode("python", "rest_sop")
    rest_sop.parm("python").set(_TPOSE_SRC + _REST_SCRIPT)

    out0 = subnet.createNode("output", "output0")
    out0.setInput(0, inner)
    out0.parm("outputidx").set(0)

    if skin_sections:
        apose_sop = subnet.createNode("python", "apose_sop")
        apose_sop.parm("python").set(_SECTION_LOADER % "apose.bgeo.sc")
        skin_sop = subnet.createNode("python", "skin_sop")
        skin_sop.parm("python").set(_SECTION_LOADER % "skin.bgeo.sc")
        out1 = subnet.createNode("output", "output1")
        out1.setInput(0, apose_sop)
        out1.parm("outputidx").set(1)
        out2 = subnet.createNode("output", "output2")
        out2.setInput(0, skin_sop)
        out2.parm("outputidx").set(2)
        out3 = subnet.createNode("output", "output3")
        out3.setInput(0, rest_sop)
        out3.parm("outputidx").set(3)
        n_outputs = 4
    else:
        out1 = subnet.createNode("output", "output1")
        out1.setInput(0, rest_sop)
        out1.parm("outputidx").set(1)
        n_outputs = 2

    out0.setDisplayFlag(True)
    out0.setRenderFlag(True)
    subnet.layoutChildren()

    hda_node = subnet.createDigitalAsset(
        name=node_name,
        hda_file_name=hda_path,
        description=description,
        min_num_inputs=0,
        max_num_inputs=0,
        version="1.0",
    )
    hda_def = hda_node.type().definition()
    hda_def.setMaxNumOutputs(n_outputs)
    if skin_sections:
        # Store the binary bgeo as base64 text so the section round-trips cleanly
        # (HDASection.contents() returns str; raw bytes don't survive that).
        import base64
        for sname, data in skin_sections.items():
            hda_def.addSection(sname, base64.b64encode(data).decode("ascii"))
    ptg = hou.ParmTemplateGroup()   # start fresh — no inherited subnet parms

    ptg.append(hou.SeparatorParmTemplate("sep_api"))
    ptg.append(hou.StringParmTemplate(
        "server_url", "API Server URL", 1,
        default_value=("http://localhost:8001",),
    ))
    if fetch_mode == "local":
        ptg.append(hou.StringParmTemplate(
            "host_output_dir", "Host Output Dir", 1,
            default_value=(_HOST_OUTPUT_DEFAULT or "",),
            help="Host-side path mapped to /workspace/output inside Docker.",
        ))
    else:
        ptg.append(hou.StringParmTemplate(
            "download_dir", "Download Dir", 1,
            default_value=("$HIP/kimodo_cache",),
            help="Local folder where generated NPZ files are downloaded from the server.",
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
    ptg.append(hou.ToggleParmTemplate(
        "force", "Force Regenerate",
        default_value=False,
        help="Bypass the server cache and re-run inference even if a matching clip exists.",
    ))
    ptg.append(hou.ButtonParmTemplate(
        "generate", "Generate",
        script_callback=generate_cb,
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
    ptg.append(hou.IntParmTemplate(
        "frame_ref", "Frame", 1,
        default_expression=("$F",),
        default_expression_language=(hou.scriptLanguage.Hscript,),
        is_hidden=True,
    ))
    ptg.append(hou.SeparatorParmTemplate("sep_npz"))
    ptg.append(hou.StringParmTemplate(
        "npz_path", "NPZ Path", 1,
        default_value=(_NPZ_DEFAULT or "",),
        string_type=hou.stringParmType.FileReference,
        file_type=hou.fileType.Any,
        tags={"filechooser_pattern": "*.npz"},
    ))

    hda_def.setParmTemplateGroup(ptg)
    hda_def.save(hda_path)
    print(f"HDA saved: {hda_path}")
    print(f"  parms: {[p.name() for p in hda_def.parmTemplateGroup().parmTemplates()]}")


# ── build both HDAs ──────────────────────────────────────────────────────────
build_hda("kimodo_motion", "Kimodo Motion Generator",
          _HDA_PATH, _GENERATE_CB, "local")
build_hda("kimodo_motion_remote", "Kimodo Motion Generator (Remote)",
          _HDA_REMOTE_PATH, _GENERATE_CB_REMOTE, "remote", skin_sections=_skin_sections())
