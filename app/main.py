from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import ensure_sqlite_parent
from app.web import router

ensure_sqlite_parent(settings.database_url)

app = FastAPI(title="Keitaro wrapper")
app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
app.include_router(router)
