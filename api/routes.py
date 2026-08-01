from fastapi import APIRouter, HTTPException
from models.schemas import GenerateRequest, Comic, Scene
from utils.file_manager import load_history, save_history
from services.comfy_service import generate_image_from_comfy
import time

router = APIRouter()

@router.get("/api/history")
async def get_history():
    return load_history()

@router.delete("/api/history/{comic_id}")
async def delete_story(comic_id: str):
    history = load_history()
    history = [comic for comic in history if comic["id"] != comic_id]
    save_history(history)
    return {"success": True}

@router.post("/api/generate")
async def generate_comic(request: GenerateRequest):
    """
    Triggers real ComfyUI image generation!
    """
    try:
        # 1. Call ComfyUI to render an image based on the prompt
        image_url = await generate_image_from_comfy(request.prompt)

        # 2. Save result to history
        history = load_history()
        new_id = f"comic-{int(time.time())}"

        new_comic = {
            "id": new_id,
            "title": f"Generated: {request.prompt[:20]}...",
            "date": "Just now",
            "mode": request.mode.capitalize(),
            "thumbnail": f"http://127.0.0.1:8000{image_url}",
            "status": "completed",
            "isRead": False,
            "progress": 100,
            "scenes": [
                {
                    "id": 1,
                    "narration": f"Scene generated for: {request.prompt}",
                    "imageUrl": f"http://127.0.0.1:8000{image_url}"
                }
            ]
        }

        history.insert(0, new_comic)
        save_history(history)
        return new_comic

    except Exception as e:
        print(f"[Error] Generation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")

@router.get("/api/comic/{comic_id}")
async def get_comic(comic_id: str):
    history = load_history()
    for comic in history:
        if comic["id"] == comic_id:
            return comic
    raise HTTPException(status_code=404, detail="Comic not found")