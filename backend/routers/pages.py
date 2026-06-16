from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
templates = Jinja2Templates(directory=str(FRONTEND_DIR / "templates"))

router = APIRouter()


@router.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "pages/index.html")


@router.get("/profile")
async def profile(request: Request):
    return templates.TemplateResponse(request, "pages/profile.html")
