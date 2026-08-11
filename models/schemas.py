from pydantic import BaseModel, Field
from typing import List, Optional


# ==========================================
# API Requests
# ==========================================

class GenerateRequest(BaseModel):
    prompt: str
    mode: str


class StoryRequest(BaseModel):
    topic: str = Field(..., description="User's topic, prompt, or raw story idea")
    genre: Optional[str] = Field(default="General", description="Target genre (e.g., Cyberpunk, Sci-Fi, Fantasy)")


# ==========================================
# STAGE 1: Core Story Generation
# ==========================================

class GeneratedStory(BaseModel):
    title: str = Field(..., description="Catchy title for the story")
    synopsis: str = Field(..., description="Short 2-3 sentence summary of the plot")
    full_story: str = Field(..., description="The complete written narrative story text")
    thumbnail_concept: str = Field(..., description="High-level visual concept for the story cover/thumbnail")


# ==========================================
# STAGE 2: Story Extraction & ComfyUI Data
# ==========================================
class StyleConfig(BaseModel):
    art_style: str = Field(...,description="Strict comic tags (e.g., 'single panel, cinematic still, 2d, flat colors, cel shading, heavy inking, masterpiece'). NEVER use 'sequential art' or 'comic page'.")
    lighting_and_atmosphere: str = Field(..., description="Atmosphere (e.g., 'dramatic lighting, sharp shadows')")
    color_palette: str = Field(..., description="Key color theme (e.g., 'muted autumn tones')")
    negative_prompt: str = Field(...,description="Crucial for stopping realism AND grids (e.g., 'multiple panels, grid, split screen, comic page, text, speech bubble, photorealistic, 3d, render')")
    flux_style_description: str = Field(...,description="A natural language sentence describing the art style, e.g., 'The image is illustrated in a highly detailed, 2D comic book style with sharp inking, vibrant flat colors, and deep dramatic shadows.'")
class StoryCharacter(BaseModel):
    id: str = Field(..., description="Stable ID (e.g., 'char1 ,char2')")
    name: str = Field(..., description="Display name")
    role: str = Field(..., description="Role in story")
    base_body_tags: str = Field(..., description="Permanent physical features")
    default_outfit_tags: str = Field(..., description="Standard clothing")
    distinctive_features: str = Field(..., description="Key anchor details")


class Dialogue(BaseModel):
    speaker_id: str = Field(..., description="The ID of the speaker (e.g., 'char_arthur')")
    text: str = Field(..., description="The actual dialogue text")
    type: str = Field(default="speech", description="'speech', 'thought', or 'shout'")

#for gemini api work perfectly
class CostumeOverride(BaseModel):
    character_id: str = Field(..., description="The ID of the character")
    body_override: Optional[str] = Field(default=None, description="Optional replacement for base_body_tags (e.g. for time-skips like adulthood)")
    tags: str = Field(..., description="Danbooru tags for their outfit/costume")


class SceneExtraction(BaseModel):
    id: int = Field(alias="scene_number")
    previous_scene: Optional[int] = Field(default=None,description="ID of the previous scene if continuity is required")
    location: str = Field(..., description="Danbooru tags for location (e.g., 'city park, park bench, outdoors')")
    time: str = Field(..., description="Danbooru tags for time/lighting (e.g., 'morning, winter afternoon')")
    camera: str = Field(..., description="Danbooru tags for camera (e.g., 'wide shot, close up, cowboy shot')")
    emotion: str = Field(..., description="Danbooru tags for mood (e.g., 'lonely, hopeful, crying')")
    characters_present: list[str] = Field(default_factory=list,description="List of character IDs present in this scene")
    costume_overrides: list[CostumeOverride] = Field(default_factory=list, description="Temporary outfit changes for this scene")
    visual: str = Field(..., description="A highly detailed, natural language paragraph describing the exact visual composition. MUST include spatial relationships (e.g., 'In the foreground...', 'Behind the desk...'), exact lighting, and specific character actions. Write this as if describing a movie still to a blind person.")
    action_tags: str = Field(..., description="Danbooru tags for actions (e.g., 'sitting, holding two coffee cups')")
    narration: str = Field(..., description="Narrative text box for the panel")
    dialogues: list[Dialogue] = Field(default_factory=list, description="List of spoken dialogues")

class ExtractedStoryData(BaseModel):
    style_config: StyleConfig
    characters: list[StoryCharacter]
    scenes: list[SceneExtraction]


# ==========================================
# DATABASE: Final Frontend Comic State
# ==========================================

class Scene(BaseModel):
    id: int
    narration: str
    imageUrl: Optional[str] = None
    dialogues: List[Dialogue] = Field(default_factory=list)


class Comic(BaseModel):
    id: str
    title: str
    date: str
    mode: str
    thumbnail: str
    status: str
    isRead: bool
    progress: int
    scenes: List[Scene] = Field(default_factory=list)
