import os
import json
import aiofiles
import uuid
import shutil
import asyncio

from services.llm_service import generate_core_story, extract_story_data
from services.comfy_service import generate_image_from_comfy
from models.schemas import GeneratedStory


def build_runtime_prompt(scene: dict, characters: list, style_config: dict, render_model: str = "sdxl") -> str:
    if render_model == "flux":
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
                
            if char_id in override_dict:
                desc_parts.append(override_dict[char_id]["tags"])
            else:
                desc_parts.append(char_data.get("default_outfit_tags", ""))
                
            clean_desc = ", ".join([p.strip() for p in desc_parts if p and p.strip()])
            
            prompt_text = prompt_text.replace(char_id, f"person ({clean_desc})")
            
        flux_style = style_config.get("flux_style_description", "")
        if flux_style:
            prompt_text = f"{prompt_text} {flux_style}"
            
        return prompt_text.strip()

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

    for char_id in characters_present:
        char_data = next((c for c in characters if c.get("id") == char_id), None)
        if char_data:
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
        async with aiofiles.open(story_file_path, "r", encoding="utf-8") as f:
            comic_record = json.loads(await f.read())

        concept = comic_record.get("thumbnail_concept", comic_record.get("synopsis", "epic comic scene"))
        title = comic_record.get("title", "Comic")

        prompt = f"comic book cover art, Title: {title}, {concept}, masterpiece, highly detailed, dramatic lighting, vibrant, graphic novel cover"

        # Generate image via ComfyUI
        render_model = comic_record.get("render_model", "sdxl")
        image_url = await generate_image_from_comfy(prompt, comic_id, "thumbnail.png", render_model=render_model)

        # Save to DB and mark completed
        comic_record["thumbnail"] = image_url
        comic_record["thumbnail_status"] = "completed"  # <-- MARK COMPLETED

        async with aiofiles.open(story_file_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(comic_record, indent=4))

        print(f"[Orchestrator] Thumbnail regenerated successfully!")

    except Exception as e:
        print(f"[ORCHESTRATOR ERROR] Failed to regenerate thumbnail: {str(e)}")
        # Reset status if it failed
        if os.path.exists(story_file_path):
            async with aiofiles.open(story_file_path, "r", encoding="utf-8") as f:
                comic_record = json.loads(await f.read())
            comic_record["thumbnail_status"] = "failed"
            async with aiofiles.open(story_file_path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(comic_record, indent=4))


async def generate_full_comic(prompt: str, mode: str = "topic", num_scenes: int = 0, render_model: str = "sdxl", comic_id: str | None = None) -> dict:
    print(f"\n=== [ORCHESTRATOR] STARTING COMIC GENERATION ===")

    if not comic_id:
        comic_id = f"comic-{uuid.uuid4().hex[:8]}"

    story_file_path = os.path.join("static", "outputs", comic_id, "story.json")

    async def save_state():
        async with aiofiles.open(story_file_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(comic_record, indent=4))

    # Load the placeholder state we instantly created in routes.py
    try:
        async with aiofiles.open(story_file_path, "r", encoding="utf-8") as f:
            comic_record = json.loads(await f.read())
    except Exception as e:
        print(f"[ORCHESTRATOR ERROR] Failed to load placeholder: {e}")
        return {"status": "failed", "error": "Placeholder missing"}

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

        # --- STAGE 3: THE RENDERER (GPU LOOP) ---
        await run_gpu_render_loop(comic_record, story_file_path, comic_id)
        return comic_record

    except Exception as e:
        print(f"\n[ORCHESTRATOR ERROR] {str(e)}")
        comic_record["status"] = "failed"
        comic_record["synopsis"] = f"Error during AI generation: {str(e)}"
        await save_state()
        return comic_record


async def resume_comic(comic_id: str):
    """Bypasses the LLM and instantly restarts the GPU loop for missing images."""
    story_file_path = os.path.join("static", "outputs", comic_id, "story.json")
    if not os.path.exists(story_file_path):
        print(f"[Orchestrator] Error: Cannot resume, {comic_id} not found.")
        return

    async with aiofiles.open(story_file_path, "r", encoding="utf-8") as f:
        comic_record = json.loads(await f.read())

    print(f"\n=== [ORCHESTRATOR] RESUMING COMIC: {comic_id} ===")
    comic_record["status"] = "generating"

    async with aiofiles.open(story_file_path, "w", encoding="utf-8") as f:
        await f.write(json.dumps(comic_record, indent=4))

    # Resume the exact same loop!
    await run_gpu_render_loop(comic_record, story_file_path, comic_id)


async def run_gpu_render_loop(comic_record: dict, story_file_path: str, comic_id: str):
    """The shared loop used by both Generate and Resume, featuring Pause & Delete detection."""
    scenes = comic_record.get("scenes", [])

    # --- 1. GENERATE COVER THUMBNAIL FIRST (if missing) ---
    if not comic_record.get("thumbnail"):
        try:
            print(f"\n[GPU] Generating Cover Art / Thumbnail for {comic_id}...")
            concept = comic_record.get("thumbnail_concept", comic_record.get("synopsis", "epic comic book scene"))
            title = comic_record.get("title", "Comic")
            thumb_prompt = f"comic book cover art, Title: {title}, {concept}, masterpiece, highly detailed, dramatic lighting, vibrant colors, graphic novel cover"

            thumb_url = await generate_image_from_comfy(thumb_prompt, comic_id, "thumbnail.png", render_model=comic_record.get("render_model", "sdxl"))
            comic_record["thumbnail"] = thumb_url

            async with aiofiles.open(story_file_path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(comic_record, indent=4))
        except Exception as e:
            print(f"[GPU Error] Thumbnail generation failed: {e}")

    # --- 2. RENDER EACH SCENE ---
    for index, scene in enumerate(scenes):
        # 1. PRE-RENDER CHECK: Did the user pause or delete before we started?
        try:
            async with aiofiles.open(story_file_path, "r", encoding="utf-8") as f:
                live_state = json.loads(await f.read())

            if live_state.get("status") == "pause_requested":
                print(f"[Orchestrator] Pause requested! Safely stopping {comic_id}.")
                live_state["status"] = "paused"
                async with aiofiles.open(story_file_path, "w", encoding="utf-8") as f:
                    await f.write(json.dumps(live_state, indent=4))
                return  # Kill the loop safely!

            elif live_state.get("status") == "delete_requested":
                print(f"[Orchestrator] Delete requested! Wiping {comic_id} and stopping.")
                shutil.rmtree(os.path.join("static", "outputs", comic_id), ignore_errors=True)
                return  # Kill the loop and wipe the folder!

        except FileNotFoundError:
            return  # File was wiped manually, just exit

        # Skip images that are already rendered
        if scene.get("imageUrl"):
            continue

        scene_num = scene.get("id")
        print(f"  -> Rendering Panel {scene_num}...")
        final_prompt = scene.get("imagePrompt")

        try:
            # Use the new filename parameter: "scene_<id>.png"
            image_url = await generate_image_from_comfy(
                prompt_text=final_prompt,
                comic_id=comic_id,
                filename=f"scene_{scene_num}.png", render_model=comic_record.get("render_model", "sdxl")
            )
        except Exception as e:
            print(f"     [Error] Panel {scene_num} failed: {e}")
            image_url = None

        # 2. POST-RENDER CHECK: Did the user hit Pause/Delete WHILE we were rendering?
        try:
            async with aiofiles.open(story_file_path, "r", encoding="utf-8") as f:
                post_state = json.loads(await f.read())

            if post_state.get("status") == "delete_requested":
                print(f"[Orchestrator] Delete caught post-render! Wiping {comic_id} permanently.")
                shutil.rmtree(os.path.join("static", "outputs", comic_id), ignore_errors=True)
                return

            if post_state.get("status") == "pause_requested":
                print(f"[Orchestrator] Pause caught post-render! Stopping {comic_id}.")
                post_state["scenes"][index]["imageUrl"] = image_url
                rendered_count = sum(1 for s in post_state["scenes"] if s.get("imageUrl"))
                post_state["progress"] = int(10 + (rendered_count / len(scenes)) * 90)
                post_state["status"] = "paused"
                async with aiofiles.open(story_file_path, "w", encoding="utf-8") as f:
                    await f.write(json.dumps(post_state, indent=4))
                return

        except FileNotFoundError:
            return

        # 3. IF NO INTERRUPTIONS, SAVE NORMALLY
        comic_record["scenes"][index]["imageUrl"] = image_url
        print(f"  -> Panel {scene_num} complete.")

        rendered_count = sum(1 for s in comic_record["scenes"] if s.get("imageUrl"))
        comic_record["progress"] = int(10 + (rendered_count / len(scenes)) * 90)

        async with aiofiles.open(story_file_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(comic_record, indent=4))

    # 4. FINALIZE THE COMIC
    comic_record["status"] = "completed"
    comic_record["progress"] = 100
    if scenes and scenes[0].get("imageUrl"):
        comic_record["thumbnail"] = scenes[0]["imageUrl"]  # fallback if thumb missing

    async with aiofiles.open(story_file_path, "w", encoding="utf-8") as f:
        await f.write(json.dumps(comic_record, indent=4))
    print(f"=== [ORCHESTRATOR] JOB FINISHED! ===")