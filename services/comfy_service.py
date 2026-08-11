import json
import os
import uuid
import requests
import websockets
import asyncio
import random

COMFY_HOST = "127.0.0.1:8188"
WORKFLOW_PATH = os.path.join("assets", "workflows", "workflow_api.json")
OUTPUT_DIR = os.path.join("static", "outputs")

os.makedirs(OUTPUT_DIR, exist_ok=True)


def interrupt_comfy():
    try:
        response = requests.post(f"http://{COMFY_HOST}/interrupt")
        return response.status_code == 200
    except Exception as e:
        print(f"[ComfyUI] Failed to interrupt: {e}")
        return False


def find_positive_prompt_node_id(workflow: dict) -> str:
    for node_id, node in workflow.items():
        if isinstance(node, dict) and node.get("class_type") in ["KSampler", "KSamplerAdvanced"]:
            positive_link = node.get("inputs", {}).get("positive")
            if positive_link and isinstance(positive_link, list):
                return str(positive_link[0])

    for node_id, node in workflow.items():
        if isinstance(node, dict) and node.get("class_type") == "CLIPTextEncode":
            return str(node_id)

    raise ValueError("Could not find a valid positive prompt node.")


async def generate_image_from_comfy(prompt_text: str, comic_id: str, filename: str) -> str:
    """
    Commands ComfyUI to generate an image, then downloads it directly into
    our backend's static folder neatly organized by comic_id and filename.
    """
    if not os.path.exists(WORKFLOW_PATH):
        raise FileNotFoundError(f"Workflow file not found at {WORKFLOW_PATH}")

    with open(WORKFLOW_PATH, "r", encoding="utf-8") as f:
        workflow = json.load(f)

    pos_node_id = find_positive_prompt_node_id(workflow)
    if "inputs" not in workflow[pos_node_id]:
        workflow[pos_node_id]["inputs"] = {}
    workflow[pos_node_id]["inputs"]["text"] = prompt_text

    for node_id, node in workflow.items():
        if isinstance(node, dict) and node.get("class_type") in ["KSampler", "KSamplerAdvanced"]:
            if "seed" in node.get("inputs", {}):
                node["inputs"]["seed"] = random.randint(1, 1000000000)
            elif "noise_seed" in node.get("inputs", {}):
                node["inputs"]["noise_seed"] = random.randint(1, 1000000000)

    client_id = str(uuid.uuid4())
    payload = {"prompt": workflow, "client_id": client_id}

    response = requests.post(f"http://{COMFY_HOST}/prompt", json=payload)
    if response.status_code != 200:
        raise Exception(f"ComfyUI Error ({response.status_code}): {response.text}")

    prompt_id = response.json().get("prompt_id")

    ws_url = f"ws://{COMFY_HOST}/ws?clientId={client_id}"
    saved_filename = None
    subfolder = ""
    img_type = "output"

    async with websockets.connect(ws_url) as ws:
        while True:
            out = await ws.recv()
            if isinstance(out, str):
                message = json.loads(out)
                msg_type = message.get("type")
                data = message.get("data", {})

                if msg_type == "executed" and data.get("prompt_id") == prompt_id:
                    output_images = data.get("output", {}).get("images", [])
                    if output_images:
                        saved_filename = output_images[0]["filename"]
                        subfolder = output_images[0].get("subfolder", "")
                        img_type = output_images[0].get("type", "output")
                        break
                
                if msg_type in ["execution_error", "error"]:
                    raise Exception(f"ComfyUI Execution Error: {data}")
                    
                if msg_type == "executing" and data.get("node") is None and data.get("prompt_id") == prompt_id:
                    break

    if not saved_filename:
        raise Exception("No output image filename was captured.")

    img_response = requests.get(
        f"http://{COMFY_HOST}/view",
        params={"filename": saved_filename, "subfolder": subfolder, "type": img_type}
    )

    if img_response.status_code != 200:
        raise Exception("Failed to retrieve the generated image from ComfyUI.")

    # --- SAVE WITH CUSTOM FILENAME ---
    comic_dir = os.path.join(OUTPUT_DIR, comic_id)
    os.makedirs(comic_dir, exist_ok=True)

    local_image_path = os.path.join(comic_dir, filename)

    with open(local_image_path, "wb") as f:
        f.write(img_response.content)

    print(f"[ComfyUI] Saved image to {local_image_path}")

    # Return the relative URL for the frontend
    return f"/static/outputs/{comic_id}/{filename}"