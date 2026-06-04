# Kimodo 骨架 - T-Pose 解析與 Houdini 格式轉換

如何把 Kimodo 的 **SOMA77 rest（T-pose）骨架**從資產檔讀出，轉成 Houdini KineFX 可用的幾何（點 + 屬性 + 骨頭線段）。

> 慣例與旋轉數學（column→row-vector 轉置、骨頭軸向）見另一篇：[Transform 慣例與骨頭軸向校正](kimodo-transform-convention.md)。本篇專注「資料在哪、怎麼讀、怎麼建幾何」。

---

## 重點前提：NPZ 沒有 T-pose

Kimodo 推論輸出的 `.npz` 只含**動畫**（`posed_joints`、`local_rot_mats`、`global_rot_mats`…），**沒有 rest pose**。T-pose 必須另外從 Kimodo 的骨架資產檔取得。

資產目錄：`kimodo/assets/skeletons/somaskel77/`

| 檔案 | 型別 / 形狀 | 內容 |
|------|------------|------|
| `joints.p` | Tensor `(77, 3)` float64 | T-pose 各關節**世界座標**（公尺，Y-up，Hips 在原點） |
| `standard_t_pose_global_offsets_rots.p` | Tensor `(77, 3, 3)` float32 | T-pose 各關節**世界空間旋轉**（骨頭對齊，column-vector） |
| （程式內建） | list[77] | 關節名稱 `SOMA77_JOINTS` 與父索引 `SOMA77_PARENTS` |

確認 `joints.p` 是 T-pose 的方法：手臂關節沿世界 **+X** 水平延伸（`LeftArm ≈ [0.165, 0.43, -0.01]`、往外到 `[0.72, …]`），頭在 +Y、腳在 −Y。手臂水平即 T 字。

---

## 載入（torch.load 的坑）

這些 `.p` 是 PyTorch 序列化的張量，**不是純 pickle**。直接 `pickle.load` 會炸：

```
_pickle.UnpicklingError: persistent IDs in protocol 0 must be ASCII strings
```

要用 `torch.load`，且新版預設 `weights_only=True` 會擋自訂類別，需顯式關掉：

```python
import torch, numpy as np

base = r"...\kimodo\assets\skeletons\somaskel77"
joints = torch.load(rf"{base}\joints.p",
                    map_location="cpu", weights_only=False).numpy()           # (77,3)
tpose  = torch.load(rf"{base}\standard_t_pose_global_offsets_rots.p",
                    map_location="cpu", weights_only=False).numpy()           # (77,3,3)
```

> Houdini 的 `hython` 通常沒有 `torch`。做法：用**外部 Python（有 torch）讀一次**，把數值**烘焙成 Python literal** 嵌進 cook script，HDA 執行期就只靠 `hou` + `numpy`，不依賴 kimodo / torch。

---

## SOMA77 階層

77 關節，`Hips`（索引 0）為根。父索引陣列 `SOMA77_PARENTS`（`-1` 為根）：

```
Hips (0)
├ Spine1-Spine2-Chest (1-3)
│  ├ Neck1-Neck2-Head-HeadEnd (4-7) + Jaw/LeftEye/RightEye (8-10)
│  ├ LeftShoulder-LeftArm-LeftForeArm-LeftHand (11-14) + 手指 15-38
│  └ RightShoulder-RightArm-RightForeArm-RightHand (39-42) + 手指 43-66
├ LeftLeg-LeftShin-LeftFoot-LeftToeBase-LeftToeEnd (67-71)
└ RightLeg-RightShin-RightFoot-RightToeBase-RightToeEnd (72-76)
```

父索引恆**小於**子索引，所以可以單次正序迴圈累積世界變換，不必遞迴。

---

## 建立 Houdini KineFX 骨架

最小 T-pose（rest skeleton，對標 `testgeometry_capybara` 的 output1）只需 `name` + `transform`：

```python
import hou
geo = hou.pwd().geometry()

def _t3(m):  # 轉置 row-major 3x3：column-vector(Kimodo) -> row-vector(Houdini)
    return (m[0],m[3],m[6], m[1],m[4],m[7], m[2],m[5],m[8])

geo.addAttrib(hou.attribType.Point, "name", "")
geo.addAttrib(hou.attribType.Point, "transform", (1.,0.,0.,0.,1.,0.,0.,0.,1.))

# 1) 建點：位置來自 joints.p，旋轉來自 tpose（轉置）
for i, name in enumerate(SOMA77_JOINTS):
    pt = geo.createPoint()
    pt.setPosition(hou.Vector3(NEUTRAL_JOINTS[i]))     # joints.p[i]
    pt.setAttribValue("name", name)
    pt.setAttribValue("transform", _t3(TPOSE_ROTS[i])) # tpose[i] 轉置

# 2) 建骨頭：每個父子配一條開放 polyline
pts = list(geo.points())
for i, parent in enumerate(SOMA77_PARENTS):
    if parent >= 0:
        prim = geo.createPolygon()
        prim.setIsClosed(False)
        prim.addVertex(pts[parent])
        prim.addVertex(pts[i])
```

要點：
- **位置**直接用 `joints.p`，不需任何轉換（座標就是世界 XYZ）。
- **`transform`** 是 float[9] 世界旋轉，Houdini 是 row-vector，所以把 Kimodo 的 column-vector 矩陣**轉置**（`_t3`）。
- **骨頭**用開放多邊形（`setIsClosed(False)`）連父→子；少了這步骨架在 viewport 只是一堆散點。
- 動畫骨架（output0）多帶 `path` / `parent_id` / `localtransform`，且世界旋轉要 `global_rot_mats @ tpose_offset` 才與這份 T-pose 軸向一致——細節見 [Transform 慣例與骨頭軸向校正](kimodo-transform-convention.md)。

---

## 驗證

- 載進 Houdini，把 output 接 **Rig Pose SOP**，能正常綁定即代表 `transform` 格式正確（缺 float[9] 會報 `Missing 'transform' attribute or it is not size 9`）。
- 軸向用「骨頭方向轉本地座標」直方圖檢查，應集中在單一軸（見另一篇）。
- 對標 `testgeometry_capybara` output1（rest skeleton）的屬性組合：`name` + `transform`。

---

## 速記

- NPZ 沒有 T-pose；rest 骨架來自 `joints.p`（位置）+ `standard_t_pose_global_offsets_rots.p`（旋轉）。
- 用 `torch.load(..., weights_only=False)` 讀，不能用 `pickle.load`。
- hython 無 torch → 外部讀一次、烘焙成 literal 嵌進 cook script。
- 位置照搬；`transform` 轉置（column→row-vector）。
- 骨頭要自己建開放 polyline 連父子。
