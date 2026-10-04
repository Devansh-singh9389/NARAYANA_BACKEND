import os
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Initialize configuration and environment variables
import core.config

# Import the centralized routes
from api.routes import router

app = FastAPI(title="PanelForge API", version="1.0")

# 1. CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Mount the static directory
os.makedirs(os.path.join("static", "outputs"), exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


# 3. Include all API routes
app.include_router(router)


@app.get("/health", tags=["System"])
def health_check():
    return {"status": "online", "message": "PanelForge Backend is ready."}


# 4. Mount the built React Frontend (1-Click Single Server mode)
frontend_dist = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "NARAYANA_FRONTEND", "dist"))
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)