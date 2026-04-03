"""
web_main.py — Entry point for the ObserveAI web server.

Run:
    python web_main.py

This starts the FastAPI server on http://localhost:8000
Access the web UI at http://localhost:8000 (after building the frontend)
or during development, run the Vite dev server separately:
    cd web/frontend && npm run dev   (serves on http://localhost:5173)
"""

import os
import sys

os.environ["TF_USE_LEGACY_KERAS"] = "1"

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "web.server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
        workers=1,  # Must be 1 — we use shared global state (camera_manager)
    )
