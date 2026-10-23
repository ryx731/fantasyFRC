from contextlib import asynccontextmanager
from hashlib import sha256
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
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


@app.middleware('http')
async def revalidate_assets(request, call_next):
    response = await call_next(request)
    if request.url.path == '/' or request.url.path.startswith('/static/'):
        # Revalidate even when an old bookmark has an unversioned asset URL.
        response.headers['Cache-Control'] = 'no-cache'
    elif request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.get("/", include_in_schema=False)
def read_index():
    assets = ('styles.css', 'app.js', 'theme-boot.js')
    version = sha256(b''.join((STATIC_DIR / asset).read_bytes() for asset in assets)).hexdigest()[:12]
    markup = (STATIC_DIR / 'index.html').read_text(encoding='utf-8')
    return HTMLResponse(markup.replace('__ASSET_VERSION__', version))
