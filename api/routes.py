import os
import json
import uuid
import aiofiles
import os
import json
import uuid
import aiofiles
import shutil
import glob
from datetime import datetime
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional

# Import our master Orchestrator
# Import the new function from orchestrator
from services.orchestrator import generate_full_comic, resume_comic, regenerate_thumbnail_task
from services.comfy_service import interrupt_comfy

# Create the router
router = APIRouter()


class ComicGenerationRequest(BaseModel):
    topic: str = Field(..., description="The user's prompt or story idea")
    mode: str = Field(default="topic", description="Either 'topic' or 'story'")
    num_scenes: int = Field(default=0, description="0 = Auto mode. Any positive integer forces exact scenes.")


# ==========================================
# 1. GENERATE (Background Task)
# ==========================================
@router.post("/api/generate", tags=["Generation"])
async def generate_comic_endpoint(request: ComicGenerationRequest, background_tasks: BackgroundTasks):
    try:
        comic_id = f"comic-{uuid.uuid4().hex[:8]}"
        display_mode = f"{request.mode.capitalize()} Mode"
        print(f"\n[API] Received '{request.mode}' request. Assigned ID: {comic_id}")

        # THE FIX 1: CREATE THE FILE INSTANTLY SO REACT NEVER 404s
        comic_dir = os.path.join("static", "outputs", comic_id)
        os.makedirs(comic_dir, exist_ok=True)
        story_file_path = os.path.join(comic_dir, "story.json")

        placeholder_record = {
            "id": comic_id,
            "title": "Consulting the AI Director...",
            "date": datetime.now().strftime("%B %d, %Y %I:%M %p"),
            "mode": display_mode,
            "thumbnail": "",
            "status": "generating",
            "isRead": False,
            "progress": 2,
            "synopsis": "Writing the script and planning panels...",
            "characters": [],
            "scenes": []
        }

        async with aiofiles.open(story_file_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(placeholder_record, indent=4))

        # Start the background task now that the file exists safely
        background_tasks.add_task(
            generate_full_comic,
            request.topic,
            request.mode,
            request.num_scenes,
            comic_id
        )

        return {"message": "Comic generation started", "comic_id": comic_id}

    except Exception as e:
        print(f"[API ERROR] {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# 2. GET ALL COMICS (History Library)
# ==========================================
@router.get("/api/comics", tags=["Library"])
async def get_all_comics():
    comics = []
    paths = glob.glob(os.path.join("static", "outputs", "*", "story.json"))

    for path in paths:
        try:
            async with aiofiles.open(path, "r", encoding="utf-8") as f:
                data = json.loads(await f.read())
                comics.append({
                    "id": data.get("id"),
                    "title": data.get("title", "Untitled Comic"),
                    "date": data.get("date", ""),
                    "mode": data.get("mode", "Story Mode"),
                    "isRead": data.get("isRead", False),
                    "status": data.get("status"),
                    "progress": data.get("progress"),
                    "thumbnail": data.get("thumbnail"),
                    "thumbnail_status": data.get("thumbnail_status", "idle")
                })
        except Exception:
            continue

    comics.sort(key=lambda x: x["id"], reverse=True)
    return {"comics": comics}

# ==========================================
# 3. GET SINGLE COMIC (Live Polling)
# ==========================================
@router.get("/api/comics/{comic_id}", tags=["Library"])
async def get_single_comic(comic_id: str):
    path = os.path.join("static", "outputs", comic_id, "story.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Comic not found")

    async with aiofiles.open(path, "r", encoding="utf-8") as f:
        return json.loads(await f.read())


# ==========================================
# 4. PAUSE COMIC
# ==========================================
@router.post("/api/comics/{comic_id}/pause", tags=["Controls"])
async def pause_comic(comic_id: str):
    path = os.path.join("static", "outputs", comic_id, "story.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Comic not found")

    async with aiofiles.open(path, "r", encoding="utf-8") as f:
        data = json.loads(await f.read())

    if data.get("status") == "generating":
        data["status"] = "pause_requested"
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, indent=4))
        interrupt_comfy()
        return {"message": "Pause requested. GPU will stop instantly."}

    return {"message": "Comic is not currently generating."}


# ==========================================
# 5. RESUME COMIC
# ==========================================
@router.post("/api/comics/{comic_id}/resume", tags=["Controls"])
async def resume_comic_endpoint(comic_id: str, background_tasks: BackgroundTasks):
    path = os.path.join("static", "outputs", comic_id, "story.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Comic not found")

    background_tasks.add_task(resume_comic, comic_id)
    return {"message": "Comic generation resumed"}


# ==========================================
# 6. DELETE COMIC
# ==========================================
@router.delete("/api/comics/{comic_id}", tags=["Controls"])
async def delete_comic(comic_id: str):
    """Permanently deletes the comic folder and images."""
    path = os.path.join("static", "outputs", comic_id, "story.json")
    dir_path = os.path.join("static", "outputs", comic_id)

    # if the JSON does not  exist but the folder does, just wipe it out
    if not os.path.exists(path):
        if os.path.exists(dir_path):
            shutil.rmtree(dir_path, ignore_errors=True)
            return {"message": f"Deleted {comic_id}"}
        raise HTTPException(status_code=404, detail="Comic not found")

    async with aiofiles.open(path, "r", encoding="utf-8") as f:
        data = json.loads(await f.read())

    # Cooperative Deletion: If generating, tell the loop to kill itself first
    if data.get("status") == "generating":
        data["status"] = "delete_requested"
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, indent=4))
        interrupt_comfy()
        return {"message": "Deletion requested. GPU interrupted."}

    # Safe to wipe instantly
    shutil.rmtree(dir_path, ignore_errors=True)
    return {"message": f"Deleted {comic_id}"}

# ==========================================
# 7. REGENERATE THUMBNAIL
# ==========================================
@router.post("/api/comics/{comic_id}/thumbnail", tags=["Controls"])
async def regenerate_thumbnail_endpoint(comic_id: str, background_tasks: BackgroundTasks):
    path = os.path.join("static", "outputs", comic_id, "story.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Comic not found")

    # 1. Instantly mark the thumbnail as generating in story.json
    async with aiofiles.open(path, "r", encoding="utf-8") as f:
        data = json.loads(await f.read())

    data["thumbnail_status"] = "generating"

    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(json.dumps(data, indent=4))

    # 2. Add background task
    background_tasks.add_task(regenerate_thumbnail_task, comic_id)
    return {"message": "Thumbnail regeneration started."}