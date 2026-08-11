from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from src.database import engine, Base
from src.tba_client import TBAClient
from src.scoring import calculate_match_points
from src.routers import leagues, auth # Import auth here

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Fantasy FRC Engine")

app.include_router(auth.router)    # Mount Auth routes
app.include_router(leagues.router) # Mount League routes

app.mount("/static", StaticFiles(directory="static"), name="static")

# (Keep your existing TBA routes here...)
@app.get("/")
def read_index():
    return FileResponse("static/index.html")