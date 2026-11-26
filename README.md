# Examination Scheduler

Local project setup for the Python/FastAPI backend and the React/TypeScript frontend. The example page reads the shared demo case from FastAPI.

## Run with Docker Compose

Start Docker Desktop or another Docker Engine with Compose. From this directory, build and start both services:

```bash
docker compose up --build
```

Open the [web app](http://localhost:5173) and [API docs](http://localhost:8000/docs). The frontend forwards `/api` requests to the backend inside Compose. Both ports are exposed on localhost. Re-run the build command after changing the source.

Stop the services with `docker compose down`.

## Run locally

Use Python 3.12 or newer, uv, and Node.js 20.19+ or 22.12+ from a supported release line.

From this directory, start the backend:

```bash
uv sync --locked --extra test
uv run --no-sync python -m uvicorn backend.main:app --reload
```

In a second terminal, start the frontend:

```bash
cd frontend
npm ci
npm run dev
```

Open the frontend URL printed by Vite, normally [localhost:5173](http://localhost:5173). The page should list three exams, two rooms, and two slots. FastAPI's interactive documentation is available at [localhost:8000/docs](http://localhost:8000/docs).

## Verify setup

From the project directory after installing the dependencies:

```bash
uv run --no-sync python -m unittest discover -s tests
npm --prefix frontend run build
```

The setup provides `GET /api/health` and `GET /api/cases/example`. The [project documentation](docs/README.md) covers solver integration and the comparison experiments.
