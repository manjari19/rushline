# Rushline

Flash-sale checkout engine built to survive Black Friday style rushes: zero overselling, a fair waiting room, measured performance.

> Work in progress. The full README (architecture diagram, benchmarks, screenshots) lands in Phase 3.

## Run the backend

```bash
docker compose up --build        # UI on http://localhost:8080, API docs on http://localhost:8000/docs
docker compose run --build --rm tests   # pytest, inside Python 3.12
```
