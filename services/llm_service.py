import os
import json
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Import both schemas for Stage 1 and Stage 2
from models.schemas import GeneratedStory, ExtractedStoryData

# Load the keys from your .env file securely
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


def generate_core_story(topic: str, genre: str = "General") -> dict:
    """
    STAGE 1: Writes the creative story narrative.
    """
    if not GEMINI_API_KEY:
        raise ValueError("Gemini API Key is missing! Check your .env file.")

    client = genai.Client(api_key=GEMINI_API_KEY)

    system_prompt = """You are an expert comic book Director and ComfyUI Prompt Engineer. 
        Take the provided story and break it down exactly into scenes.
        Ensure characters are assigned stable IDs (e.g., 'char_arthur').
        To prevent realism and maintain a graphic novel aesthetic, ensure the StyleConfig heavily penalizes 3D and realism in the negative_prompt, and enforces '2d, flat colors, comic book style, heavy inking' in the art_style.
        Every scene MUST explicitly list the characters_present by ID and include Danbooru tags for location, time, camera, and emotion."""

    prompt = f"Topic: {topic}\nGenre: {genre}"

    config = types.GenerateContentConfig(
        temperature=0.7,
        response_mime_type="application/json",
        response_schema=GeneratedStory,
        system_instruction=system_prompt,
    )

    print(f"[Story Engine] Writing {genre} story about: {topic}...")

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=config
    )

    return json.loads(response.text)


def extract_story_data(core_story_dict: dict, num_scenes: int = 3) -> dict:
    """
    STAGE 2: Extracts ComfyUI visual prompts, character sheets, and dialogue.
    """
    if not GEMINI_API_KEY:
        raise ValueError("Gemini API Key is missing! Check your .env file.")

    client = genai.Client(api_key=GEMINI_API_KEY)

    # Pass the written story from Stage 1 into Stage 2
    story_text = json.dumps(core_story_dict, indent=2)

    system_prompt = """You are an expert comic book Director and ComfyUI Prompt Engineer. 
    Take the provided story and break it down exactly into scenes.
    Ensure characters are defined precisely to maintain consistency across scenes.
    The 'comfy_prompt' MUST be a comma-separated list of Danbooru-style tags combining the camera, setting, character traits, character actions, and global art style."""

    prompt = f"Here is the core story. Break this down into {num_scenes} scenes.\n\n{story_text}"

    config = types.GenerateContentConfig(
        temperature=0.7,
        response_mime_type="application/json",
        response_schema=ExtractedStoryData,
        system_instruction=system_prompt,
    )

    print(f"[Story Engine] Extracting visual data and breaking into {num_scenes} scenes...")

    response = client.models.generate_content(
        model='gemini-3.6-flash',
        contents=prompt,
        config=config
    )

    return json.loads(response.text)


# --- Quick Test Block ---
if __name__ == "__main__":
    test_topic = "A lone samurai wandering a rainy neon city discovers a glowing cybernetic artifact. and the memory of there best friend who dies for rescue our samurai is flashing in there eyes"
    test_genre = "Cyberpunk / Sci-Fi"

    try:
        # 1. Run Stage 1 (Write the story)
        core_story = generate_core_story(topic=test_topic, genre=test_genre)
        print("[Story Engine] Stage 1 (Story Generation) Complete!")

        # 2. Run Stage 2 (Extract ComfyUI visual parameters)
        extracted_data = extract_story_data(core_story_dict=core_story, num_scenes=3)
        print("[Story Engine] Stage 2 (Visual Extraction) Complete!")

        # 3. Combine everything into one master payload
        final_output = {
            "title": core_story.get("title"),
            "synopsis": core_story.get("synopsis"),
            "thumbnail_concept": core_story.get("thumbnail_concept"),
            "full_story": core_story.get("full_story"),
            "style_config": extracted_data.get("style_config"),
            "characters": extracted_data.get("characters"),
            "scenes": extracted_data.get("scenes")
        }

        # 4. Save to your data/story.json file
        os.makedirs("data", exist_ok=True)
        output_path = os.path.join("data", "story.json")

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(final_output, f, indent=4)

        print(f"\n[Success] Full story and extraction saved to {output_path}!")

    except Exception as err:
        print(f"\n[Test Failed] {err}")