# Teacher Question Paper Portal

A Flask-based teacher portal with:

- teacher signup and login
- question paper generation
- subject-wise answer evaluation
- student history and analytics
- owner insights for platform totals
- PDF exports for papers and reports

## Project Structure

The project is now arranged so the UI and server code are easier to separate later:

- `frontend/templates/` contains the page templates
- `frontend/static/` contains CSS and browser JavaScript
- `backend/app.py` contains Flask routes, database logic, and generation/evaluation logic
- `api/index.py` is the Vercel entrypoint
- root `app.py` is a lightweight compatibility launcher for local development

This still runs as one Flask app today, but the folders are now split in a way that makes a future frontend/backend deployment split much easier.

## Database

The app now supports:

- local development with SQLite
- deployment with an external PostgreSQL database through `DATABASE_URL`

For Vercel, use PostgreSQL. Local SQLite is fine for development, but it is not a good production choice on Vercel because the filesystem is not persistent.

## Owner Access

Set `OWNER_EMAIL` to the email address of the account that should see the owner dashboard. That page shows:

- total accounts created
- total question papers generated
- total evaluations
- recent accounts
- teacher-wise paper generation and evaluation activity

## Required Environment Variables

```bash
SECRET_KEY=your-secure-secret
DATABASE_URL=your-postgres-connection-string
OWNER_EMAIL=owner@example.com
```

For local development, `DATABASE_URL` is optional and the app will fall back to `portal.db`.

## Run Locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`.

## Vercel Deployment Notes

- `api/index.py` is the Vercel Python entrypoint.
- `vercel.json` routes all requests to the Flask app.
- Generated question papers are stored in the database, not in local files.
- Evaluation history is stored in the database.
- Temporary files are only used during upload parsing and PDF creation.

## Recommended Vercel Setup

1. Create a PostgreSQL database from Neon, Supabase, or Vercel Postgres.
2. Add `DATABASE_URL`, `SECRET_KEY`, and `OWNER_EMAIL` in Vercel project environment variables.
3. Deploy the repo to Vercel.
