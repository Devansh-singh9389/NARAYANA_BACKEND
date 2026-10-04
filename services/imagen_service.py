import os
import base64
import asyncio
import aiofiles
import time
from google import genai
from dotenv import load_dotenv

load_dotenv()

OUTPUT_DIR = os.path.join("static", "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def get_gemini_api_key() -> str:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        load_dotenv(override=True)
        key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise ValueError("Gemini API Key is missing! Check your .env file.")
    return key


def generate_image_sync(prompt_text: str, retries: int = 2) -> bytes:
    api_key = get_gemini_api_key()
    client = genai.Client(api_key=api_key)

    models_to_try = [
        "gemini-2.5-flash-image",
        "gemini-3.1-flash-image",
        "gemini-3.1-flash-lite-image"
    ]

    for attempt in range(retries):
        for model_name in models_to_try:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=f"Generate a detailed comic panel illustration: {prompt_text}",
                )

                for candidate in (response.candidates or []):
                    for part in (candidate.content.parts or []):
                        if getattr(part, "inline_data", None) and part.inline_data.data:
                            return part.inline_data.data

                raise Exception(f"No image returned from {model_name}.")

            except Exception as e:
                error_str = str(e).lower()
                # Fast fail if key has 0 quota for image generation (free tier)
                if "limit: 0" in error_str or ("quota" in error_str and "free_tier" in error_str):
                    raise Exception(
                        "Google Imagen requires Pay-As-You-Go billing in Google AI Studio. "
                        "Consumer Gemini Advanced/Pro subscriptions don't apply to Developer API keys (which stay on Free Tier with 0 image quota). "
                        "Use SDXL or Flux to render locally for free, or enable Pay-As-You-Go billing at aistudio.google.com!"
                    )

                if "429" in error_str or "resource_exhausted" in error_str:
                    if attempt < retries - 1:
                        sleep_time = 5 * (attempt + 1)
                        print(f"[Imagen] Rate limit hit. Waiting {sleep_time}s...")
                        time.sleep(sleep_time)
                        break

                if "not found" in error_str or "unsupported" in error_str:
                    continue

                if attempt == retries - 1:
                    raise e


async def generate_image_from_imagen(prompt_text: str, comic_id: str, filename: str, render_model: str = "imagen") -> str:
    """
    Commands Google Image API to generate an image, then saves it directly into
    our backend's static folder neatly organized by comic_id and render_model.
    Non-blocking async using asyncio.to_thread and aiofiles.
    """
    print(f"[Imagen] Generating {filename} for {comic_id}...")

    image_bytes = await asyncio.to_thread(generate_image_sync, prompt_text)

    model_dir = os.path.join(OUTPUT_DIR, comic_id, render_model)
    os.makedirs(model_dir, exist_ok=True)

    file_path = os.path.join(model_dir, filename)

    async with aiofiles.open(file_path, "wb") as f:
        await f.write(image_bytes)

    print(f"[Imagen] Saved image to {file_path}")
    return f"/static/outputs/{comic_id}/{render_model}/{filename}"
