from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from backend.config import settings

templates = Jinja2Templates(directory=str(settings.templates_dir))

router = APIRouter()


@router.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "pages/index.html")


@router.get("/profile")
async def profile(request: Request):
    return templates.TemplateResponse(request, "pages/profile.html")


@router.get("/admin")
async def admin(request: Request):
    return templates.TemplateResponse(request, "pages/admin.html")
