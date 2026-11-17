# MAXX

This scaffold provides a minimal FastAPI backend.

Quick start:

1. Create a virtual environment and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
```

2. Run the app from the `maxx/backend` folder:

```powershell
cd backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

API endpoints:
- `GET /health/` - health check
- `POST /chat/send` - send chat message
- `POST /memory/save` - save memory item
- `GET /memory/list` - list memory items
