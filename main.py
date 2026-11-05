"""◈ Alliance Site — coalition portal for allied guards."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from routers import alliance_api, alliance_pages
from services import alliance_service

ASSETS_DIR = Path("assets")
ASSETS_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("◈ Booting Alliance...")
    await alliance_service.on_startup()
    print("◈ Ready · /  /admin  /s/<id>  /data/<uuid>")
    yield


app = FastAPI(title="Alliance", lifespan=lifespan)

app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(alliance_api.router)
app.include_router(alliance_pages.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
