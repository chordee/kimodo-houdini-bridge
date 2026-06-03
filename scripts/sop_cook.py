# Kimodo Python SOP cook script — paste into a Python SOP's Code tab.
# Required parameter on the SOP node: npz_path (String)
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
    -1, 0, 1, 2, 3, 4, 5, 6, 6, 6, 6,
    3, 11, 12, 13,
    14, 15, 16, 17,
    14, 19, 20, 21, 22,
    14, 24, 25, 26, 27,
    14, 29, 30, 31, 32,
    14, 34, 35, 36, 37,
    3, 39, 40, 41,
    42, 43, 44, 45,
    42, 47, 48, 49, 50,
    42, 52, 53, 54, 55,
    42, 57, 58, 59, 60,
    42, 62, 63, 64, 65,
    0, 67, 68, 69, 70,
    0, 72, 73, 74, 75,
]


def _make_mat4(rot, pos):
    return (
        float(rot[0, 0]), float(rot[0, 1]), float(rot[0, 2]), 0.0,
        float(rot[1, 0]), float(rot[1, 1]), float(rot[1, 2]), 0.0,
        float(rot[2, 0]), float(rot[2, 1]), float(rot[2, 2]), 0.0,
        float(pos[0]),    float(pos[1]),    float(pos[2]),    1.0,
    )


node = hou.pwd()
geo  = node.geometry()

npz_path = node.parm("npz_path").eval()
if not npz_path:
    raise hou.NodeError("npz_path parameter is empty")

data       = np.load(npz_path)
posed      = data["posed_joints"]    # (T, 77, 3)
local_rots = data["local_rot_mats"]  # (T, 77, 3, 3)
T          = posed.shape[0]

frame = int(hou.frame()) - 1
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
