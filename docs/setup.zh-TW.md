# 安裝指南

[English](setup.md)

本指南涵蓋完整的環境設定流程，從 Docker 部署到 Houdini HDA。

## Step 0：環境驗證

複製此 repo 並執行前置檢查：

```bash
git clone https://github.com/<your-org>/kimodo-houdini-bridge.git
cd kimodo-houdini-bridge
python scripts/check_env.py
```

此腳本會檢查 Docker 是否可用、GPU pass-through、系統 RAM 以及埠號是否空閒。繼續之前請先修正所有 `FAIL` 項目。

一切就緒時的預期輸出：

```
[PASS] Docker CLI found
[PASS] Docker daemon running
[PASS] Docker GPU pass-through (nvidia-smi visible in container)
[PASS] System RAM >= 16 GB — XX.X GB detected
[PASS] Port 8000 available
[PASS] Port 9550 available

Result: 6/6 checks passed. Ready for Phase 1.
```

---

## Step 1：複製 Kimodo 並建置 Docker 映像

```bash
# 複製 Kimodo（例如放在此 repo 旁邊）
git clone https://github.com/nv-tlabs/kimodo.git
cd kimodo

# 複製 Kimodo 專用的 Viser fork —— 建置前必須先完成
git clone https://github.com/nv-tlabs/kimodo-viser.git
```

**僅限 Windows：** Git 可能會將 shell 腳本的換行符號轉成 CRLF，導致 Docker entrypoint 無法執行。建置前請先修正：

```bash
sed -i 's/\r//' kimodo/scripts/docker-entrypoint.sh
```

```bash
# 建置映像 —— 使用 Kimodo 官方的 CUDA Dockerfile
# 首次建置會下載 base image（約 10 GB）並安裝所有相依套件
docker build -t kimodo:1.0 .
```

> Base image 為 `nvcr.io/nvidia/pytorch:24.10-py3`，需要快速的網路連線或 NGC 存取權限。

---

## Step 2：啟動服務並生成一段動作片段

將此 repo 的 `docker-compose.hybrid.yaml` 複製到 `kimodo/` 目錄，並建立輸出資料夾：

```bash
cp ../kimodo-houdini-bridge/docker-compose.hybrid.yaml .
mkdir -p output
```

匯出 HuggingFace token，讓容器能下載模型權重：

```bash
# 選項 A：若已執行過 `hf auth login`，從快取讀取
export HUGGING_FACE_HUB_TOKEN=$(cat ~/.cache/huggingface/token)

# 選項 B：直接貼上你的 token
export HUGGING_FACE_HUB_TOKEN=hf_...
```

啟動 text-encoder 服務（在 CPU 上執行，多次生成之間維持運作）：

```bash
docker compose -f docker-compose.hybrid.yaml up text-encoder -d

# 等待狀態顯示 "healthy"
# 首次啟動會下載 LLM2Vec text encoder 模型並載入 CPU —— 約需 5-10 分鐘
docker compose -f docker-compose.hybrid.yaml ps
```

執行一次生成（擴散在 GPU 上執行）：

```bash
docker compose -f docker-compose.hybrid.yaml run --rm demo
```

驗證輸出：

```bash
ls -lh output/test.npz
```

```python
# 在 Houdini Python Shell 或任何 Python 環境中
import numpy as np
data = np.load("output/test.npz")
print(list(data.keys()))
# ['local_rot_mats', 'global_rot_mats', 'posed_joints', 'root_positions',
#  'smooth_root_pos', 'foot_contacts', 'global_root_heading']

joints = data["posed_joints"]
print(joints.shape)       # (T, 77, 3)  — T = 幀數, 77 = SOMA 關節
print(data["local_rot_mats"].shape)   # (T, 77, 3, 3)
print(data["foot_contacts"].shape)    # (T, 6) bool — SOMA 骨架的 6 個接觸點
```

另存一份作為開發用的參考檔：

```bash
cp output/test.npz output/dev_reference.npz
```

---

## Step 3：Houdini Python 環境設定

將所需套件安裝到 Houdini 內建的 Python：

```bash
# Linux / macOS
$HFS/bin/hython -m pip install requests scipy numpy

# Windows（請依你的 Houdini 安裝路徑調整 HFS）
"C:\Program Files\Side Effects Software\Houdini 21.0.xxx\bin\hython.exe" -m pip install requests scipy numpy
```

在 Houdini Python Shell 中驗證：

```python
import numpy as np
import requests
import scipy
print(np.__version__, requests.__version__, scipy.__version__)
```

三者都應印出版本字串且無 import 錯誤。

---

## Step 4：啟動 API 伺服器

將此 repo 的 `kimodo_server.py` 複製到 `kimodo/` 目錄：

```bash
cp ../kimodo-houdini-bridge/kimodo_server.py .
```

以 **mock mode** 啟動 API 服務（不執行推論，直接回傳 `dev_reference.npz` —— 適合 HDA 開發階段）：

```bash
docker compose -f docker-compose.hybrid.yaml up api -d
```

驗證：

```bash
curl http://localhost:8001/health
# {"status":"ok","mock_mode":true}

curl -X POST http://localhost:8001/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "a person walks forward", "duration": 3.0}'
# {"npz_path":"/workspace/output/dev_reference.npz","prompt":"...","frames":90,"joints":77}
```

> **埠號說明：** 在 Windows 上，埠號 8000 由 Docker Desktop 佔用，因此 API 預設使用 **8001**。
> 若要使用其他埠號：`KIMODO_PORT=8002 docker compose -f docker-compose.hybrid.yaml up api -d`
> 若更改了埠號，記得同步修改 HDA 的 **API Server URL** 參數（例如 `http://localhost:8002`）。

要啟用**即時推論（live inference）**，請先確認 `text-encoder` 已 healthy，再以 `MOCK_MODE=0` 重啟 api 服務：

```bash
docker compose -f docker-compose.hybrid.yaml stop api
MOCK_MODE=0 docker compose -f docker-compose.hybrid.yaml up api -d
```

在 live mode 下，每次 `/generate` 呼叫都會在 GPU 上執行完整的 Kimodo 擴散運算（依長度約 30 秒至 3 分鐘）。首次呼叫還會從 HuggingFace 下載模型權重（首次約 10 分鐘）。

---

## Step 5：從 Houdini 連線（Python Shell）

```python
import requests

resp = requests.post(
    "http://localhost:8001/generate",
    json={"prompt": "a person walks forward", "duration": 3.0},
    timeout=30,
)
resp.raise_for_status()
data = resp.json()
print(data["npz_path"])  # /workspace/output/dev_reference.npz
print(data["frames"])    # 90
print(data["joints"])    # 77
```

載入 NPZ（Docker 的 `/workspace/output/` 對應主機端的 `./output/`）：

```python
import numpy as np

host_path = data["npz_path"].replace("/workspace/output", "/path/to/kimodo/output")
motion = np.load(host_path)
print(motion["posed_joints"].shape)  # (90, 77, 3)
```

---

## Step 6：建置並安裝 Houdini HDA

使用 hython 生成 HDA 檔案（不需開啟 Houdini GUI）：

```bash
# 在 kimodo-houdini-bridge repo 根目錄下執行
hython scripts/create_hda.py "/path/to/kimodo/output/dev_reference.npz" "/path/to/kimodo/output"
# 輸出：kimodo_motion.hda
```

在 Houdini 中安裝 —— 完整的 HDA 文件與安裝選項請見 [hda/README.zh-TW.md](../hda/README.zh-TW.md)。

在任一 SOP 網路中放置 **kimodo_motion** 節點，將 **Host Output Dir** 設為你的 `kimodo/output/` 目錄路徑，再按下 **Generate**。
