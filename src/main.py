from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.database import Base, engine
from src.routers import auth, leagues, admin
from src.migrations import migrate

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    migrate(engine)
    yield


app = FastAPI(title="Fantasy FRC Engine", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(leagues.router)
app.include_router(admin.router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def read_index():
    return FileResponse(STATIC_DIR / "index.html")
