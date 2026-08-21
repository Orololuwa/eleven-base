# Eleven Backend

Minimal FastAPI backend with Auth0 JWT authentication.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set Postgres + Auth0 + Cloudinary values
```

## Auth0

1. Create a Native application for the mobile app.
2. Enable Google, Apple, and Passwordless Email connections.
3. Create an API (resource server) and set `AUTH0_AUDIENCE` to its identifier.
4. Set `AUTH0_DOMAIN` to your tenant domain (e.g. `eleven.eu.auth0.com`).

## Cloudinary (avatars)

Set these in `.env` (required for avatar signature / delete):

```
CLOUDINARY_CLOUD_NAME=...
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...
```

`CLOUD_NAME` and `API_KEY` are returned to the mobile client for direct upload; `API_SECRET` stays on the backend.

## Database migrations

Migrations are **manual** (not run on app startup). Postgres needs the **PostGIS** extension for profile location.

After pulling player profile models:

```bash
# Ensure PostGIS is available on the database, then:
alembic revision --autogenerate -m "add player_profiles and player_positions"
```

Review the generated revision and ensure it includes:

1. `CREATE EXTENSION IF NOT EXISTS postgis;` (if not already present)
2. `player_profiles` with `location geography(Point, 4326)`
3. `player_positions` with `UNIQUE (player_profile_id, position)`
4. Partial unique index:
   `CREATE UNIQUE INDEX one_preferred_per_player ON player_positions (player_profile_id) WHERE is_preferred = true;`

Then apply:

```bash
alembic upgrade head
```

For other model changes:

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
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
- `GET /profiles/me` — full player profile for the authenticated user
- `PATCH /profiles/me` — partial profile update
- `GET /profiles/{user_id}` — another user's profile (public fields / 404 if private)
- `PUT /profiles/me/positions` — replace position set (1–5, exactly one preferred)
- `POST /profiles/me/avatar/signature` — Cloudinary signed upload params
- `PATCH /profiles/me/avatar` — confirm upload (`public_id`, `secure_url`)
- `DELETE /profiles/me/avatar` — destroy Cloudinary asset and clear fields

## Tests

```bash
pytest
```

Schema validation tests run without DB tables. Service-level profile tests require a migrated database with PostGIS.
