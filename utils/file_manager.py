import json
import os
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