"""Personal AI OS backend entrypoint."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routes import router
from database import db
from memory.semantic import semantic

logger = logging.getLogger("personal_ai")

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR.parent / ".env")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await db.init_db()
    try:
        await semantic.ensure_collection()
        await semantic.ensure_notes_collection()
    except Exception as exc:
        logger.warning("Qdrant unavailable at startup: %s", exc)
    yield


app = FastAPI(title="Personal AI OS", version="0.2.0", lifespan=lifespan)
app.include_router(router)

STATIC_DIR = BASE_DIR / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
