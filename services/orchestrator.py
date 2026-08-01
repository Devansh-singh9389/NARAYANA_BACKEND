import os
import json
import uuid
from datetime import datetime

# Import our custom services
from services.llm_service import generate_core_story, extract_story_data
from services.comfy_service import generate_image_from_comfy


def build_runtime_prompt(scene: dict, characters: list, style_config: dict) -> str:
    """
    (9.8/10 Architecture) Assembles the final ComfyUI prompt using strict, explicit scene states.
    """
    prompt_parts = []

    # 1. Add Explicit Composition Constraints
    prompt_parts.append(scene.get("camera", ""))
    prompt_parts.append(scene.get("location", ""))
    prompt_parts.append(scene.get("time", ""))
    prompt_parts.append(scene.get("emotion", ""))

    # 2. Inject Characters Explicitly
    characters_present = scene.get("characters_present", [])
    raw_overrides = scene.get("costume_overrides", [])

    # Convert the list of objects back into a simple lookup dictionary
    override_dict = {item["character_id"]: item["tags"] for item in raw_overrides if "character_id" in item}

    for char_id in characters_present:
        char_data = next((c for c in characters if c.get("id") == char_id), None)

        if char_data:
            prompt_parts.append(char_data.get("base_body_tags", ""))
            prompt_parts.append(char_data.get("distinctive_features", ""))

            # Check our new override_dict
            if char_id in override_dict:
                prompt_parts.append(override_dict[char_id])
            else:
                prompt_parts.append(char_data.get("default_outfit_tags", ""))

    # 3. Add Scene Actions
    prompt_parts.append(scene.get("action_tags", ""))

    # 4. Add Global Atmosphere & Flat 2D Comic Style
    prompt_parts.append(style_config.get("lighting_and_atmosphere", ""))
    prompt_parts.append(style_config.get("color_palette", ""))
    prompt_parts.append(style_config.get("art_style", ""))

    clean_parts = [part.strip() for part in prompt_parts if part and part.strip()]
    return ", ".join(clean_parts)


async def generate_full_comic(prompt: str, mode: str = "topic", num_scenes: int = 3) -> dict:
    print(f"\n=== [ORCHESTRATOR] STARTING COMIC GENERATION ===")

    # 1. Generate the Comic ID FIRST
    comic_id = f"comic-{uuid.uuid4().hex[:8]}"
    print(f"Assigning ID: {comic_id}")

    # 2. RUN LLM STAGES (The Bypass Logic)
    if mode == "topic":
        print("[1/3] Mode is 'topic'. Generating Core Story via Gemini...")
        core_story = generate_core_story(topic=prompt, genre="General")
    else:
        print("[1/3] Mode is 'story'. Bypassing generation and using User's custom script...")
        # We package the user's raw text into the exact format Stage 2 expects
        core_story = {
            "title": "Custom Story",
            "synopsis": "A custom story written by the user.",
            "thumbnail_concept": "A dramatic comic book cover reflecting the story.",
            "full_story": prompt  # The user's pasted text goes directly here
        }

    print("[2/3] Extracting Scene Logic and Character Sheets...")
    # Stage 2 doesn't care who wrote the story, it just extracts the tags!
    extracted_data = extract_story_data(core_story, num_scenes)
    characters = extracted_data.get("characters", [])
    style_config = extracted_data.get("style_config", {})
    scenes = extracted_data.get("scenes", [])

    # 3. PREPARE THE INITIAL STATE (Preserving all rich metadata)
    frontend_scenes = []
    for scene in scenes:
        scene_data = scene.copy()

        # Rename 'scene_number' to 'id' for the frontend
        if "scene_number" in scene_data:
            scene_data["id"] = scene_data.pop("scene_number")

        scene_data["imageUrl"] = None

        # Save the exact prompt we are sending to ComfyUI for debugging!
        scene_data["imagePrompt"] = build_runtime_prompt(scene, characters, style_config)

        frontend_scenes.append(scene_data)

    comic_record = {
        "id": comic_id,
        "title": core_story.get("title", "Untitled Comic"),
        "date": datetime.now().strftime("%B %d, %Y"),
        "mode": "Story Mode",
        "thumbnail": "",
        "status": "generating",  # Flags to the frontend that it's still working
        "isRead": False,
        "progress": 10,  # Give it 10% progress for finishing the story
        "synopsis": core_story.get("synopsis", ""),
        "characters": characters,
        "scenes": frontend_scenes
    }

    # 4. SAVE THE FILE IMMEDIATELY BEFORE COMFYUI STARTS
    comic_dir = os.path.join("static", "outputs", comic_id)
    os.makedirs(comic_dir, exist_ok=True)
    story_file_path = os.path.join(comic_dir, "story.json")

    with open(story_file_path, "w", encoding="utf-8") as f:
        json.dump(comic_record, f, indent=4)
    print(f"[Orchestrator] Core Story safely saved to {story_file_path}. Starting GPU...")

    # 5. LOOP THROUGH COMFYUI
    print(f"[3/3] Generating {len(scenes)} Images on local GPU...")
    for index, scene in enumerate(scenes):
        scene_num = scene.get("scene_number", scene.get("id"))
        print(f"  -> Rendering Panel {scene_num}...")

        final_prompt = build_runtime_prompt(scene, characters, style_config)

        try:
            image_url = await generate_image_from_comfy(
                prompt_text=final_prompt,
                comic_id=comic_id,
                scene_num=scene_num
            )
        except Exception as e:
            print(f"     [Error] Panel {scene_num} failed: {e}")
            image_url = None

        # Inject the generated image URL into our scenes list
        frontend_scenes[index]["imageUrl"] = image_url
        print(f"  -> Panel {scene_num} complete: {image_url}")

        # PROGRESSIVE SAVE: Update the JSON file after EVERY image!
        # This calculates exact progress percentage for React
        current_progress = int(10 + ((index + 1) / len(scenes)) * 90)
        comic_record["progress"] = current_progress

        with open(story_file_path, "w", encoding="utf-8") as f:
            json.dump(comic_record, f, indent=4)

    # 6. FINALIZE THE COMIC
    comic_record["status"] = "completed"
    comic_record["progress"] = 100
    if frontend_scenes and frontend_scenes[0].get("imageUrl"):
        comic_record["thumbnail"] = frontend_scenes[0]["imageUrl"]

    # Final Save
    with open(story_file_path, "w", encoding="utf-8") as f:
        json.dump(comic_record, f, indent=4)

    print(f"=== [ORCHESTRATOR] GENERATION COMPLETE! Saved to static/outputs/{comic_id}/ ===\n")
    return comic_record


# --- Quick Test Block ---
if __name__ == "__main__":
    import asyncio


    async def run_test():
        test_topic = "A cyberpunk samurai fighting in the neon rain"
        final_comic = await generate_full_comic(test_topic, num_scenes=2)
        print(json.dumps(final_comic, indent=2))


    asyncio.run(run_test())