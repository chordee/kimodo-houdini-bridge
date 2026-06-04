# HDA 函式庫（繁體中文說明）

本目錄收錄 Kimodo-Houdini 橋接專案的 Houdini Digital Assets。  
每個 HDA 以**解包（unpacked）格式**儲存——副檔名為 `.hda/` 的目錄，內容均為純文字，可在 git 中進行 diff 與 code review。

---

## kimodo_motion.hda

**節點類型：** `Sop/kimodo_motion`  
**使用環境：** SOP（幾何網路）  
**最低 Houdini 版本：** H20.5

這是一個 SOP 節點，透過本地執行的 NVIDIA Kimodo 推論伺服器，將自然語言提示（prompt）轉換為 3D 人體動作，輸出與 Houdini KineFX 相容的 77 關節 SOMA 骨架。

---

## 背景知識

### NVIDIA Kimodo 是什麼？

[Kimodo](https://github.com/nv-tlabs/kimodo) 是 NVIDIA 研究團隊開發的文字驅動 3D 動作生成模型，屬於擴散模型（diffusion model）架構。輸入一段自然語言描述，模型就會生成對應的人體骨架動畫序列。

### SOMA77 骨架

Kimodo 使用 **SOMA77** 骨架格式，共 77 個關節，以 `Hips`（索引 0）為根節點。骨架層級如下：

```
Hips (0)
├── Spine1 → Spine2 → Chest
│   ├── Neck1 → Neck2 → Head → HeadEnd
│   │                        ├── Jaw
│   │                        ├── LeftEye
│   │                        └── RightEye
│   ├── LeftShoulder → LeftArm → LeftForeArm → LeftHand
│   │                                         └── 手指 15–38（拇指、食指、中指、無名指、小指）
│   └── RightShoulder → RightArm → RightForeArm → RightHand
│                                                └── 手指 43–66
├── LeftLeg → LeftShin → LeftFoot → LeftToeBase → LeftToeEnd  (67–71)
└── RightLeg → RightShin → RightFoot → RightToeBase → RightToeEnd  (72–76)
```

### NPZ 檔案是什麼？

NPZ 是 NumPy 的壓縮封存格式（`.npz`），Kimodo 以此格式儲存推論結果。每個 NPZ 包含一段完整的動作片段，內含以下陣列：

| 鍵值 | 形狀 | 說明 |
|------|------|------|
| `posed_joints` | `(T, 77, 3)` | 各關節世界座標位置（公尺）—— **節點會讀取**(關節位置) |
| `global_rot_mats` | `(T, 77, 3, 3)` | 各關節世界空間旋轉 —— **節點會讀取**;`transform` / `localtransform` 由此推導 |
| `local_rot_mats` | `(T, 77, 3, 3)` | 各關節局部旋轉矩陣（Kimodo 輸出;節點不需要） |
| `root_positions` | `(T, 3)` | 根節點（Hips）的世界座標位置 |
| `foot_contacts` | `(T, 6)` | 足部接觸標記（布林值，SOMA 的 6 個接觸點） |

節點重建骨架只需要 **`posed_joints`** 與 **`global_rot_mats`**(且為 SOMA77 關節順序)。
任何相容的 NPZ 都能用,不管怎麼產生的(Kimodo CLI、其他腳本…):把 **NPZ Path** 指到它,
節點就會逐幀重建該片段。**Host Output Dir** / **Download Dir** 只在 **Generate** 時用來放置／抓取檔案——
手動設定 **NPZ Path** 時完全用不到它們。

---

## 輸出

節點有 **兩個輸出**，均產生帶有 polyline primitive（連接父子關節的線段）的 77 關節 SOMA 骨架。

| 輸出 | 內容 | 時間相依 |
|------|------|----------|
| **output0** | 動畫骨架——每幀從 NPZ 重建 | 是（`$F`） |
| **output1** | T-pose（rest）靜態骨架——不依賴 NPZ | 否 |

世界空間旋轉以 Houdini 的 row-vector 慣例儲存（已從 Kimodo 的 column-vector 矩陣轉置），
因此兩個輸出彼此一致，可直接用於 KineFX。

**output0（動畫）** 帶有：

| 屬性 | 型別 | 說明 |
|------|------|------|
| `name` | string | 關節名稱，例如 `Hips`、`LeftArm` |
| `path` | string | 完整階層路徑，例如 `/Hips/Spine1/Spine2` |
| `parent_id` | int | 父節點索引；根節點（Hips）為 `-1` |
| `transform` | float[9] | 世界空間旋轉，行主序 3×3 |
| `localtransform` | float[16] | 相對於父節點的局部 4×4 變換，行主序 |

**output1（T-pose）** 帶有 `name` 與 `transform`（float[9] 世界空間旋轉）；
關節位置來自 Kimodo 的 SOMA77 neutral pose 定義。

將 output0 連接至 **Rig Pose SOP** 進行 KineFX 骨架綁定；output1 可作為 **Bone Capture** 或 **Skin SOP** 的 rest skeleton 輸入。

---

## 參數說明

### API Server URL
**預設：** `http://localhost:8001`

正在執行的 `kimodo_server` FastAPI 服務網址。若伺服器部署在不同主機或埠號，請修改此欄位。若啟動伺服器時使用了自訂的 `KIMODO_PORT`，請將此欄位設為對應的埠號（例如 `http://localhost:8002`）。

### Host Output Dir

Docker 容器內 `/workspace/output` 對應的**主機端**目錄路徑。伺服器將 NPZ 寫入此路徑，並以容器內路徑回傳；節點收到後會自動替換前綴，讓 Houdini 能直接讀取。此路徑必須與 `docker-compose.hybrid.yaml` 的 volume 掛載設定一致。

### Prompt
**預設：** `a person walks forward`

描述目標動作的自然語言字串（目前僅支援英文）。描述越具體，結果越符合預期。建議包含：

- 身體部位（全身 / 上半身 / 手部）
- 方向與速度（forward、slowly、quickly）
- 動作風格（jogs、waves、crouches）

範例：`"a person jogs in a circle"`、`"someone waves with their right hand"`

### Duration (s)
**預設：** `3.0`

動作片段長度（秒）。以 30 fps 計算，3 秒 = 90 幀。片段越長，推論所需時間越多。

### Model
**預設：** `Kimodo-SOMA-RP-v1.1`

Kimodo 模型變體：

| 變體 | 說明 |
|------|------|
| `Kimodo-SOMA-RP-v1.1` | Reference Pose——以靜止姿態為條件輸入，結果較穩定 |
| `Kimodo-SOMA-SEED-v1.1` | 固定隨機種子——相同 prompt 每次輸出一致，便於重現 |
| `Kimodo-SOMA-RP-v1` | RP 的前一版本 |

### Force Regenerate
**預設：** 關閉

繞過伺服器快取，即使已存在相同 prompt、duration、model 的片段也強制重新推論。詳見 [快取](#快取)。

### Generate（按鈕）

按下後，節點會向 `<API Server URL>/generate` 提交 prompt，並立即取得一個 job ID 返回。推論在伺服器端執行，背景執行緒會持續輪詢進度，因此 **Houdini 不會凍結、可繼續操作**。任務完成後會自動更新 **NPZ Path** 並重新 cook。

**注意：** 在 mock mode（`MOCK_MODE=1`）下，伺服器不執行推論，直接回傳 `dev_reference.npz`——無論輸入什麼 prompt 結果都相同。切換至 production mode（`MOCK_MODE=0`）才會真正跑模型。

### Cancel（按鈕）

取消目前正在執行的任務（終止伺服器端的推論程序）。僅在任務進行中有作用。

### Status

唯讀欄位，顯示即時任務狀態：`Queued`、`Running... (N秒)`（含經過秒數）、`Done (N秒)`（命中快取時顯示 `Done (N秒) (cached)`）、`Failed` 或 `Cancelled`。由背景輪詢執行緒自動更新。

### NPZ Path

節點用來重建骨架的 `.npz` 檔——是個**檔案欄位**,帶瀏覽按鈕(過濾 `*.npz`)。由 **Generate** 自動填入;也可以手動指定(瀏覽或貼上)任何相容的 NPZ,載入在本節點之外產生的片段——不需 Generate、也不需 server。預設為空:剛拖出的節點在設定前會輸出空幾何(不報錯)。路徑變更時節點會自動重新 cook。

---

## 快取

伺服器以 `prompt + duration + model` 的 MD5 作為快取鍵，並用該雜湊值當輸出檔名（例如 `a872d0b….npz`），旁邊附一個 `.json` metadata 檔（prompt、duration、model、幀數、時間戳）。當 **Generate** 的參數與既有片段相同時，會即時回傳該檔——**Status** 顯示 `Done (cached)`，不會執行推論。

若要強制重新生成（例如 `SEED` 模型變體，或想換一個不同的結果），開啟 **Force Regenerate**。若要清除快取，刪除 **Host Output Dir** 中對應的 `.npz`／`.json` 檔即可。

---

## 前置條件

按下 **Generate** 前，以下 Docker 服務必須正在執行：

```bash
# 在 kimodo/ 目錄下執行
docker compose -f docker-compose.hybrid.yaml up text-encoder -d  # 等待 healthy（首次約 5-10 分鐘）
docker compose -f docker-compose.hybrid.yaml up api -d
```

---

## kimodo_motion_remote.hda

**節點類型：** `Sop/kimodo_motion_remote`

針對**常駐模型（resident）**部署的第二個節點，伺服器跑在算力強的（通常是遠端）GPU 主機上。它與 `kimodo_motion` 完全相同——一樣的 prompt、duration、model、輸出與骨架——只差一點：遠端的 Houdini 讀不到伺服器的檔案系統，所以不做掛載路徑替換，而是**透過 HTTP 下載生成好的 NPZ**。

| | `kimodo_motion` | `kimodo_motion_remote` |
|--------|-----------------|------------------------|
| 伺服器 | 每請求開子行程（`docker-compose.hybrid.yaml`） | 常駐模型、啟動預載（`docker-compose.resident.yaml`） |
| NPZ 傳輸 | volume 掛載 + 路徑替換 | HTTP 下載 |
| 傳輸參數 | **Host Output Dir** | **Download Dir** — 下載 NPZ 的本機資料夾（預設 `$HIP/kimodo_cache`） |

伺服器在啟動時預載模型（`INFERENCE_MODE=resident`），因此每次生成省去重載開銷。取捨：模型常駐佔用 VRAM，且執行中的工作無法硬性取消（Cancel 只能停掉排隊中的工作或丟棄結果）。啟動常駐伺服器：

```bash
docker compose -f docker-compose.resident.yaml up text-encoder -d  # 等待 healthy
docker compose -f docker-compose.resident.yaml up api -d
```

將節點的 **API Server URL** 設為執行常駐伺服器的主機位址。

常駐伺服器在啟動時從本機 HuggingFace 快取載入模型並略過網路（`HF_HUB_OFFLINE=1`），以免某次卡住的 HF 下載拖住啟動。權重必須先存在快取中——先用 hybrid 模式跑一次或 `huggingface-cli download` 取得，或首次以 `HF_HUB_OFFLINE=0` 啟動下載一次。

---

## 重建 HDA

若修改了 `scripts/create_hda.py` 內嵌的 cook 腳本或參數定義，需重新生成 HDA：

```bash
# 1. 在 repo 根目錄重建 packed HDA
hython scripts/create_hda.py "/path/to/kimodo/output/dev_reference.npz" "/path/to/kimodo/output"

# 2. 加入 Help Card 並將解包後的 HDA 儲存至 hda/
hython scripts/_add_help.py
```

---

## 安裝方式

### 方式 A — Houdini Package（推薦）

將專案根目錄的 `kimodo-houdini-bridge.json` 複製到 Houdini 的 packages 目錄：

```bash
# Windows
copy kimodo-houdini-bridge.json %HOUDINI_USER_PREF_DIR%\packages\

# Linux / macOS
cp kimodo-houdini-bridge.json ~/houdiniXX.Y/packages/
```

開啟 `kimodo-houdini-bridge.json`，將 `KIMODO_BRIDGE_ROOT` 改為此 repo 的實際路徑，重啟 Houdini 後即可在 Tab 選單的 **Kimodo** 分類下找到 `kimodo_motion` 節點。

### 方式 B — 手動安裝

在 Houdini：**Assets → Install Asset Library…** → 選擇 `hda/kimodo_motion.hda/` 目錄。
