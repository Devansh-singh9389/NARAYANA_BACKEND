import os
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Optional

# Import our master Orchestrator
from services.orchestrator import generate_full_comic

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


# ==========================================
# MASTER GENERATION ROUTE
# ==========================================

class ComicGenerationRequest(BaseModel):
    topic: str = Field(..., description="The user's prompt or story idea")
    mode: str = Field(default="topic", description="Either 'topic' or 'story'")
    num_scenes: Optional[int] = Field(default=3, description="Number of panels to generate")


@app.post("/api/generate", tags=["Generation"])
async def generate_comic_endpoint(request: ComicGenerationRequest):
    """
    Receives a topic from React, runs the full AI Story & GPU pipeline,
    and returns the completed comic JSON with local image URLs.
    """
    try:
        print(f"\n[API] Received generation request for topic: '{request.topic}'")

        # Await the orchestrator to do all the heavy lifting!
        final_comic_data = await generate_full_comic(
            prompt=request.topic,
            mode=request.mode,
            num_scenes=request.num_scenes
        )

        return final_comic_data

    except Exception as e:
        print(f"[API ERROR] {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health", tags=["System"])
def health_check():
    return {"status": "online", "message": "PanelForge Backend is ready."}


# ==========================================
# SERVER RUNNER
# ==========================================
if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)