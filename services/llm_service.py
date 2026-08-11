import os
import json
from google import genai
from google.genai import types
from dotenv import load_dotenv

from models.schemas import GeneratedStory, ExtractedStoryData

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


def parse_json_safely(text: str) -> dict:
    #Removes markdown formatting that Gemini sometimes adds before parsing JSON.
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

    # FIX 1: Removed the broken variable.
    # FIX 2: Told Gemini to embrace the Traditional Comic Grid!
    system_prompt = """You are an expert comic book Director and ComfyUI Prompt Engineer. 
        Take the provided story and break it down into a highly engaging narrative.
        Ensure characters are assigned stable IDs (e.g., 'char_arthur').
        CRITICAL: We want traditional multi-panel comic pages! Enforce tags like 'sequential art, comic page, multiple panels' in the art_style.
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
    response = client.models.generate_content(model='gemini-3.6-flash', contents=prompt, config=config)

    return parse_json_safely(response.text)


def extract_story_data(core_story_dict: dict, num_scenes: int) -> dict:
    if not GEMINI_API_KEY:
        raise ValueError("Gemini API Key is missing!")

    client = genai.Client(api_key=GEMINI_API_KEY)

    if num_scenes > 0:
        scene_instruction = f"CRITICAL: You MUST generate exactly {num_scenes} pages in the scenes array. Do not rush the story. Use slow, cinematic pacing to perfectly fill exactly {num_scenes} pages."
    else:
        scene_instruction = """CRITICAL: AUTO MODE. You must analyze the story and determine the optimal number of pages. 
        DO NOT RUSH THE NARRATIVE. For emotional or dramatic stories, use a highly cinematic, slow-paced structure. 
        You are free to generate anywhere from 5 to 40 pages to perfectly capture the story."""

    system_prompt = f"""You are an expert comic book Director and ComfyUI Prompt Engineer. 
        Take the provided story and break it down into sequential pages.
        {scene_instruction}
        Ensure characters are assigned stable IDs (e.g., 'char_arthur').
        CRITICAL: We want traditional multi-panel comic pages! Enforce tags like 'sequential art, comic page, multiple panels, panelling' in the art_style.
        Every page MUST explicitly list the characters_present by ID."""

    response = client.models.generate_content(
        model='gemini-2.5-flash-lite',
        contents=f"Extract visual data for this story: {json.dumps(core_story_dict)}",
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=ExtractedStoryData,
            temperature=0.2,
            max_output_tokens=65536,
        ),
    )

    return parse_json_safely(response.text)