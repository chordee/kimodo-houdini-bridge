# HDA 函式庫（繁體中文說明）

[English](README.md)

本目錄收錄 Kimodo-Houdini 橋接專案的 Houdini Digital Asset，以**解包（unpacked）格式**
儲存——副檔名為 `.hda/` 的目錄,內容為純文字,可在 git 中 diff 與 review。

---

## kimodo_motion.hda

**節點類型：** `Sop/kimodo_motion`  
**使用環境：** SOP（幾何網路）  
**最低 Houdini 版本：** H20.5

一個 SOP 節點,透過 [NVIDIA Kimodo](https://github.com/nv-tlabs/kimodo) 模型,把自然語言
prompt 轉成 3D 人體動作。它把 prompt 送到執行中的 `kimodo_server`、透過 HTTP 下載輸出的
NPZ,並重建 77 關節 SOMA 動作為 KineFX 相容幾何——動畫骨架、rest 骨架、以及蒙皮身體 mesh。

### 輸出

四個輸出。世界空間旋轉採 Houdini 的 row-vector / row-major 慣例(已從 Kimodo 的
column-vector 轉置)。骨架以 polyline 連接父子關節。

| # | 標籤 | 內容 |
|---|------|------|
| 0 | **Animated Pose** | 逐幀動畫骨架。`name`、`path`、`parent_id`、`transform`(float[9] 世界旋轉)、`localtransform`(float[16] 局部 4×4)。 |
| 1 | **Capture Pose** | mesh 綁定的 A-pose rest 骨架(腳在地面)。`name`、`transform`。 |
| 2 | **Rest Geometry** | SOMA77 身體 mesh 的 bind 姿勢,帶 KineFX `boneCapture` 屬性(權重 + bind 來自 Kimodo 蒙皮)。 |
| 3 | **T-Pose** | T-pose 骨架(`name`、`transform`),供參考 / retarget。 |

**要變形身體**:放一個 **`kinefx::jointdeform`**(Labs/KineFX Joint Deform),接:
input 0 = **Rest Geometry**(輸出 2)、input 1 = **Capture Pose**(輸出 1)、
input 2 = **Animated Pose**(輸出 0)。mesh 會跟著動畫變形,rest 時回到 bind。
(輸出 0 也可直接接 Rig Pose / Bone Deform 流程。)

### 參數說明

| 參數 | 預設 | 說明 |
|------|------|------|
| API Server URL | `http://localhost:8001` | 執行中的 `kimodo_server` 網址。伺服器在別台就指過去。 |
| Download Dir | `$HIP/kimodo_cache` | 從伺服器透過 HTTP 下載 NPZ 的本機資料夾。 |
| Prompt | `a person walks forward` | 動作的自然語言描述。越具體(部位、方向、速度、風格)越好。 |
| Duration (s) | `3.0` | 片段長度(秒)。30 fps 下 3 秒 = 90 幀。 |
| Model | `Kimodo-SOMA-RP-v1.1` | Kimodo 模型變體。`RP` 以 rest pose 為條件;`SEED` 固定種子可重現。 |
| Force Regenerate | 關閉 | 繞過伺服器快取,即使有相同片段也強制重算。 |
| **Generate** | — | 送 prompt 到 `<API Server URL>/generate` 並立即返回 job ID。背景執行緒輪詢進度,Houdini 不凍結。完成後 NPZ 下載到 **Download Dir**、設定 **NPZ Path**、節點重新 cook。 |
| **Cancel** | — | 取消工作。常駐伺服器無法中斷執行中的生成——Cancel 只停掉排隊中的工作或丟棄結果。 |
| Status | _(唯讀)_ | 即時狀態:`Queued`、`Running... (N秒)`、`Downloading...`、`Done (N秒)`、`Failed`、`Cancelled`。 |
| NPZ Path | _(空)_ | 節點用來建骨架的 `.npz`——是**檔案欄位**(可瀏覽,`*.npz`)。由 Generate 設定;也可手動指向任何相容 NPZ(不需 Generate/伺服器)。空 = 輸出空幾何直到設定。 |

#### NPZ 檔案是什麼？

NPZ(NumPy 壓縮封存)是 Kimodo 的推論輸出。節點讀取:

| 鍵值 | 形狀 | 內容 |
|------|------|------|
| `posed_joints` | `(T, 77, 3)` | 各關節世界座標位置(公尺)—— **節點會讀取**(關節位置) |
| `global_rot_mats` | `(T, 77, 3, 3)` | 各關節世界空間旋轉 —— **節點會讀取**;`transform`/`localtransform` 由此推導 |
| `local_rot_mats` | `(T, 77, 3, 3)` | 各關節局部旋轉(Kimodo 輸出;節點不需要) |
| `root_positions` | `(T, 3)` | 根節點(Hips)世界位置 |
| `foot_contacts` | `(T, 6)` | 足部接觸標記(布林) |

節點重建骨架只需 **`posed_joints`** 與 **`global_rot_mats`**(SOMA77 關節順序)。任何相容的
NPZ 都能用,不管怎麼產生的——把 **NPZ Path** 指過去即可。**Download Dir** 只在 Generate 時用到。

### 快取

伺服器以 `prompt + duration + model` 的 SHA-256 雜湊為鍵快取。相同設定再跑會即時回傳
(Status 顯示 `Done (cached)`);開 **Force Regenerate** 可繞過。

### 前置條件

一個執行中的 `kimodo_server`。在 kimodo 目錄(見 [安裝指南](../docs/setup.zh-TW.md)):

```bash
docker compose -f docker-compose.bridge.yaml up text-encoder -d   # 等到 healthy
MOCK_MODE=0 docker compose -f docker-compose.bridge.yaml up api -d
```

模型在啟動時從本機 HuggingFace 快取離線載入,所以權重要先快取
(`huggingface-cli download nvidia/Kimodo-SOMA-RP-v1.1`)。之後模型常駐 VRAM,直到停掉 api 容器。

---

## 重建 HDA

若修改了 cook 腳本或蒙皮,重新生成 HDA:

```bash
# 1. 建置內嵌的 skin 幾何(mesh + capture、A-pose 骨架)
hython scripts/build_skin.py

# 2. 在 repo 根重建 packed HDA(嵌入 skin sections)
hython scripts/create_hda.py

# 3. 加入 help card 並存成解包格式至 hda/
hython scripts/_add_help.py
```

---

## 安裝方式

### 方式 A — Houdini Package（推薦）

把 package 檔複製到 Houdini packages 目錄,再把 `KIMODO_BRIDGE_ROOT` 改成此 repo 的絕對路徑:

```bash
# Windows
copy kimodo-houdini-bridge.json %HOUDINI_USER_PREF_DIR%\packages\
# Linux / macOS
cp kimodo-houdini-bridge.json ~/houdiniXX.Y/packages/
```

重啟 Houdini,即可在 Tab 選單的 **Kimodo** 分類下找到 `kimodo_motion` 節點。

### 方式 B — 手動安裝

Houdini:**Assets → Install Asset Library…** → 選 `hda/kimodo_motion.hda/`。
