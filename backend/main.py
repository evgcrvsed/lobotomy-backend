from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.routers import pages

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Lobotomy")

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "static")), name="static")
app.include_router(pages.router)
