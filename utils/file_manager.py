import json
import os
import uuid
import asyncio
import aiofiles
from typing import List, Dict

# Path to our local JSON database
DB_PATH = os.path.join("data", "database.json")

def load_history() -> List[Dict]:
    """Loads the comic history from the JSON file."""
    if not os.path.exists(DB_PATH):
        return []
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return []

def save_history(data: List[Dict]):
    """Saves the comic history to the JSON file."""
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


async def save_json_atomic(file_path: str, data: dict):
    """
    Writes data to a temporary file in the same directory and performs an atomic rename.
    In POSIX filesystems, os.replace is atomic, ensuring concurrent readers never see
    an empty (truncated) or partially-written file.
    """
    dir_name = os.path.dirname(file_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    tmp_path = os.path.join(dir_name or ".", f".tmp_{uuid.uuid4().hex[:8]}_{os.path.basename(file_path)}")
    async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
        await f.write(json.dumps(data, indent=4))
    os.replace(tmp_path, file_path)


async def load_json_resilient(file_path: str, retries: int = 4, retry_delay: float = 0.05) -> dict:
    """
    Reads and parses a JSON file with retry backoff in case of transient filesystem lag.
    """
    last_err = None
    for attempt in range(retries):
        try:
            async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
                content = await f.read()
            if not content.strip():
                await asyncio.sleep(retry_delay)
                continue
            return json.loads(content)
        except (json.JSONDecodeError, IOError) as err:
            last_err = err
            await asyncio.sleep(retry_delay)
    raise last_err or ValueError(f"Could not read valid JSON from {file_path}")