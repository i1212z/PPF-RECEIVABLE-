# PPF-RECEIVABLE-

## Deploy on Render + MongoDB

### Render service

- **Build command**: `pip install -r requirements.txt`
- **Start command**: `gunicorn -k uvicorn.workers.UvicornWorker app:app --bind 0.0.0.0:$PORT`

This repo includes a `render.yaml` blueprint you can use to create the service.

### Required env vars

- **`MONGODB_URI`**: Mongo connection string
- **`MONGODB_DB`**: optional DB name (default: `ppf_receivable`)
- **`DATA_DIR`**: optional writable path for uploads/exports (default: `/tmp`)
