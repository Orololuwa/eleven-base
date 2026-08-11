# Eleven Backend

Minimal FastAPI boilerplate.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload
```

App runs at http://localhost:8000. Docs at http://localhost:8000/docs.

## Endpoints

- `GET /` — root
- `GET /health` — health check
