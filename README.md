# PPF-RECEIVABLE-

## Deploy on Render + Postgres (recommended)

### Render service

- **Build command**: `pip install -r requirements.txt`
- **Start command**: `gunicorn -k uvicorn.workers.UvicornWorker app:app --bind 0.0.0.0:$PORT`

This repo includes a `render.yaml` blueprint you can use to create the service.

### Required env vars

- **`DATABASE_URL`**: set automatically by Render when you attach a Render Postgres database
