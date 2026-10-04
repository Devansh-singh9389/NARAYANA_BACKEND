import os
import json
import uuid
import re
import shutil
import glob
from datetime import datetime
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional

# Import our master Orchestrator
from services.orchestrator import generate_full_comic, resume_comic, regenerate_thumbnail_task
from services.comfy_service import interrupt_comfy
from utils.file_manager import save_json_atomic, load_json_resilient

# Create the router
router = APIRouter()

_COMIC_ID_RE = re.compile(r'^comic-[a-f0-9]{8}$')

def _validate_comic_id(comic_id: str) -> str:
    """Reject path-traversal attempts by enforcing strict comic ID format."""
    if not _COMIC_ID_RE.match(comic_id):
        raise HTTPException(status_code=400, detail="Invalid comic ID format.")
    return comic_id


class ComicGenerationRequest(BaseModel):
    topic: str = Field(..., description="The user's prompt or story idea")
    mode: str = Field(default="topic", description="Either 'topic' or 'story'")
    num_scenes: int = Field(default=0, description="0 = Auto mode. Any positive integer forces exact scenes.")
    render_model: str = Field(default="sdxl", description="Either 'sdxl', 'flux', or 'imagen'")


class RegenerateRequest(BaseModel):
    render_model: str = Field(..., description="Either 'sdxl', 'flux', or 'imagen'")


# ==========================================
# 1. GENERATE (Background Task)
# ==========================================
@router.post("/api/generate", tags=["Generation"])
async def generate_comic_endpoint(request: ComicGenerationRequest, background_tasks: BackgroundTasks):
    try:
        comic_id = f"comic-{uuid.uuid4().hex[:8]}"
        display_mode = f"{request.mode.capitalize()} Mode"
        print(f"\n[API] Received '{request.mode}' request. Assigned ID: {comic_id}")

        comic_dir = os.path.join("static", "outputs", comic_id)
        os.makedirs(comic_dir, exist_ok=True)
        story_file_path = os.path.join(comic_dir, "story.json")

        placeholder_record = {
            "id": comic_id,
            "title": "Consulting the AI Director...",
            "date": datetime.now().strftime("%B %d, %Y %I:%M %p"),
            "mode": display_mode,
            "raw_mode": request.mode,
            "prompt": request.topic,
            "num_scenes": request.num_scenes,
            "render_model": request.render_model,
            "thumbnail": "",
            "status": "generating",
            "isRead": False,
            "progress": 2,
            "synopsis": "Writing the script and planning panels...",
            "characters": [],
            "scenes": []
        }

        await save_json_atomic(story_file_path, placeholder_record)

        # Start the background task now that the file exists safely
        background_tasks.add_task(
            generate_full_comic,
            request.topic,
            request.mode,
            request.num_scenes,
            request.render_model,
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
            data = await load_json_resilient(path)
            comics.append({
                "id": data.get("id"),
                "title": data.get("title", "Untitled Comic"),
                "date": data.get("date", ""),
                "mode": data.get("mode", "Story Mode"),
                "isRead": data.get("isRead", False),
                "status": data.get("status"),
                "progress": data.get("progress"),
                "render_model": data.get("render_model", "sdxl"),
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
    _validate_comic_id(comic_id)
    path = os.path.join("static", "outputs", comic_id, "story.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Comic not found")

    try:
        return await load_json_resilient(path)
    except Exception as e:
        print(f"[API ERROR] Failed to read {comic_id} story.json: {e}")
        raise HTTPException(status_code=500, detail="Failed to read comic data")


# ==========================================
# 4. PAUSE COMIC
# ==========================================
@router.post("/api/comics/{comic_id}/pause", tags=["Controls"])
async def pause_comic(comic_id: str):
    _validate_comic_id(comic_id)
    path = os.path.join("static", "outputs", comic_id, "story.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Comic not found")

    data = await load_json_resilient(path)

    if data.get("status") == "generating":
        data["status"] = "pause_requested"
        await save_json_atomic(path, data)
        await interrupt_comfy()
        return {"message": "Pause requested. GPU will stop instantly."}

    return {"message": "Comic is not currently generating."}


# ==========================================
# 5. RESUME COMIC
# ==========================================
@router.post("/api/comics/{comic_id}/resume", tags=["Controls"])
async def resume_comic_endpoint(comic_id: str, background_tasks: BackgroundTasks):
    _validate_comic_id(comic_id)
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
    _validate_comic_id(comic_id)
    path = os.path.join("static", "outputs", comic_id, "story.json")
    dir_path = os.path.join("static", "outputs", comic_id)

    # if the JSON does not exist but the folder does, just wipe it out
    if not os.path.exists(path):
        if os.path.exists(dir_path):
            shutil.rmtree(dir_path, ignore_errors=True)
            return {"message": f"Deleted {comic_id}"}
        raise HTTPException(status_code=404, detail="Comic not found")

    data = await load_json_resilient(path)

    # Cooperative Deletion: If generating, tell the loop to kill itself first
    if data.get("status") == "generating":
        data["status"] = "delete_requested"
        await save_json_atomic(path, data)
        await interrupt_comfy()
        return {"message": "Deletion requested. GPU interrupted."}

    # Safe to wipe instantly
    shutil.rmtree(dir_path, ignore_errors=True)
    return {"message": f"Deleted {comic_id}"}


# ==========================================
# 7. REGENERATE THUMBNAIL
# ==========================================
@router.post("/api/comics/{comic_id}/thumbnail", tags=["Controls"])
async def regenerate_thumbnail_endpoint(comic_id: str, background_tasks: BackgroundTasks):
    _validate_comic_id(comic_id)
    path = os.path.join("static", "outputs", comic_id, "story.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Comic not found")

    # 1. Instantly mark the thumbnail as generating in story.json
    data = await load_json_resilient(path)
    data["thumbnail_status"] = "generating"
    await save_json_atomic(path, data)

    # 2. Add background task
    background_tasks.add_task(regenerate_thumbnail_task, comic_id)
    return {"message": "Thumbnail regeneration started."}


# ==========================================
# 8. REGENERATE ENTIRE COMIC / MODEL HOT-SWAP
# ==========================================
@router.post("/api/comics/{comic_id}/regenerate", tags=["Controls"])
async def regenerate_comic_endpoint(comic_id: str, request: RegenerateRequest, background_tasks: BackgroundTasks):
    _validate_comic_id(comic_id)
    new_model = request.render_model.lower().strip()
    if new_model not in ("sdxl", "flux", "imagen"):
        raise HTTPException(status_code=400, detail="Invalid render_model. Must be 'sdxl', 'flux', or 'imagen'.")

    path = os.path.join("static", "outputs", comic_id, "story.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Comic not found")

    data = await load_json_resilient(path)
    model_dir = os.path.join("static", "outputs", comic_id, new_model)
    os.makedirs(model_dir, exist_ok=True)

    # Legacy migration: If new_model == 'sdxl' and images exist in comic root, sync them into sdxl subfolder
    if new_model == "sdxl":
        root_thumb = os.path.join("static", "outputs", comic_id, "thumbnail.png")
        sub_thumb = os.path.join(model_dir, "thumbnail.png")
        if os.path.exists(root_thumb) and not os.path.exists(sub_thumb):
            try:
                shutil.copy2(root_thumb, sub_thumb)
            except Exception:
                pass

        for index, scene in enumerate(data.get("scenes", [])):
            scene_id = scene.get("id", index + 1)
            root_scene = os.path.join("static", "outputs", comic_id, f"scene_{scene_id}.png")
            sub_scene = os.path.join(model_dir, f"scene_{scene_id}.png")
            if os.path.exists(root_scene) and not os.path.exists(sub_scene):
                try:
                    shutil.copy2(root_scene, sub_scene)
                except Exception:
                    pass

    # 1. Update model
    data["render_model"] = new_model

    # 2. Check for cached images in the target model folder, with fallback to comic root
    thumbnail_expected = os.path.join(model_dir, "thumbnail.png")
    root_thumbnail = os.path.join("static", "outputs", comic_id, "thumbnail.png")
    if os.path.exists(thumbnail_expected):
        data["thumbnail"] = f"/static/outputs/{comic_id}/{new_model}/thumbnail.png"
        data["thumbnail_status"] = "ready"
    elif os.path.exists(root_thumbnail) and new_model == "sdxl":
        data["thumbnail"] = f"/static/outputs/{comic_id}/thumbnail.png"
        data["thumbnail_status"] = "ready"
    else:
        data["thumbnail"] = None
        data["thumbnail_status"] = "idle"

    for index, scene in enumerate(data.get("scenes", [])):
        scene_id = scene.get("id", index + 1)
        scene_expected = os.path.join(model_dir, f"scene_{scene_id}.png")
        root_scene = os.path.join("static", "outputs", comic_id, f"scene_{scene_id}.png")
        if os.path.exists(scene_expected):
            scene["imageUrl"] = f"/static/outputs/{comic_id}/{new_model}/scene_{scene_id}.png"
        elif os.path.exists(root_scene) and new_model == "sdxl":
            scene["imageUrl"] = f"/static/outputs/{comic_id}/scene_{scene_id}.png"
        else:
            scene["imageUrl"] = None

    # Check how many images are missing
    missing = sum(1 for s in data.get("scenes", []) if not s.get("imageUrl"))
    if not data.get("thumbnail") and data.get("thumbnail_status") != "ready":
        missing += 1

    if missing > 0:
        data["status"] = "generating"
        data["progress"] = 10
        await save_json_atomic(path, data)
        background_tasks.add_task(resume_comic, comic_id)
        msg = f"Regeneration started with {new_model}."
    else:
        data["status"] = "completed"
        data["progress"] = 100
        await save_json_atomic(path, data)
        msg = f"Swapped to cached {new_model} renders instantly!"

    return {"message": msg, "render_model": new_model}