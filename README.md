# Repo Analysis Tool (RAT)

Repo Analysis Tool is a FastAPI + React dashboard for analyzing Git repository evolution, volatility, and developer impact. It ingests repositories from `.zip` archives or remote Git URLs, parses non-merge history with native Git rename/binary detection, resolves `.mailmap` author identities, and exposes file, directory, commit-set, time-series, and author-impact metrics.

## Features

- Ingest repositories by uploading a `.zip` that includes a `.git` file or directory.
- Ingest repositories by cloning a remote Git URL.
- Track multiple repositories with persisted ingestion status.
- Parse non-merge commits using Git CLI output (`--no-merges -M50% --numstat`).
- Exclude binary files from line metrics while still tracking binary file touches.
- Attribute rename edits to the new path.
- Resolve author identities through `.mailmap` and persisted manual author merge rules.
- Filter by repository, author, path, time window, commit interval, or explicit commit hashes.
- View summary metrics, directory rollups, file metrics, author ownership, time series, and commits.

## Project Structure

```text
repo-analysis-tool/
├── backend/                 # FastAPI service
│   ├── app/
│   │   ├── main.py          # App entry point, CORS, routers, health check
│   │   ├── api/             # Repository and metrics REST routes
│   │   ├── git_engine/      # Git subprocess wrapper, log parser, mailmap support
│   │   ├── ingestion/       # Zip extraction and URL clone logic
│   │   └── metrics/         # Metrics aggregation engine
│   ├── requirements.txt
│   └── tests/               # Parser and metrics tests
├── frontend/                # React 18 + Vite + Tailwind dashboard
│   └── src/
│       ├── components/      # Dashboard widgets and modals
│       ├── api.js           # Frontend/backend API contract
│       ├── App.jsx
│       └── main.jsx
└── README.md
```

## Prerequisites

Install these before running the application:

- Python 3.11+ (Python 3.12 recommended)
- Node.js 18+
- npm 9+
- Git CLI available on `PATH`

The backend uses the native `git` executable; GitPython is not required.

## Running the Application

Run the backend and frontend in two separate terminals.

### 1. Backend terminal

From the repository root:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Verify the backend is running:

```bash
curl http://localhost:8000/api/health
```

Expected response:

```json
{"status":"ok"}
```

### 2. Frontend terminal

From the repository root:

```bash
cd frontend
npm install
npm run dev
```

Open the dashboard in a browser:

```text
http://localhost:5173
```

The Vite dev server proxies `/api` requests to the FastAPI backend on `http://localhost:8000`.

## Repository Workspace

Ingested repositories are stored in the first writable location from this resolution order:

1. `RAT_WORKSPACE` environment variable, if set
2. `<system temp directory>/rat_workspace`
3. `backend/data/workspace`

To force a workspace location, start the backend like this:

```bash
cd backend
RAT_WORKSPACE="$PWD/rat_workspace" uvicorn app.main:app --reload --port 8000
```

Runtime workspace directories are ignored by Git and should not be committed.

## Using the Dashboard

1. Start the backend and frontend.
2. Click **Repositories** in the top-right of the dashboard.
3. Upload a repository `.zip` file or clone a remote Git URL.
4. Wait until the repository status becomes `ready`.
5. Use the filter bar to choose:
   - all commits,
   - a time window (`since` inclusive, `until` exclusive),
   - a newest-first commit interval (`from_index` inclusive, `to_index` exclusive),
   - explicit commit hashes,
   - author substring,
   - file or directory path.
6. Review the directory tree, metrics panels, author ownership, and commit table.

## Metrics Definitions

For a selected commit set `H`:

- Added lines: `l⁺`
- Removed lines: `l⁻`
- Growth: `δ = l⁺ - l⁻`
- Churn: `λ = l⁺ + l⁻`
- Modifications: `n`, the number of commits in `H` where the selected entity has `λ > 0`
- Modification frequency: `η = n / |H|`
- Churn rate: `ρ = λ / |H|`
- Author ownership: `ω = author λ / total λ`

Binary files are excluded from line-count metrics because Git reports binary numstat entries as `-\t-`.

## API Summary

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Backend health check |
| `POST` | `/api/repo/upload` | Ingest a repository from a `.zip` archive containing a `.git` file or directory (`multipart/form-data`, field `file`) |
| `POST` | `/api/repo/clone` | Ingest a repository by cloning a remote URL (`{"url":"..."}`) |
| `GET` | `/api/repo/list` | List repositories and ingestion status |
| `GET` | `/api/repo/{repo_id}` | Repository status and metadata |
| `GET` | `/api/repo/{repo_id}/commits` | Parsed non-merge commits, paginated and filterable |
| `DELETE` | `/api/repo/{repo_id}` | Delete a repository and its workspace data |
| `GET` | `/api/metrics/{repo_id}/summary` | Commit-set totals and rates |
| `GET` | `/api/metrics/{repo_id}/authors` | Per-author churn, modifications, raw identities, and ownership |
| `GET` | `/api/metrics/{repo_id}/authors/identities` | Raw author identity list for merge tooling |
| `GET` | `/api/metrics/{repo_id}/files` | Per-file metrics, sortable and paginated |
| `GET` | `/api/metrics/{repo_id}/tree` | Directory/file rollup tree; `path` can re-root the response |
| `GET` | `/api/metrics/{repo_id}/series` | Bucketed time series (`bucket=day`, `week`, or `month`) |
| `POST` | `/api/repo/{repo_id}/authors/merge` | Manual author merge endpoint |

Metric endpoints share these filters where applicable:

- `since`: committer timestamp lower bound, inclusive
- `until`: committer timestamp upper bound, exclusive
- `author`: case-insensitive substring over canonical and raw author name/email
- `path`: exact file path or directory prefix
- `hashes`: comma-separated full or short commit hashes
- `from_index`: newest-first commit interval start, inclusive
- `to_index`: newest-first commit interval end, exclusive

Selector precedence is `hashes` > interval (`from_index`/`to_index`) > time window (`since`/`until`).

## Tests and Verification

Run backend tests:

```bash
cd backend
source .venv/bin/activate
python -m pytest
```

Run frontend lint and production build checks:

```bash
cd frontend
npm run lint
npm run build
```

A successful frontend build writes output to `frontend/dist/`.

## Troubleshooting

### Backend says the repository is not ready

Ingestion runs asynchronously. Poll the repository endpoint until `status` is `ready` or `error`:

```bash
curl http://localhost:8000/api/repo/<repo_id>
```

### Frontend cannot reach the backend

Check that the backend is running on port 8000:

```bash
curl http://localhost:8000/api/health
```

Then restart the frontend dev server:

```bash
cd frontend
npm run dev
```

### Workspace or temp-directory errors

Use an explicit workspace inside the project:

```bash
cd backend
mkdir -p rat_workspace
RAT_WORKSPACE="$PWD/rat_workspace" uvicorn app.main:app --reload --port 8000
```

## Repository Access / Privacy

The application code does not control whether this GitHub repository can be cloned anonymously. Clone access is controlled by the repository visibility setting on GitHub.

To require users to sign in before cloning this repository, make the GitHub repository private:

1. Open the repository on GitHub: `https://github.com/Kgaogelo96/Repo-analysis-tool`
2. Go to **Settings**.
3. Scroll to **Danger Zone**.
4. Choose **Change repository visibility**.
5. Select **Make private** and confirm.

After changing visibility, verify from a signed-out terminal or browser session:

```bash
git ls-remote https://github.com/Kgaogelo96/Repo-analysis-tool.git
```

Expected result for a private repository without credentials: authentication should be required, and the command should not list refs.

Do not store a Personal Access Token in the repository remote URL or commit credentials to the project.

## Current Status

The parser, ingestion pipeline, metrics endpoints, React dashboard, and manual author merge workflow are implemented. Time-window filters use committer timestamps to match the brief, and repository privacy must be managed in GitHub settings, not in application code.
