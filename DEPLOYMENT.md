# Deployment Notes

## Stack

- Frontend: Vue + Vite in `frontend/`
- Backend: FastAPI in `backend/`
- Initial data: read-only SQLite file `articles.db`
- Deployment target: Vercel through GitHub import

## Local Development

Run the backend:

```powershell
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8001
```

Run the frontend:

```powershell
cd frontend
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

## Vercel Build

Vercel reads `vercel.json`, then runs:

```powershell
python build.py
```

`build.py` installs frontend dependencies, runs the Vue production build, and copies:

```text
frontend/dist/ -> public/
```

Vercel serves files in `public/` as static assets.

The build command lives in `vercel.json` instead of `pyproject.toml` so the
deployment behavior is explicit at the project root.

## FastAPI Entry

`pyproject.toml` defines the FastAPI application entry:

```toml
[project.scripts]
app = "backend.app:app"
```

The root `app.py` also imports the FastAPI application:

```python
from backend.app import app
```

Vercel uses that `app` object as the Python backend entry.

## Initial Limitation

This first deployment reads `articles.db` only. It is suitable for a public demo, but not for daily writes on Vercel.

For daily automatic updates, replace SQLite with a cloud database or generate static JSON through a scheduled GitHub Action.
