# FastAPI 專案架構與執行指南

這是一個基於 FastAPI 框架開發的高效能後端應用程式。本文件旨在說明專案的目錄架構設計以及如何快速啟動開發環境。

## 1. 專案架構 (Architecture)

目前採用簡易的單一入口架構，方便快速開發：

```text
project-root/
├── index.py             # 應用程式主要邏輯與 API 定義
├── vercel.json          # Vercel 部署設定檔
├── tests/               # 單元測試與整合測試
├── service_account.json # Google Sheets 授權金鑰
├── .env                 # 環境變數設定檔 (不應上傳至 Git)
├── requirements.txt     # 專案依賴套件清單
└── readmeForfastapi     # 本說明文件
```

## 2. 執行方式 (Execution)

請依照以下步驟在本地環境設定並啟動服務：

### 步驟 A：建立並啟動虛擬環境
```bash
# 建立虛擬環境
python -m venv venv

# 啟動虛擬環境 (Windows)
venv\Scripts\activate

# 啟動虛擬環境 (Linux/macOS)
source venv/bin/activate
```

### 步驟 B：安裝依賴套件
```bash
pip install -r requirements.txt
```

### 步驟 C：啟動 Uvicorn 開發伺服器
使用 `--reload` 參數可在程式碼變動時自動重啟伺服器：
```bash
uvicorn index:app --host 0.0.0.0 --port 8000 --reload
```

## 3. API 文件
服務啟動後，您可以透過瀏覽器存取自動生成的交互式文件：
- **Swagger UI**: http://127.0.0.1:8000/docs
- **ReDoc**: http://127.0.0.1:8000/redoc