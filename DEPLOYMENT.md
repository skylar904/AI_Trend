# AI 趨勢追蹤部署手冊

本文件描述目前專案的正式架構與操作方式：Vercel 只部署 Vue 前端；Oracle 主機執行 FastAPI、MySQL、定時爬蟲與 AI 分析。

## 1. 正式架構

```text
使用者瀏覽器
  -> Vercel（Vue 靜態前端）
  -> /api/* rewrite
  -> Oracle 公開 HTTP 入口／Nginx
  -> FastAPI 127.0.0.1:8000
  -> MySQL、OpenAI、Gemini、外部資料來源
```

主要檔案：

- `frontend/`：Vue + Vite 前端。
- `backend/app.py`：FastAPI 入口。
- `main.py`：文章、GitHub、Hugging Face 收集流程。
- `database.py`：SQLite／MySQL 相容資料層與 schema migration。
- `summarizer.py`：OpenAI 文章分析。
- `topic_rankings.py`：本日 Top 5 與累積話題。
- `project_advisor.py`：Gemini Google Search 專案顧問。
- `retry_pending_articles.py`：重試文章分析失敗項目。
- `rebuild_daily_topics.py`：重建指定日期的本日話題。
- `cleanup_month.py`：清除前一個月文章與每日話題。
- `requirements.txt`：唯一正式 Python 相依清單。
- `.env.example`：環境變數範本，不包含真實密鑰。
- `vercel.json`：Vercel 建置與 `/api/*` rewrite。

`backend/` 不是獨立部署專案。FastAPI 會匯入根目錄的 `database.py`、`project_advisor.py` 與 `topic_rankings.py`，所以所有後端指令都必須從專案根目錄執行。

## 2. Python 相依套件

專案只維護根目錄的 `requirements.txt`。不要另外建立第二份後端 requirements。

目前必要套件：

- `fastapi`
- `uvicorn[standard]`
- `feedparser`
- `openai`
- `PyMySQL`
- `python-dotenv`
- `cryptography`（MySQL 8 的部分驗證方式需要）

建立虛擬環境與安裝：

```bash
cd /home/ubuntu/AI_Trend
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
```

正常結果：

```text
No broken requirements found.
```

更新程式後再次執行 `pip install -r requirements.txt` 是安全的；pip 只會補裝或調整需要的套件。

## 3. 環境變數

第一次部署才建立 `.env`：

```bash
cd /home/ubuntu/AI_Trend
cp .env.example .env
chmod 600 .env
nano .env
```

如果 Oracle 已經有正式 `.env`，不要用 `cp` 覆蓋它，只需依 `.env.example` 人工核對缺少的欄位。

正式環境至少需要：

```dotenv
DB_TYPE=mysql
DB_HOST=127.0.0.1
DB_PORT=3306
DB_NAME=ai_trend
DB_USER=ai_trend
DB_PASSWORD=實際密碼

OPENAI_API_KEY=實際金鑰
OPENAI_MODEL=gpt-5.4-nano
TOPIC_MODEL=gpt-5.4-nano

GEMINI_API_KEY=實際金鑰
GEMINI_TIMEOUT=45
```

選用來源憑證：

```dotenv
GITHUB_TOKEN=
HF_TOKEN=
PRODUCT_HUNT_TOKEN=
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
SEMANTIC_SCHOLAR_API_KEY=
```

沒有設定選用憑證時，對應來源會跳過或使用未登入額度，不會阻止其他來源執行。

收集與話題設定：

```dotenv
MAX_DAILY_ARTICLES=30
MAX_ENTRIES_PER_SOURCE=30
MIN_RELEVANCE_SCORE=60
TOPIC_BATCH_SIZE=120
BATCH_TOPIC_CANDIDATES=10
FINAL_TOPIC_LIMIT=5
DISPLAY_EVIDENCE_ARTICLES=10
MAX_TOPIC_SUMMARY_CHARS=520
```

重要定義：

- `MAX_ENTRIES_PER_SOURCE=30`：每個來源每次最多取得 30 個候選。
- `MAX_DAILY_ARTICLES=30`：單次執行最多成功收錄 30 篇，不是 OpenAI 呼叫上限，也不是整個自然日上限。
- 一天執行三次且每次都收滿 30 篇時，當日最多可能新增約 90 篇。
- `GEMINI_MODEL` 不需要設定；目前 `project_advisor.py` 固定使用 `gemini-3.1-flash-lite`。

只確認金鑰有載入，不要把值印出來：

```bash
cd /home/ubuntu/AI_Trend
.venv/bin/python -c "from dotenv import load_dotenv; import os; load_dotenv(); print('DB_TYPE:',os.getenv('DB_TYPE')); print('OpenAI loaded:',bool(os.getenv('OPENAI_API_KEY'))); print('Gemini loaded:',bool(os.getenv('GEMINI_API_KEY')))"
```

`.env`、私鑰、API Key 文字檔、資料庫備份不得提交到公開 repository。

## 4. 資料庫初始化與 migration

程式使用 `init_db()` 建立缺少的表、欄位與索引，不會清空既有文章。

部署新版本後執行：

```bash
cd /home/ubuntu/AI_Trend
.venv/bin/python -c "from database import init_db, connect_db; init_db(); c=connect_db(); print('processed_candidates:',c.execute('SELECT COUNT(*) AS count FROM processed_candidates').fetchone()['count']); c.close()"
```

檢查重要資料表：

```bash
.venv/bin/python - <<'PY'
from database import connect_db, table_exists

conn = connect_db()
for name in [
    "articles",
    "daily_topics",
    "topic_stats",
    "pending_articles",
    "processed_candidates",
    "platform_items",
]:
    print(name, table_exists(conn, name))
conn.close()
PY
```

所有結果都應為 `True`。

## 5. 測試後端程式

```bash
cd /home/ubuntu/AI_Trend
.venv/bin/python -m unittest -v test_pipeline_logic.py
.venv/bin/python -m pip check
```

手動啟動測試：

```bash
.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

另一個 SSH 視窗測試：

```bash
curl -sS -w "\nHTTP_STATUS=%{http_code}\n" http://127.0.0.1:8000/api/health
```

正常應為 `HTTP_STATUS=200`。手動測試完成後按 `Ctrl+C`，正式環境交給 systemd 管理。

## 6. systemd FastAPI 服務

正式 service 建議位於：

```text
/etc/systemd/system/ai-trend-api.service
```

參考內容：

```ini
[Unit]
Description=AI Trend FastAPI Service
Wants=network-online.target
After=network-online.target mysql.service

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/AI_Trend
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/ubuntu/AI_Trend/.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=5
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

套用與啟動：

```bash
sudo systemctl daemon-reload
sudo systemctl enable ai-trend-api.service
sudo systemctl restart ai-trend-api.service
sudo systemctl status ai-trend-api.service --no-pager -l
```

查看最近紀錄：

```bash
sudo journalctl -u ai-trend-api.service -n 200 --no-pager
```

即時監看 API request：

```bash
sudo journalctl -u ai-trend-api.service -f
```

## 7. Nginx 與目前的 HTTP 狀態

FastAPI 應只監聽 `127.0.0.1:8000`，不要把 Uvicorn 的 8000 port 直接開放到 Internet。Nginx 對外接收 port 80，再轉送到 Uvicorn。

沒有網域時的基本 Nginx 範例：

```nginx
server {
    listen 80 default_server;
    server_name _;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 10s;
        proxy_read_timeout 90s;
    }
}
```

檢查並重載：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

目前 `vercel.json` 使用 Oracle IP 的明文 HTTP：

```text
http://161.33.202.231/api/:path*
```

這代表瀏覽器到 Vercel 是 HTTPS，但 Vercel 到 Oracle 是 HTTP。POST 也不會取代 HTTPS。取得網域或可用的 IP TLS 憑證後，應把 Oracle 入口升級成 HTTPS，再更新 `vercel.json`。

目前 `/api/project-advisor` 是公開付費端點，尚未實作驗證與 rate limit；公開展示期間必須監控 Gemini 額度與 Oracle access log。

## 8. Vercel 前端部署

Vercel 只部署前端。`vercel.json` 執行：

```text
python build.py
```

`build.py` 會：

1. 在 `frontend/` 執行 `npm ci`。
2. 執行 `npm run build`。
3. 將 `frontend/dist/` 複製為根目錄 `public/`。

本機部署前驗證：

```powershell
cd "C:\Users\user\Desktop\推甄\AI_Trend\frontend"
npm ci
npm run build
```

也可以從專案根目錄完整模擬 Vercel build：

```powershell
cd "C:\Users\user\Desktop\推甄\AI_Trend"
python build.py
```

前端預設使用同源 `/api`。本機 Vite 會把 `/api` 轉送至 `http://127.0.0.1:8001`；Vercel 則依 `vercel.json` 轉送至 Oracle。

## 9. 每 8 小時執行爬蟲

預定時間：

```text
00:10
08:10
16:10
```

先建立 log 目錄：

```bash
mkdir -p /home/ubuntu/AI_Trend/logs
```

編輯 ubuntu 使用者的 crontab：

```bash
crontab -e
```

加入一整行：

```cron
10 0,8,16 * * * /usr/bin/flock -n /tmp/ai-trend-crawler.lock /bin/bash -lc 'cd /home/ubuntu/AI_Trend || exit 1; echo "START=$(date --iso-8601=seconds)"; .venv/bin/python main.py; code=$?; echo "END=$(date --iso-8601=seconds) EXIT=$code"; exit $code' >> /home/ubuntu/AI_Trend/logs/crawler.log 2>&1
```

作用：

- `flock` 防止上一輪未結束時又啟動下一輪。
- `START`、`END` 記錄每次執行範圍。
- `EXIT=0` 代表正常結束。
- `EXIT` 非 0、沒有 `END` 或出現 Traceback 代表需要檢查。

確認 cron：

```bash
crontab -l
sudo journalctl -u cron --since "24 hours ago" --no-pager | tail -n 200
```

查看爬蟲：

```bash
tail -n 300 /home/ubuntu/AI_Trend/logs/crawler.log
```

只找錯誤：

```bash
grep -Ei '失敗|錯誤|待補|Traceback|Exception|429|402|401|403|RESOURCE_EXHAUSTED|Invalid|timeout|timed out|denied' /home/ubuntu/AI_Trend/logs/crawler.log | tail -n 100
```

## 10. Log rotation

避免 `crawler.log` 無限增長，建立 `/etc/logrotate.d/ai-trend`，內容：

```text
/home/ubuntu/AI_Trend/logs/*.log {
    weekly
    rotate 8
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    su ubuntu ubuntu
}
```

只檢查設定、不實際輪替：

```bash
sudo logrotate --debug /etc/logrotate.d/ai-trend
```

## 11. 本日 Top 5 與近期焦點

每次爬蟲只要成功新增至少一篇文章，就會：

1. 讀取 Oracle 時間當天的全部正式文章。
2. 重新產生當天 Top 5。
3. 刪除 `daily_topics` 中當天舊版本。
4. 寫入當天最新版本。
5. 從全部保留的 `daily_topics` 重建 `topic_stats`。

因此同一天 00:10、08:10、16:10 不會累加三份排行，只保留最新版本。`topic_stats` 是由各日最後版本重新建立，不會重複計算同一天三次。

## 12. 每日資料庫健康檢查

```bash
cd /home/ubuntu/AI_Trend

.venv/bin/python - <<'PY'
from datetime import datetime
from database import connect_db, table_exists
from cleaning import normalize_topic_key

today = datetime.now().strftime("%Y-%m-%d")
conn = connect_db()

def one(sql, params=()):
    return conn.execute(sql, params).fetchone()

article = one(
    "SELECT COUNT(*) AS count, MAX(created_at) AS latest FROM articles WHERE substr(created_at,1,10)=?",
    (today,),
)
daily_today = one(
    "SELECT COUNT(*) AS count, MAX(updated_at) AS latest FROM daily_topics WHERE topic_date=?",
    (today,),
)
daily_all = one("SELECT COUNT(*) AS count, MAX(updated_at) AS latest FROM daily_topics")
stats = one("SELECT COUNT(*) AS count, MAX(updated_at) AS latest FROM topic_stats")
pending = one(
    "SELECT COUNT(*) AS count FROM pending_articles WHERE status IN ('pending','failed')"
)

processed_exists = table_exists(conn, "processed_candidates")
candidate_status = {}
if processed_exists:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS count FROM processed_candidates WHERE substr(last_processed_at,1,10)=? GROUP BY status",
        (today,),
    ).fetchall()
    candidate_status = {row["status"]: int(row["count"] or 0) for row in rows}

daily_count = int(daily_all["count"] or 0)
stats_count = int(stats["count"] or 0)
daily_latest = daily_all["latest"]
stats_latest = stats["latest"]
time_synced = (
    (daily_count == 0 and stats_count == 0)
    or (
        daily_count > 0
        and stats_count > 0
        and daily_latest
        and stats_latest
        and stats_latest >= daily_latest
    )
)

expected_scores = {}
for row in conn.execute("SELECT term, topic_score FROM daily_topics").fetchall():
    key = normalize_topic_key(row["term"])
    if key:
        expected_scores[key] = round(
            expected_scores.get(key, 0.0) + float(row["topic_score"] or 0),
            2,
        )

stored_scores = {}
for row in conn.execute("SELECT term, topic_score FROM topic_stats").fetchall():
    key = normalize_topic_key(row["term"])
    if key:
        stored_scores[key] = round(float(row["topic_score"] or 0), 2)

score_synced = (
    expected_scores.keys() == stored_scores.keys()
    and all(abs(expected_scores[key] - stored_scores[key]) < 0.01 for key in expected_scores)
)

print("Oracle日期:", today)
print("processed_candidates存在:", processed_exists)
print("今日正式文章:", int(article["count"] or 0))
print("今日最新文章時間:", article["latest"])
print("今日Top話題數:", int(daily_today["count"] or 0))
print("今日Top最後更新:", daily_today["latest"])
print("全部daily_topics數:", daily_count)
print("daily_topics最後更新:", daily_latest)
print("近期焦點數:", stats_count)
print("topic_stats最後更新:", stats_latest)
print("近期焦點時間同步:", time_synced)
print("近期焦點分數同步:", score_synced)
print("待補或失敗:", int(pending["count"] or 0))
print("今日候選狀態:", candidate_status)

conn.close()
PY
```

正常時應確認：

```text
processed_candidates存在: True
近期焦點時間同步: True
近期焦點分數同步: True
待補或失敗: 0
```

今日 Top 5 在第一次爬蟲前可能是 0；文章太少或合格話題不足時也可能少於 5，不一定代表錯誤。

## 13. 故障修復

### 13.1 查看與重試待補文章

```bash
.venv/bin/python - <<'PY'
from database import connect_db

conn = connect_db()
rows = conn.execute(
    """
    SELECT id, title, status, attempt_count, failure_reason, created_at, updated_at
    FROM pending_articles
    WHERE status IN ('pending', 'failed')
    ORDER BY updated_at DESC
    LIMIT 20
    """
).fetchall()

print("待補／失敗數量:", len(rows))
for row in rows:
    print()
    print("ID:", row["id"])
    print("標題:", row["title"])
    print("狀態:", row["status"])
    print("嘗試次數:", row["attempt_count"])
    print("第一次抓到:", row["created_at"])
    print("最後更新:", row["updated_at"])
    print("錯誤:", row["failure_reason"])
conn.close()
PY

.venv/bin/python retry_pending_articles.py
```

### 13.2 今日有文章但 Top 5 不正確

```bash
TODAY=$(date +%F)
.venv/bin/python rebuild_daily_topics.py --date "$TODAY"
```

這會重新呼叫 OpenAI 產生當日話題。

### 13.3 `daily_topics` 正常但 `topic_stats` 落後

```bash
.venv/bin/python -c "from database import init_db, rebuild_topic_stats; init_db(); count=rebuild_topic_stats(); print('topic_stats重建完成，話題數:',count)"
```

這不會呼叫 OpenAI，也不會新增文章或修改 `daily_topics`。

### 13.4 FastAPI 失敗

```bash
sudo journalctl -u ai-trend-api.service -n 200 --no-pager
sudo systemctl restart ai-trend-api.service
sudo systemctl status ai-trend-api.service --no-pager -l
```

## 14. 每月資料清理

每月 1 日先預覽前一個月份：

```bash
cd /home/ubuntu/AI_Trend
.venv/bin/python cleanup_month.py --previous-month --dry-run
```

確認後正式清理：

```bash
.venv/bin/python cleanup_month.py --previous-month
```

cron 範例（每月 1 日 04:20）：

```cron
20 4 1 * * /usr/bin/flock -n /tmp/ai-trend-cleanup.lock /bin/bash -lc 'cd /home/ubuntu/AI_Trend || exit 1; .venv/bin/python cleanup_month.py --previous-month' >> /home/ubuntu/AI_Trend/logs/cleanup.log 2>&1
```

清理會刪除該月的正式文章與 `daily_topics`，清除失效文章 ID，然後重建 `topic_stats`。去重歷史與 pending 原始紀錄會保留，避免舊文章日後重新花費 AI 分析費用。

## 15. 更新正式環境

在本機完成修改與測試後，由使用者自行將變更推送到 GitHub。Oracle 更新流程：

```bash
cd /home/ubuntu/AI_Trend
git status --short
git pull --ff-only
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -c "from database import init_db; init_db(); print('database migration complete')"
.venv/bin/python -m unittest -v test_pipeline_logic.py
sudo systemctl restart ai-trend-api.service
sudo systemctl status ai-trend-api.service --no-pager -l
curl -sS -w "\nHTTP_STATUS=%{http_code}\n" http://127.0.0.1:8000/api/health
```

確認後再等待或觸發 Vercel 部署。不要在 Oracle 上用 `git reset --hard` 覆蓋未確認的檔案。

## 16. 本機開發

後端（PowerShell）：

```powershell
cd "C:\Users\user\Desktop\推甄\AI_Trend"
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8001
```

前端（另一個 PowerShell）：

```powershell
cd "C:\Users\user\Desktop\推甄\AI_Trend\frontend"
npm ci
npm run dev
```

開啟 `http://127.0.0.1:5173`。

## 17. 部署完成檢查表

- [ ] Oracle 時區是 `Asia/Taipei`。
- [ ] `.env` 存在、權限為 600，且沒有提交到 repository。
- [ ] `DB_TYPE=mysql`，不是意外使用本機 SQLite。
- [ ] `pip check` 通過。
- [ ] `test_pipeline_logic.py` 全部通過。
- [ ] `processed_candidates` 與其他正式資料表存在。
- [ ] `ai-trend-api.service` 是 `active (running)`。
- [ ] 本機 `/api/health` 回傳 HTTP 200。
- [ ] Nginx 能從公開入口轉送 `/api/*`。
- [ ] cron 是 00:10、08:10、16:10。
- [ ] cron 使用 `flock` 防止重疊。
- [ ] `crawler.log` 有 START、END、EXIT。
- [ ] `daily_topics` 和 `topic_stats` 同步。
- [ ] `pending_articles` 沒有未處理錯誤，或已安排重試。
- [ ] Vercel 正式 build 成功。
- [ ] 公開 repository 不含 `.env`、私鑰、API Key、資料庫與 SQL 備份。
