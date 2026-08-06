import os
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Import the centralized routes
from api.routes import router

app = FastAPI(title="PanelForge API", version="1.0")

# 1. CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)