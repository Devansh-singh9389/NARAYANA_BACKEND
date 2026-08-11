# PanelForge Backend

PanelForge is an AI-powered comic book generation backend. It leverages the power of Large Language Models (LLMs) to write compelling stories and scene descriptions, and then orchestrates an image generation pipeline to bring those stories to life visually as comic panels.

## Features

- **End-to-End Generation**: Takes a topic or user prompt and generates a full comic book with a title, synopsis, character sheets, and sequential scenes.
- **Two-Stage LLM Pipeline**: 
  - **Stage 1 (The Writer)**: Generates the core narrative and characters.
  - **Stage 2 (The Director)**: Breaks down the story into visual panels with precise image generation prompts (Danbooru tags, camera angles, lighting, actions).
- **ComfyUI Integration**: Seamlessly communicates with a local ComfyUI instance via REST and WebSockets to generate comic panels based on the Director's prompts.
- **Live State Management**: Uses a robust local JSON file system (`story.json`) to track the progress of ongoing generations, allowing the frontend to poll for live updates.
- **Advanced Controls**: Supports pausing, resuming, and gracefully deleting running comic generation jobs using Python `BackgroundTasks`.
- **Thumbnail Generation**: Automatically generates or regenerates cover art for each comic.

## Technology Stack

- **Framework**: [FastAPI](https://fastapi.tiangolo.com/) - A modern, fast (high-performance) web framework for building APIs with Python.
- **Data Validation**: [Pydantic](https://docs.pydantic.dev/) - For robust data schemas and type hinting.
- **AI / LLMs**: Google Gemini (via `google-genai` SDK) - Powers the story and scene extraction logic (`gemini-3.6-flash` and `gemini-2.5-flash-lite`).
- **Image Generation**: [ComfyUI](https://github.com/comfyanonymous/ComfyUI) - The backend communicates with a local ComfyUI server (expected at `127.0.0.1:8188`) using its API and WebSocket interface to render the comic panels.

## Project Structure

```
├── api/
│   └── routes.py           # FastAPI endpoints for generation, library management, and controls
├── core/
│   └── config.py           # Configuration (currently empty)
├── models/
│   └── schemas.py          # Pydantic models for API requests, LLM outputs, and comic state
├── services/
│   ├── comfy_service.py    # Logic for interacting with the local ComfyUI API (prompting and downloading)
│   ├── llm_service.py      # Logic for interacting with Google Gemini API for story and scene generation
│   └── orchestrator.py     # Master orchestrator tying LLMs and ComfyUI together, handling the generation loop
├── static/
│   └── outputs/            # Generated comics are stored here (each gets a folder with story.json and images)
├── main.py                 # The FastAPI application entry point
├── requirements.txt        # Python dependencies
└── .env                    # Environment variables (e.g., GEMINI_API_KEY)
```

## Setup and Running

1. **Prerequisites**:
   - Python 3.9+
   - A running instance of **ComfyUI** on `127.0.0.1:8188`.
   - A ComfyUI workflow JSON placed at `assets/workflows/workflow_api.json`.
   - Google Gemini API Key.

2. **Environment Variables**:
   Create a `.env` file in the root directory and add your Gemini API key:
   ```env
   GEMINI_API_KEY=your_google_gemini_api_key_here
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   pip install fastapi uvicorn websockets requests google-genai python-dotenv
   ```
   *(Note: The `requirements.txt` currently only lists `pydantic`, make sure to install all required dependencies).*

4. **Run the Server**:
   ```bash
   python main.py
   ```
   The API will be available at `http://0.0.0.0:8000`. You can access the Swagger UI documentation at `http://localhost:8000/docs`.

## How It Works

1. A user submits a prompt via `/api/generate`.
2. The `orchestrator` creates a placeholder in `static/outputs/` and starts a background task.
3. `llm_service` contacts Gemini to write a story based on the prompt.
4. `llm_service` contacts Gemini again to break the story into a sequence of scenes and visual descriptions.
5. The `orchestrator` loops through each scene, building an image prompt and sending it to `comfy_service`.
6. `comfy_service` sends the prompt to the local ComfyUI server, listens via WebSocket for the finished image, and downloads it to the output folder.
7. The JSON state is continuously updated, allowing the frontend to poll for live progress.
