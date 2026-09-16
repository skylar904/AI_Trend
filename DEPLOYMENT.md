# Deployment Notes

## Target Architecture

This project is intended to run as a split frontend/backend system:

```text
User browser
  -> Vercel frontend
  -> /api/* rewrite
  -> Oracle host FastAPI backend
  -> database, OpenAI API, scheduled collectors
```

Vercel serves the Vue frontend only. The Oracle host runs the FastAPI API,
stores the production data, keeps API keys, and runs the daily collection
pipeline.

## Project Roles

- `frontend/`: Vue + Vite frontend source for Vercel.
- `backend/app.py`: FastAPI backend entry point for the Oracle host.
- `database.py`: SQLite/MySQL-compatible database layer.
- `main.py`: daily AI trend collection pipeline.
- `project_advisor.py`: user-facing Project Advisor API logic.
- `articles.db`: local demo/backup SQLite data, not the Vercel production DB.
- `vercel.json`: Vercel frontend build plus `/api/*` rewrite to Oracle.

## Local Development

Run the backend locally:

```powershell
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8001
```

Run the frontend locally:

```powershell
cd frontend
npm install
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

The Vite dev server proxies local `/api/*` requests to:

```text
http://127.0.0.1:8001
```

## Vercel Frontend Deployment

Vercel reads `vercel.json` and runs:

```powershell
python build.py
```

`build.py` installs frontend dependencies, builds Vue, and copies:

```text
frontend/dist/ -> public/
```

`vercel.json` also rewrites frontend API calls:

```text
/api/:path* -> http://161.33.202.231/api/:path*
```

So the deployed Vercel frontend does not run the Python backend itself.

## Oracle Backend Deployment

On the Oracle host, install backend dependencies:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
```

Configure environment variables in `.env` on the Oracle host. At minimum,
production should define the database mode and secrets used by the backend:

```text
DB_TYPE=mysql
DB_HOST=...
DB_PORT=3306
DB_NAME=ai_trend
DB_USER=...
DB_PASSWORD=...
OPENAI_API_KEY=...
```

Optional source tokens can be set when available:

```text
GITHUB_TOKEN=...
HF_TOKEN=...
PRODUCT_HUNT_TOKEN=...
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
SEMANTIC_SCHOLAR_API_KEY=...
```

Run the API server:

```bash
.venv/bin/python -m uvicorn backend.app:app --host 0.0.0.0 --port 8001
```

The public Oracle API must be reachable from Vercel at the host configured in
`vercel.json`.

## Daily Data Update

The daily collector is:

```bash
.venv/bin/python main.py
```

Useful modes:

```bash
.venv/bin/python main.py --dry-run
.venv/bin/python main.py --skip-platform
.venv/bin/python main.py --platform-only
.venv/bin/python retry_pending_articles.py --dry-run
.venv/bin/python rebuild_daily_topics.py --date 2026-09-16 --dry-run
```

In production, schedule `.venv/bin/python main.py` on the Oracle host with cron
or another process scheduler. Run it from the project root so the local SQLite fallback
path resolves predictably when `DB_TYPE` is not set to `mysql`.

If articles were saved but daily topic ranking failed because an API/token
problem interrupted the final AI step, rebuild that day after fixing the token:

```bash
.venv/bin/python rebuild_daily_topics.py --date YYYY-MM-DD
```

By default, daily topic ranking and `rebuild_daily_topics.py` use every saved
article for that date. The topic analyzer processes large days in batches so
the daily Top 5 is not capped to the first few hundred articles.

## Monthly Data Cleanup

Preview the previous calendar month before deleting:

```bash
.venv/bin/python cleanup_month.py --previous-month --dry-run
```

Delete the previous calendar month and rebuild recent focus stats:

```bash
.venv/bin/python cleanup_month.py --previous-month
```

To schedule cleanup on the first day of every month:

```bash
20 4 1 * * cd /home/ubuntu/AI_Trend && /home/ubuntu/AI_Trend/.venv/bin/python cleanup_month.py --previous-month >> /home/ubuntu/AI_Trend/cleanup.log 2>&1
```

## Important Notes

- Do not publish `.env` or API key text files.
- `articles.db` is a local demo/backup file. The production backend should use
  the Oracle-hosted database.
- `frontend/node_modules/`, `frontend/dist/`, `public/`, and `__pycache__/` are
  generated artifacts and can be rebuilt.
- If the Oracle backend has fewer records than local `articles.db`, check
  database migration/import and whether the scheduled collector is running.
