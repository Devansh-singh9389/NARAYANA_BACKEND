import os
from dotenv import load_dotenv

# Load .env file from backend root
load_dotenv(override=False)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
COMFY_HOST = os.getenv("COMFY_HOST", "127.0.0.1:8188")
OUTPUT_DIR = os.path.join("static", "outputs")
