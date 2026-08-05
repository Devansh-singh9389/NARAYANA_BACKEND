import os
import json
from google import genai
from google.genai import types
from dotenv import load_dotenv

from models.schemas import GeneratedStory, ExtractedStoryData

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


# --- NEW: Bulletproof JSON Cleaner ---
def parse_json_safely(text: str) -> dict:
    """Removes markdown formatting that Gemini sometimes adds before parsing JSON."""
    clean_text = text.strip()
    if clean_text.startswith("```json"):
        clean_text = clean_text[7:]
    if clean_text.startswith("```"):
        clean_text = clean_text[3:]
    if clean_text.endswith("```"):
        clean_text = clean_text[:-3]

    clean_text = clean_text.strip()
    return json.loads(clean_text)


def generate_core_story(topic: str, genre: str = "General") -> dict:
    if not GEMINI_API_KEY:
        raise ValueError("Gemini API Key is missing! Check your .env file.")

    client = genai.Client(api_key=GEMINI_API_KEY)
    system_prompt = """You are an expert comic book Director... (Keep your exact prompt here)"""

    # Shortened for brevity, keep your system_prompt exactly as you had it!
    system_prompt = """You are an expert comic book Director and ComfyUI Prompt Engineer. 
        Take the provided story and break it down exactly into scenes.
        Ensure characters are assigned stable IDs (e.g., 'char_arthur').
        CRITICAL: If a character ages significantly due to a time skip, create a completely new character entry in the characters array (e.g., 'char_lily_child' and 'char_lily_adult').
        To prevent realism and maintain a graphic novel aesthetic, ensure the StyleConfig heavily penalizes 3D and realism in the negative_prompt, and enforces '2d, flat colors, comic book style, heavy inking' in the art_style.
        Every scene MUST explicitly list the characters_present by ID and include Danbooru tags for location, time, camera, emotion, and visual."""

    prompt = f"Topic: {topic}\nGenre: {genre}"
    config = types.GenerateContentConfig(
        temperature=0.7,
        response_mime_type="application/json",
        response_schema=GeneratedStory,
        system_instruction=system_prompt,
        max_output_tokens=65536,
    )

    print(f"[Story Engine] Writing {genre} story about: {topic[:50]}...")
    response = client.models.generate_content(model='gemini-3.5-flash-lite', contents=prompt, config=config)

    # FIX 1: Use the safe parser
    return parse_json_safely(response.text)


def extract_story_data(core_story_dict: dict, num_scenes: int) -> dict:
    if not GEMINI_API_KEY:
        raise ValueError("Gemini API Key is missing!")

    client = genai.Client(api_key=GEMINI_API_KEY)

    if num_scenes > 0:
        scene_instruction = f"CRITICAL: You MUST generate exactly {num_scenes} scenes in the scenes array. Do not rush the story. Use slow, cinematic pacing to perfectly fill exactly {num_scenes} panels."
    else:
        scene_instruction = """CRITICAL: AUTO MODE. You must analyze the story and determine the optimal number of scenes. 
        DO NOT RUSH THE NARRATIVE. For emotional or dramatic stories, use a highly cinematic, slow-paced panel structure (like a manga or graphic novel). 
        You are free to generate anywhere from 5 to 40 scenes to perfectly capture every micro-expression, environmental transition, and story beat."""

    system_prompt = f"""You are an expert comic book Director and ComfyUI Prompt Engineer. 
        Take the provided story and break it down into sequential panels.
        {scene_instruction}
        Ensure characters are assigned stable IDs (e.g., 'char_arthur').
        To prevent realism, ensure the StyleConfig penalizes 3D in the negative_prompt.
        Every scene MUST explicitly list the characters_present by ID."""

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=f"Extract visual data for this story: {json.dumps(core_story_dict)}",
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=ExtractedStoryData,
            temperature=0.2,
            max_output_tokens=65536,
        ),
    )

    # FIX 2: Use the safe parser
    return parse_json_safely(response.text)