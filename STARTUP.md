# Eleven Backend

Minimal FastAPI backend with Auth0 JWT authentication.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set Postgres + Auth0 values
```

## Auth0

1. Create a Native application for the mobile app.
2. Enable Google, Apple, and Passwordless Email connections.
3. Create an API (resource server) and set `AUTH0_AUDIENCE` to its identifier.
4. Set `AUTH0_DOMAIN` to your tenant domain (e.g. `eleven.eu.auth0.com`).

## Database migrations

Migrations are **manual** (not run on app startup):

```bash
alembic upgrade head
# after model changes:
# alembic revision --autogenerate -m "describe change"
# alembic upgrade head
```

## Run

```bash
uvicorn app.main:app --reload
```

App runs at http://localhost:8000. Docs at http://localhost:8000/docs.

## Endpoints

- `GET /` — root
- `GET /health` — health check (public)
- `GET /me` — resolve Bearer JWT → local user (create / merge / attach)
- `POST /me/link` — attach a secondary Auth0 identity (`{"secondary_token": "..."}`)

## Tests

```bash
pytest
```
