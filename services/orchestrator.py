import os
import json
import aiofiles
import uuid
import shutil
import asyncio

from services.llm_service import generate_core_story, extract_story_data
from services.comfy_service import generate_image_from_comfy
from services.imagen_service import generate_image_from_imagen
from models.schemas import GeneratedStory
from utils.file_manager import save_json_atomic, load_json_resilient


def build_runtime_prompt(scene: dict, characters: list, style_config: dict, render_model: str = "sdxl") -> str:
    if render_model in ("flux", "imagen"):
        prompt_text = scene.get("visual", "")
        
        characters_present = scene.get("characters_present", [])
        raw_overrides = scene.get("costume_overrides", [])
        
        override_dict = {}
        for item in raw_overrides:
            if "character_id" in item:
                override_dict[item["character_id"]] = {
                    "body": item.get("body_override"),
                    "tags": item.get("tags", "")
                }
                
        for char_id in characters_present:
            char_data = next((c for c in characters if c.get("id") == char_id), None)
            if not char_data:
                continue
                
            desc_parts = []
            if char_id in override_dict and override_dict[char_id]["body"]:
                desc_parts.append(override_dict[char_id]["body"])
            else:
                desc_parts.append(char_data.get("base_body_tags", ""))
                desc_parts.append(char_data.get("distinctive_features", ""))
                
            if char_id in override_dict and override_dict[char_id]["tags"]:
                desc_parts.append(override_dict[char_id]["tags"])
            else:
                desc_parts.append(char_data.get("default_outfit_tags", ""))
                
            clean_desc = ", ".join([p for p in desc_parts if p])
            if clean_desc:
                prompt_text += f", featuring {char_data.get('name', 'character')} ({clean_desc})"
                
        lighting = style_config.get("lighting_and_atmosphere", "")
        palette = style_config.get("color_palette", "")
        art_style = style_config.get("art_style", "")
        
        extra_styles = ", ".join([s for s in [lighting, palette, art_style] if s])
        if extra_styles:
            prompt_text += f", {extra_styles}"
            
        return prompt_text

    # Default: SDXL Tag-based prompt
    prompt_parts = [
        scene.get("camera", ""),
        scene.get("environment", ""),
        scene.get("emotion", "")
    ]

    characters_present = scene.get("characters_present", [])
    raw_overrides = scene.get("costume_overrides", [])

    override_dict = {}
    for item in raw_overrides:
        if "character_id" in item:
            override_dict[item["character_id"]] = {
                "body": item.get("body_override"),
                "tags": item.get("tags", "")
            }

    if not characters_present:
        prompt_parts.append("no humans")
    else:
        for char_id in characters_present:
            char_data = next((c for c in characters if c.get("id") == char_id), None)
            if not char_data:
                continue

            if char_id in override_dict and override_dict[char_id]["body"]:
                prompt_parts.append(override_dict[char_id]["body"])
            else:
                prompt_parts.append(char_data.get("base_body_tags", ""))
                prompt_parts.append(char_data.get("distinctive_features", ""))

            if char_id in override_dict:
                prompt_parts.append(override_dict[char_id]["tags"])
            else:
                prompt_parts.append(char_data.get("default_outfit_tags", ""))

    prompt_parts.append(scene.get("action_tags", ""))
    prompt_parts.append(style_config.get("lighting_and_atmosphere", ""))
    prompt_parts.append(style_config.get("color_palette", ""))
    prompt_parts.append(style_config.get("art_style", ""))

    clean_parts = [part.strip() for part in prompt_parts if part and part.strip()]
    return ", ".join(clean_parts)


async def regenerate_thumbnail_task(comic_id: str):
    """Standalone task to recreate a thumbnail without touching the scenes."""
    print(f"\n=== [ORCHESTRATOR] REGENERATING THUMBNAIL FOR {comic_id} ===")
    story_file_path = os.path.join("static", "outputs", comic_id, "story.json")

    try:
        comic_record = await load_json_resilient(story_file_path)

        concept = comic_record.get("thumbnail_concept", comic_record.get("synopsis", "epic comic scene"))
        title = comic_record.get("title", "Comic")

        prompt = f"comic book cover art, Title: {title}, {concept}, masterpiece, highly detailed, dramatic lighting, vibrant, graphic novel cover"

        # Generate image via ComfyUI or Google Imagen
        render_model = comic_record.get("render_model", "sdxl")
        if render_model == "imagen":
            image_url = await generate_image_from_imagen(prompt, comic_id, "thumbnail.png")
        else:
            image_url = await generate_image_from_comfy(prompt, comic_id, "thumbnail.png", render_model=render_model)

        # Save to DB and mark completed
        comic_record["thumbnail"] = image_url
        comic_record["thumbnail_status"] = "ready"
        await save_json_atomic(story_file_path, comic_record)

        print(f"[Orchestrator] Thumbnail regenerated successfully!")

    except Exception as e:
        print(f"[ORCHESTRATOR ERROR] Failed to regenerate thumbnail: {str(e)}")
        if os.path.exists(story_file_path):
            try:
                comic_record = await load_json_resilient(story_file_path)
                comic_record["thumbnail_status"] = "failed"
                await save_json_atomic(story_file_path, comic_record)
            except Exception:
                pass


async def generate_full_comic(prompt: str, mode: str = "topic", num_scenes: int = 0, render_model: str = "sdxl", comic_id: str | None = None) -> dict:
    print(f"\n=== [ORCHESTRATOR] STARTING COMIC GENERATION ===")

    if not comic_id:
        comic_id = f"comic-{uuid.uuid4().hex[:8]}"

    story_file_path = os.path.join("static", "outputs", comic_id, "story.json")

    async def save_state():
        await save_json_atomic(story_file_path, comic_record)

    # Load the placeholder state we instantly created in routes.py
    try:
        comic_record = await load_json_resilient(story_file_path)
    except Exception as e:
        print(f"[ORCHESTRATOR ERROR] Failed to load placeholder: {e}")
        return {"status": "failed", "error": "Placeholder missing"}

    comic_record["prompt"] = prompt
    comic_record["raw_mode"] = mode
    comic_record["num_scenes"] = num_scenes
    comic_record["render_model"] = render_model

    try:
        # --- STAGE 1: THE WRITER ---
        if mode == "topic":
            core_story = await asyncio.to_thread(generate_core_story, prompt, "General")
            story_text = core_story.full_story
        else:
            core_story = GeneratedStory(
                title="Custom Story",
                synopsis="A custom story written by the user.",
                full_story=prompt,
                thumbnail_concept="A dramatic comic book cover reflecting the story."
            )
            story_text = prompt

        # Save the pure text to the text file
        async with aiofiles.open(os.path.join("static", "outputs", comic_id, "story_concept.txt"), "w", encoding="utf-8") as f:
            await f.write(story_text)

        # Update JSON progress to show Stage 1 is complete
        comic_record["progress"] = 5
        comic_record["title"] = core_story.title
        comic_record["synopsis"] = core_story.synopsis
        comic_record["thumbnail_concept"] = core_story.thumbnail_concept

        await save_state()

        # --- STAGE 2: THE DIRECTOR ---
        extracted_data = await asyncio.to_thread(extract_story_data, core_story, num_scenes)

        characters = [c.model_dump() for c in extracted_data.characters]
        style_config = extracted_data.style_config.model_dump()
        scenes = [s.model_dump(by_alias=True) for s in extracted_data.scenes]

        frontend_scenes = []
        for scene in scenes:
            scene_data = scene.copy()
            if "scene_number" in scene_data:
                scene_data["id"] = scene_data.pop("scene_number")

            scene_data["imageUrl"] = None
            scene_data["imagePrompt"] = build_runtime_prompt(scene, characters, style_config, render_model)
            frontend_scenes.append(scene_data)

        # UPDATE FILE WITH FULL STORY DATA BEFORE GPU LOOP
        comic_record["progress"] = 10
        comic_record["characters"] = characters
        comic_record["scenes"] = frontend_scenes

        await save_state()

        # --- STAGE 3: THE RENDERER (GPU LOOP OR IMAGEN) ---
        if render_model.lower() == "imagen":
            await run_imagen_render_loop(comic_id, comic_record)
        else:
            await run_gpu_render_loop(comic_record, story_file_path, comic_id)
        return comic_record

    except Exception as e:
        print(f"\n[ORCHESTRATOR ERROR] {str(e)}")
        comic_record["status"] = "failed"
        comic_record["synopsis"] = f"Error during AI generation: {str(e)}"
        await save_state()
        return comic_record


async def resume_comic(comic_id: str):
    """Restarts generation: runs full LLM pipeline if scenes are missing, or restarts GPU loop for missing images."""
    story_file_path = os.path.join("static", "outputs", comic_id, "story.json")
    if not os.path.exists(story_file_path):
        print(f"[Orchestrator] Error: Cannot resume, {comic_id} not found.")
        return

    comic_record = await load_json_resilient(story_file_path)
    scenes = comic_record.get("scenes", [])

    # If the story was interrupted before scenes were generated, re-run full pipeline!
    if not scenes:
        prompt = comic_record.get("prompt")
        concept_path = os.path.join("static", "outputs", comic_id, "story_concept.txt")
        if not prompt and os.path.exists(concept_path):
            try:
                async with aiofiles.open(concept_path, "r", encoding="utf-8") as f:
                    prompt = (await f.read()).strip()
            except Exception:
                pass

        if prompt:
            print(f"\n=== [ORCHESTRATOR] RESUMING FULL PIPELINE (NO SCENES FOUND): {comic_id} ===")
            raw_mode = comic_record.get("raw_mode", "topic" if "topic" in comic_record.get("mode", "").lower() else "story")
            num_scenes = comic_record.get("num_scenes", 0)
            render_model = comic_record.get("render_model", "sdxl")
            await generate_full_comic(prompt, raw_mode, num_scenes, render_model, comic_id)
            return
        else:
            comic_record["status"] = "failed"
            comic_record["synopsis"] = "Cannot resume: No scenes or original prompt found. Please create a new comic from the Home page."
            await save_json_atomic(story_file_path, comic_record)
            print(f"[Orchestrator] Cannot resume {comic_id}: no prompt or scenes found.")
            return

    print(f"\n=== [ORCHESTRATOR] RESUMING COMIC: {comic_id} ===")
    comic_record["status"] = "generating"
    await save_json_atomic(story_file_path, comic_record)

    # Resume the exact same loop!
    if comic_record.get("render_model", "").lower() == "imagen":
        await run_imagen_render_loop(comic_id, comic_record)
    else:
        await run_gpu_render_loop(comic_record, story_file_path, comic_id)


async def run_gpu_render_loop(comic_record: dict, story_file_path: str, comic_id: str):
    """The shared loop used by both Generate and Resume, featuring Pause & Delete detection."""
    scenes = comic_record.get("scenes", [])

    if not scenes:
        comic_record["status"] = "failed"
        if not comic_record.get("synopsis") or "Error" not in comic_record.get("synopsis", ""):
            comic_record["synopsis"] = "No scenes were generated."
        await save_json_atomic(story_file_path, comic_record)
        print(f"[Orchestrator] No scenes to render for {comic_id}.")
        return

    # --- 1. GENERATE COVER THUMBNAIL FIRST (if missing) ---
    if not comic_record.get("thumbnail") and comic_record.get("thumbnail_status") != "ready":
        try:
            print(f"\n[GPU] Generating Cover Art / Thumbnail for {comic_id}...")
            concept = comic_record.get("thumbnail_concept", comic_record.get("synopsis", "epic comic book scene"))
            title = comic_record.get("title", "Comic")
            thumb_prompt = f"comic book cover art, Title: {title}, {concept}, masterpiece, highly detailed, dramatic lighting, vibrant colors, graphic novel cover"

            thumb_url = await generate_image_from_comfy(
                thumb_prompt, comic_id, "thumbnail.png", render_model=comic_record.get("render_model", "sdxl")
            )
            comic_record["thumbnail"] = thumb_url
            comic_record["thumbnail_status"] = "ready"
            await save_json_atomic(story_file_path, comic_record)
        except Exception as e:
            print(f"[GPU Error] Thumbnail generation failed: {e}")
            comic_record["thumbnail_status"] = "failed"
            if "missing_node_type" in str(e) or "Connection refused" in str(e):
                print(f"[Fatal ComfyUI Error] Aborting: {e}")
                comic_record["status"] = "failed"
                comic_record["synopsis"] = f"ComfyUI Error: {e}"
                await save_json_atomic(story_file_path, comic_record)
                return

    # --- 2. RENDER EACH SCENE ---
    last_error = None
    for index, scene in enumerate(scenes):
        # 1. PRE-RENDER CHECK: Did the user pause or delete before we started?
        try:
            live_state = await load_json_resilient(story_file_path)
            if live_state.get("status") == "pause_requested":
                print(f"[Orchestrator] Pause requested! Safely stopping {comic_id}.")
                live_state["status"] = "paused"
                await save_json_atomic(story_file_path, live_state)
                return

            elif live_state.get("status") == "delete_requested":
                print(f"[Orchestrator] Delete requested! Wiping {comic_id} and stopping.")
                shutil.rmtree(os.path.join("static", "outputs", comic_id), ignore_errors=True)
                return

        except FileNotFoundError:
            return

        # Skip images that are already rendered
        if scene.get("imageUrl"):
            continue

        scene_num = scene.get("id")
        print(f"  -> Rendering Panel {scene_num}...")
        final_prompt = scene.get("imagePrompt")

        try:
            image_url = await generate_image_from_comfy(
                prompt_text=final_prompt,
                comic_id=comic_id,
                filename=f"scene_{scene_num}.png",
                render_model=comic_record.get("render_model", "sdxl")
            )
            comic_record["scenes"][index]["imageUrl"] = image_url
            print(f"  -> Panel {scene_num} complete.")
        except Exception as e:
            print(f"     [Error] Panel {scene_num} failed: {e}")
            last_error = str(e)
            if "missing_node_type" in str(e) or "Connection refused" in str(e) or "Failed to connect" in str(e):
                print(f"     [Fatal ComfyUI Error] Aborting render loop: {e}")
                comic_record["status"] = "failed"
                comic_record["synopsis"] = f"ComfyUI Error: {e}"
                await save_json_atomic(story_file_path, comic_record)
                return

        # 2. POST-RENDER CHECK: Did the user hit Pause/Delete WHILE we were rendering?
        try:
            post_state = await load_json_resilient(story_file_path)
            if post_state.get("status") == "delete_requested":
                print(f"[Orchestrator] Delete caught post-render! Wiping {comic_id} permanently.")
                shutil.rmtree(os.path.join("static", "outputs", comic_id), ignore_errors=True)
                return

            if post_state.get("status") == "pause_requested":
                print(f"[Orchestrator] Pause caught post-render! Stopping {comic_id}.")
                rendered_count = sum(1 for s in post_state["scenes"] if s.get("imageUrl"))
                post_state["progress"] = int(10 + (rendered_count / len(scenes)) * 90)
                post_state["status"] = "paused"
                await save_json_atomic(story_file_path, post_state)
                return

        except FileNotFoundError:
            return

        # 3. IF NO INTERRUPTIONS, SAVE PROGRESS
        rendered_count = sum(1 for s in comic_record["scenes"] if s.get("imageUrl"))
        comic_record["progress"] = int(10 + (rendered_count / len(scenes)) * 90)
        await save_json_atomic(story_file_path, comic_record)

    # 4. FINALIZE THE COMIC
    rendered_count = sum(1 for s in comic_record["scenes"] if s.get("imageUrl"))
    if rendered_count == len(scenes):
        comic_record["status"] = "completed"
        comic_record["progress"] = 100
        if not comic_record.get("thumbnail") and scenes and scenes[0].get("imageUrl"):
            comic_record["thumbnail"] = scenes[0]["imageUrl"]
    elif rendered_count > 0:
        comic_record["status"] = "paused"
        comic_record["progress"] = int(10 + (rendered_count / len(scenes)) * 90)
        comic_record["synopsis"] = f"Partially completed ({rendered_count}/{len(scenes)} panels). Resume when ready."
    else:
        comic_record["status"] = "failed"
        comic_record["progress"] = 0
        if last_error:
            comic_record["synopsis"] = f"Generation failed: {last_error}"

    await save_json_atomic(story_file_path, comic_record)
    print(f"=== [ORCHESTRATOR] JOB FINISHED! Status: {comic_record['status']} ===")


async def run_imagen_render_loop(comic_id: str, comic_record: dict):
    """Parallel execution loop for Google Imagen generation with interruption support."""
    scenes = comic_record.get("scenes", [])
    path = os.path.join("static", "outputs", comic_id, "story.json")

    comic_record["status"] = "generating"
    comic_record["synopsis"] = "Sending prompts to Google Imagen in parallel..."
    await save_json_atomic(path, comic_record)

    semaphore = asyncio.Semaphore(3)

    async def sem_task(prompt, c_id, fname):
        async with semaphore:
            if not os.path.exists(path):
                raise Exception("Comic was deleted")
            try:
                live_state = await load_json_resilient(path)
                if live_state.get("status") in ["delete_requested", "pause_requested"]:
                    raise Exception(f"Comic generation interrupted: {live_state.get('status')}")
            except (FileNotFoundError, json.JSONDecodeError):
                raise Exception("Comic was deleted or invalid")

            await asyncio.sleep(0.5)
            return await generate_image_from_imagen(prompt, c_id, fname)

    tasks = []
    task_mapping = {}

    if comic_record.get("thumbnail_status") != "ready" and not comic_record.get("thumbnail"):
        thumb_concept = comic_record.get("thumbnail_concept", comic_record.get("synopsis", "epic comic cover"))
        thumb_prompt = f"comic book cover art, Title: {comic_record.get('title')}, {thumb_concept}, masterpiece, highly detailed, dramatic lighting, vibrant, graphic novel cover"
        tasks.append(sem_task(thumb_prompt, comic_id, "thumbnail.png"))
        task_mapping[len(tasks)-1] = "thumbnail"

    for index, scene in enumerate(scenes):
        if not scene.get("imageUrl"):
            final_prompt = scene.get("imagePrompt", "")
            tasks.append(sem_task(final_prompt, comic_id, f"scene_{index + 1}.png"))
            task_mapping[len(tasks)-1] = f"scene_{index}"

    print(f"[Orchestrator] Launching {len(tasks)} parallel Imagen requests for {comic_id}...")

    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            task_type = task_mapping[i]
            if isinstance(result, Exception):
                print(f"[Imagen Error] Task {task_type} failed: {result}")
                if task_type == "thumbnail":
                    comic_record["thumbnail_status"] = "failed"
            else:
                if task_type == "thumbnail":
                    comic_record["thumbnail"] = result
                    comic_record["thumbnail_status"] = "ready"
                else:
                    scene_idx = int(task_type.split("_")[1])
                    scenes[scene_idx]["imageUrl"] = result

        total = len(scenes) + 1
        completed = sum(1 for s in scenes if s.get("imageUrl")) + (1 if comic_record.get("thumbnail_status") == "ready" else 0)
        progress = int((completed / total) * 100) if total > 0 else 100

        comic_record["progress"] = progress
        if completed == total:
            comic_record["status"] = "completed"
            comic_record["synopsis"] = "All Imagen panels generated successfully!"
        else:
            comic_record["status"] = "failed"
            comic_record["synopsis"] = "Some Imagen panels encountered rate limits. Click retry to resume."

    except Exception as e:
        print(f"[Orchestrator Imagen Error] {e}")
        comic_record["status"] = "failed"
        comic_record["synopsis"] = f"Generation failed: {str(e)}"

    await save_json_atomic(path, comic_record)