# 安裝指南

[English](setup.md)

本專案支援兩種部署方式。先看 roadmap,做完**共用安裝**,再**只**照你需要的那條路走。

## 部署 roadmap

| | Path A — 本機(Hybrid) | Path B — 遠端／常駐(Resident) |
|---|---|---|
| 使用時機 | Houdini 與 GPU 在同一台 | GPU 在另一台／更強的機器 |
| Compose 檔 | `docker-compose.hybrid.yaml` | `docker-compose.resident.yaml` |
| 推論 | 每請求開一個子行程(每次重載模型) | 模型預載一次,in-process 服務 |
| Houdini 節點 | `kimodo_motion` | `kimodo_motion_remote` |
| NPZ → Houdini | 掛載 volume(路徑替換) | HTTP 下載 |
| 額外前提 | — | 模型權重需先快取(離線載入) |

兩條路共用同一個 Docker image、`kimodo_server.py`、HDA 與骨架輸出 ——
差別只在於你起哪個 compose、用哪個節點。

---

# 共用安裝(兩條路都要)

## 1. 環境檢查

clone 本 repo 並執行前置檢查:

```bash
git clone https://github.com/<your-org>/kimodo-houdini-bridge.git
cd kimodo-houdini-bridge
python scripts/check_env.py
```

腳本會檢查 Docker、GPU pass-through、系統記憶體與埠號可用性。有 `FAIL` 先修掉再繼續。

## 2. Clone Kimodo 並建置 Docker image

```bash
# Clone Kimodo（例如放在本 repo 旁邊）
git clone https://github.com/nv-tlabs/kimodo.git
cd kimodo

# Clone Kimodo 專用的 Viser fork —— 建置前必須先 clone
git clone https://github.com/nv-tlabs/kimodo-viser.git
```

**僅 Windows：** Git 可能把 shell 腳本換行轉成 CRLF,會弄壞 Docker entrypoint,建置前先修:

```bash
sed -i 's/\r//' kimodo/scripts/docker-entrypoint.sh
```

```bash
# 建置 image —— 使用 Kimodo 官方的 CUDA Dockerfile。
# 首次建置會下載 base image（約 10 GB）並安裝所有相依套件。
docker build -t kimodo:1.0 .
```

> Base image 是 `nvcr.io/nvidia/pytorch:24.10-py3`,需要快速網路或 NGC 存取權限。

## 3. HuggingFace token

匯出 token,讓容器能下載模型權重:

```bash
# 方式 A：若已執行過 `hf auth login`，直接從快取讀
export HUGGING_FACE_HUB_TOKEN=$(cat ~/.cache/huggingface/token)

# 方式 B：直接貼上 token
export HUGGING_FACE_HUB_TOKEN=hf_...
```

## 4. Houdini Python 套件

把 HDA 需要的套件裝進 Houdini 內建的 Python:

```bash
# Linux / macOS
$HFS/bin/hython -m pip install requests scipy numpy

# Windows（請依你的 Houdini 安裝路徑調整 HFS）
"C:\Program Files\Side Effects Software\Houdini 21.0.xxx\bin\hython.exe" -m pip install requests scipy numpy
```

## 5. 安裝 HDA

repo 已在 `hda/` 底下附上**兩個建好的 HDA**,直接在 Houdini 安裝即可
(**Assets → Install Asset Library…**,或用 package 檔)。完整選項見
[hda/README.md](../hda/README.md)。你只需要對應你那條路的節點:
`kimodo_motion`(Path A)或 `kimodo_motion_remote`(Path B)。

> 若你修改了 cook script,可重建兩個 HDA:
> `hython scripts/create_hda.py "<npz_default>" "<host_output_default>"` 再
> `hython scripts/_add_help.py` —— 見 [hda/README.md](../hda/README.md)。

---

# Path A — 本機(Hybrid)

Houdini 與 GPU 在同一台;節點從掛載的 volume 讀 NPZ。

## A1. 把 server 部署進 kimodo 目錄

```bash
cd /path/to/kimodo
cp /path/to/kimodo-houdini-bridge/docker-compose.hybrid.yaml .
cp /path/to/kimodo-houdini-bridge/kimodo_server.py .
mkdir -p output
```

## A2. 啟動 text-encoder(CPU,生成之間保持執行)

```bash
docker compose -f docker-compose.hybrid.yaml up text-encoder -d
# 首次啟動會下載 text encoder 並在 CPU 載入 —— 約 5-10 分鐘。
docker compose -f docker-compose.hybrid.yaml ps   # 等到 "healthy"
```

## A3. 產生一個參考片段(啟用 mock 模式 + 快取權重)

```bash
docker compose -f docker-compose.hybrid.yaml run --rm demo
cp output/test.npz output/dev_reference.npz
```

這會在 GPU 上跑一次真實生成,順便下載並快取模型權重。

## A4. 啟動 API server

```bash
# Mock 模式（回傳 dev_reference.npz、不跑推論 —— 適合開發 HDA）
docker compose -f docker-compose.hybrid.yaml up api -d
curl http://localhost:8001/health     # {"status":"ok","mock_mode":true,"inference_mode":"subprocess"}

# Live 模式（每次跑完整擴散；text-encoder 必須 healthy）
docker compose -f docker-compose.hybrid.yaml stop api
MOCK_MODE=0 docker compose -f docker-compose.hybrid.yaml up api -d
```

> **埠號注意：** Windows 上 8000 埠被 Docker Desktop 佔用,API 預設用 **8001**。
> 要換埠:`KIMODO_PORT=8002 docker compose -f docker-compose.hybrid.yaml up api -d`,
> 並把節點的 **API Server URL** 改成對應埠號。

## A5. 在 Houdini 生成

在 SOP 網路放一個 **`kimodo_motion`** 節點。把 **API Server URL** 設成
`http://localhost:8001`、**Host Output Dir** 設成你的 `kimodo/output/` 路徑,按 **Generate**。

---

# Path B — 遠端／常駐(Resident)

GPU 在另一台機器;模型預載一次,節點透過 HTTP 取回 NPZ。B1–B3 **在 GPU 機器上執行**。

## B1. 預先快取模型權重(一次性)

常駐 server 在啟動時從本機 HuggingFace 快取載入、略過網路(`HF_HUB_OFFLINE=1`),
所以權重必須先在這台快取好。兩種方式擇一:

- 你已在這台跑過生成(Path A 會把權重留在快取),或
- 直接下載:

```bash
huggingface-cli download nvidia/Kimodo-SOMA-RP-v1.1
```

(若節點會選別的模型,一併下載,例如 `nvidia/Kimodo-SOMA-SEED-v1.1`。)

## B2. 把 server 部署進 kimodo 目錄

```bash
cd /path/to/kimodo
cp /path/to/kimodo-houdini-bridge/docker-compose.resident.yaml .
cp /path/to/kimodo-houdini-bridge/kimodo_server.py .
mkdir -p output
export HUGGING_FACE_HUB_TOKEN=$(cat ~/.cache/huggingface/token)
```

## B3. 啟動 text-encoder + resident API

```bash
docker compose -f docker-compose.resident.yaml up text-encoder -d   # 等到 "healthy"
docker compose -f docker-compose.resident.yaml up api -d
```

api 會在啟動時預載模型(看 `docker logs kimodo-api`,出現
`[RESIDENT] model ready` → `Application startup complete`)。接著:

```bash
curl http://<gpu-box>:8001/health    # {"status":"ok","mock_mode":false,"inference_mode":"resident"}
```

## B4. 在 Houdini 生成

放一個 **`kimodo_motion_remote`** 節點。把 **API Server URL** 設成
`http://<gpu-box>:8001`、**Download Dir** 維持 `$HIP/kimodo_cache`(或任意本機資料夾),
按 **Generate** —— 完成的 NPZ 會自動下載到該處。
