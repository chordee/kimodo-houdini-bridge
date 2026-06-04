# Kimodo 骨架 - Transform 慣例與骨頭軸向校正

把外部動作模型（Kimodo / SMPL 系）的骨架資料匯入 Houdini KineFX 時，最容易踩兩個坑：

1. **矩陣慣例**：來源是 column-vector（列向量），Houdini 是 row-vector（行向量）。
2. **Joint frame 軸向**：來源的 joint frame 在 rest 時是「世界軸對齊」，KineFX 慣例則希望「骨頭對齊」（某個本地軸指向子節點）。

兩者都不會影響關節位置（位置由 `posed_joints` 直接決定），但會讓 `transform` / `localtransform` 數值錯誤，導致綁定（Rig Pose / Bone Capture）行為異常，或同一骨架的兩個輸出軸向對不起來。

資料來源與解析流程見另一篇：[T-Pose 解析與 Houdini 格式轉換](kimodo-tpose-parsing.md)。

---

## KineFX 點屬性

| 屬性 | 型別 | 含意 |
|------|------|------|
| `P` | vector | 關節世界座標 |
| `transform` | float[9] | 關節**世界空間旋轉** 3×3，row-major |
| `localtransform` | float[16] | 相對父節點的**局部 4×4**，row-major，平移在最後一列 |
| `name` / `parent_id` / `path` | str/int/str | 關節名、父索引、階層路徑 |

KineFX 是 **row-vector**：點以行向量右乘矩陣 `v' = v * M`，矩陣連乘 `world_i = local_i * world_parent`。平移放在 4×4 的**最後一列**（row 3），不是最後一欄。

> 驗證慣例最可靠的方法：直接讀 `testgeometry_capybara` 的 output2（rest skeleton，帶 transform + localtransform），檢查 `transform_i == localtransform_3x3_i @ transform_parent`（row-vector）誤差是否接近 0。

---

## 坑一：column-vector → row-vector（轉置）

外部模型（PyTorch / numpy）的旋轉矩陣多為 column-vector：`v' = R @ v`，世界旋轉累積為 `R_global_i = R_global_parent @ R_local_i`。

轉到 Houdini row-vector 就是**全部轉置**：

```
transform[i]        = R_global_i.T            # float[9]
localtransform[i]   = world_i @ inv(world_parent)   # float[16]，root 直接用 world_i
  其中 world_i 為 row-vector 4×4：左上 3×3 = R_global_i.T，最後一列 = 世界座標
```

要點：
- **直接用來源現成的 global rotation**，不要自己用 local 重新累積（容易把乘法順序弄反）。
- `localtransform` 的平移是**相對父節點的局部位移**，不是世界座標。用 `world_i @ inv(world_parent)` 一次算對，避免手推公式。

數學自洽：column-vector 的 `R_g_i = R_g_p @ R_l_i` 轉置後 `R_g_i.T = R_l_i.T @ R_g_p.T`，正好就是 row-vector 的 `world_i = local_i * world_parent`。

---

## 坑二：世界軸對齊 frame → 骨頭對齊 frame

SMPL / SOMA 系模型的 `global_rot_mats` 在 **rest pose 時是 identity**（local rotation 全為 0），代表 joint frame 在 rest 時**與世界軸對齊**。後果：

- 手臂沿世界 X → 該關節 frame 的「指向子節點」軸是 X
- 脊椎、腿沿世界 Y → 指向子節點的軸是 Y

也就是「哪個本地軸指向子節點」會**隨關節而異**（X / Y / Z 混在一起）。

而 rest skeleton（T-pose）若用模型附帶的 **bone-aligned 偏移旋轉**（如 Kimodo 的 `standard_t_pose_global_offsets_rots`），則每個關節都是某個固定軸（如 ±X）指向子節點。

→ 兩個輸出軸向不一致：動畫骨頭朝 ±Y，T-pose 骨頭朝 ±X。

### 校正：右乘 rest offset

設 `O_i` 為把「世界軸對齊 frame」轉成「骨頭對齊 frame」的偏移旋轉。因為 rest 時動畫 frame 為 identity，rest 的骨頭對齊 frame 就是 T-pose 旋轉 `tp_i`，故 `O_i = tp_i`。任意幀的骨頭對齊世界旋轉：

```
R_bone_i = R_global_i @ tp_i        # column-vector，右乘（在本地座標套用偏移）
transform[i] = R_bone_i.T           # 再轉置進 Houdini
```

- rest 時 `R_global = I` → `R_bone = tp_i`，與 T-pose 輸出同一份資料、同一慣例，兩輸出自然對齊。
- 順序是 `glo @ tp`（右乘）；`tp @ glo` 會得到錯誤的混亂軸向。
- `R_bone` 仍是正交、det = 1，是合法旋轉。

---

## 驗證方法（軸向直方圖）

判斷某組 `transform` 是否骨頭對齊：把世界空間骨頭方向轉進關節本地座標，統計落在哪個軸。

```python
# Houdini row-vector：local_dir = world_dir @ transform.T
def bone_axis_hist(points, parents, child):
    from collections import Counter
    AX = ["+X","+Y","+Z","-X","-Y","-Z"]
    c = Counter()
    for j, ch in child.items():            # ch = j 的某個子節點
        wd = pos[ch] - pos[j]
        wd /= np.linalg.norm(wd)
        T = transform[j].reshape(3, 3)
        ld = wd @ T.T
        a = np.argmax(np.abs(ld))
        c[AX[a + (0 if ld[a] >= 0 else 3)]] += 1
    return dict(c)
```

- **骨頭對齊**：直方圖集中在單一軸（如 `{+X:33, -X:26}`）。
- **世界軸對齊**：直方圖散開（`{+X, +Y, +Z, ...}` 混雜）。
- 修正成功的判準：**動畫輸出與 T-pose 輸出的直方圖完全相同**。

附帶檢查（都應到 machine epsilon）：
- KineFX 關係 `transform_i == localtransform_3x3_i @ transform_parent`
- 由 localtransform 重建位置：`localtransform_i[3,:3] @ transform_parent + P_parent == P_i`
- 所有 `transform` 的 `det == 1`

---

## 重點速記

- Houdini KineFX = row-vector / row-major，平移在最後一列。
- 外部 column-vector 資料 → 全部轉置；世界旋轉直接用現成的 global，別自己累積。
- `localtransform = world_i @ inv(world_parent)`，平移是局部位移。
- SMPL/SOMA 的 global frame 是世界軸對齊；要骨頭對齊得 `glo @ tp_offset`（右乘）。
- 一律用 `testgeometry_capybara` 對標、用軸向直方圖驗證，不要靠肉眼或推導。
