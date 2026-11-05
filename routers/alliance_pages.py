"""Serve the Alliance SPA shell."""
from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()


@router.get("/")
async def home():
    return FileResponse("templates/alliance/index.html")


@router.get("/s/{section_id}")
async def section_page(section_id: str):
    return FileResponse("templates/alliance/index.html")


@router.get("/s/{section_id}/{slug}")
async def post_page(section_id: str, slug: str):
    return FileResponse("templates/alliance/index.html")


@router.get("/admin")
async def admin_page():
    return FileResponse("templates/alliance/index.html")


@router.get("/admin/panel")
async def admin_panel_page():
    return FileResponse("templates/alliance/index.html")
