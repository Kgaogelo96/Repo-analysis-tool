# Repo Analysis Tool (RAT)

A high-performance web dashboard for analyzing Git repository evolution, volatility and
developer impact over time. Ingests repositories via **zip upload** or **remote URL clone**,
parses non-merge commit history, aggregates line-level metrics across directory trees and
authors, and exposes interactive filtering.

## Project Structure

```
repo-analysis-tool/
├── backend/                 # FastAPI service
│   ├── app/
│   │   ├── main.py          # Application entry point (CORS, routers, health)
│   │   ├── ingestion/       # Zip extraction, git clone manager
│   │   ├── git_engine/      # Git CLI wrappers (log parser, mailmap)
│   │   ├── metrics/         # Calculation engine (file, directory, author metrics)
│   │   └── api/             # REST controllers (repo, metrics)
│   └── requirements.txt
├── frontend/                # React (Vite) + Tailwind dashboard
│   └── src/
│       ├── components/      # IngestionModal, DirectoryTree, MetricCharts, FilterBar, AuthorMergeModal
│       ├── App.jsx
│       └── main.jsx
└── README.md
```

## Prerequisites

- Python 3.11+ (3.12 recommended)
- Node.js 18+
- Git CLI on `PATH`

## Run the Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Health check: `curl http://localhost:8000/api/health` → `{"status":"ok"}`

Repositories are ingested into a workspace directory. By default this is
`/tmp/rat_workspace`; override with the `RAT_WORKSPACE` environment variable
(the backend falls back to `./data/workspace` when `/tmp` is not writable).

## Run the Frontend

```bash
cd frontend
npm install
npm run dev
```

The dashboard is served at http://localhost:5173 (Vite dev server proxies `/api`
to the backend on port 8000).

## Status

Scaffolding stage — backend routers and metric modules are stubs; the frontend is a
Vite + Tailwind boilerplate. Features are being added incrementally.
