"""Settings for the standalone Lunar Studio app.

The new app reuses the repository's ``.env`` (DeepSeek and ComfyUI keys) but
keeps its own SQLite database, uploads and rendered media. Nothing here writes
to the legacy Streamlit database.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

STUDIO_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STUDIO_ROOT.parent

# The ComfyUI launcher in ``services/`` imports ``config.settings``; when the
# API is started from the repository root that import already works. Keeping
# the explicit path insert makes ``uvicorn studio.api.main:app`` work from a
# different working directory too.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

load_dotenv(REPO_ROOT / ".env")


def _path(raw: str | None, default: Path) -> Path:
    if not raw:
        return default
    value = Path(raw)
    return value if value.is_absolute() else (REPO_ROOT / value)


DATA_DIR = _path(os.getenv("STUDIO_DATA_DIR"), STUDIO_ROOT / "data")
DB_PATH = _path(os.getenv("STUDIO_DB_PATH"), DATA_DIR / "lumen.sqlite3")
UPLOAD_DIR = _path(os.getenv("STUDIO_UPLOAD_DIR"), DATA_DIR / "uploads")
MEDIA_DIR = _path(os.getenv("STUDIO_MEDIA_DIR"), REPO_ROOT / "output" / "studio")
SKILL_DIR = _path(os.getenv("STUDIO_SKILL_DIR"), STUDIO_ROOT / "skills")
WORKFLOW_DIR = _path(os.getenv("STUDIO_WORKFLOW_DIR"), STUDIO_ROOT / "workflows")

for folder in (DATA_DIR, UPLOAD_DIR, MEDIA_DIR):
    folder.mkdir(parents=True, exist_ok=True)

DEEPSEEK_API_KEY = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
DEEPSEEK_BASE_URL = (
    os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com"
).strip().rstrip("/")
DEEPSEEK_MODEL = (os.getenv("DEEPSEEK_MODEL") or "deepseek-chat").strip()
DEEPSEEK_JSON_MODE = (os.getenv("DEEPSEEK_JSON_MODE") or "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

try:
    DEEPSEEK_TIMEOUT_SECONDS = float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "120"))
except ValueError:
    DEEPSEEK_TIMEOUT_SECONDS = 120.0

try:
    DEEPSEEK_MAX_RETRIES = int(os.getenv("DEEPSEEK_MAX_RETRIES", "2"))
except ValueError:
    DEEPSEEK_MAX_RETRIES = 2

COMFYUI_URL = (os.getenv("AIGC_COMFYUI_URL") or "http://127.0.0.1:8188").strip().rstrip("/")

#: ComfyUI sends execution events to the client id that queued the prompt.
#: One fixed id lets the progress websocket listen to those events.
#: Unique per API process: two servers (or a stale one) must never share a
#: websocket id, otherwise ComfyUI sends the events to whichever connected
#: last and the other sits at 0%.
COMFY_CLIENT_ID = f"lunar-studio-{os.getpid()}"

try:
    COMFYUI_HTTP_TIMEOUT = float(os.getenv("AIGC_COMFYUI_HTTP_TIMEOUT", "15"))
except ValueError:
    COMFYUI_HTTP_TIMEOUT = 15.0

try:
    COMFYUI_JOB_TIMEOUT = float(os.getenv("AIGC_COMFYUI_JOB_TIMEOUT", "1800"))
except ValueError:
    COMFYUI_JOB_TIMEOUT = 1800.0

# Max upload size (bytes). A product photo is not a RAW file.
MAX_UPLOAD_BYTES = 16 * 1024 * 1024

SKILLS = {
    "cinema": {
        "path": SKILL_DIR / "cinema-dna",
        "label": "Cinema DNA",
        "version": "3.1.1",
        "source": "https://github.com/dacnay816y62-hub/cinema-dna-21x9x3",
    },
    "ecommerce": {
        "path": SKILL_DIR / "ecom-details-image",
        "label": "E-commerce Visual",
        "version": "main",
        "source": "https://github.com/liangdabiao/ecom-details-image",
    },
    "video": {
        "path": SKILL_DIR / "video-h3",
        "label": "Video Clip",
        "version": "1.0.0",
        "source": "local skill · MiniMax H3",
    },
    "taste": {
        "path": SKILL_DIR / "taste-skill",
        "label": "Taste Skill",
        "version": "2.1",
        "source": "https://github.com/Leonxlnx/taste-skill",
    },
}

# Output dimensions are chosen to fit an 8 GB card. They are deliberately
# approximate for the 2.39:1 family: 1024x432 is 2.37:1, the closest stable
# SD3-latent size to Cinema DNA's widescreen target.
#: MiniMax H3 only accepts 5 or 10 second clips (the template declares both).
VIDEO_DURATIONS: tuple[int, ...] = (5, 10)

#: H3 is far heavier than Z-Image: on an 8 GB card the 10 s clip only fits at
#: the smaller step of each aspect. Index 0 is used for 5 s, index 1 for 10 s.
VIDEO_SIZES: dict[str, tuple[tuple[int, int], tuple[int, int]]] = {
    "16:9": ((768, 432), (640, 368)),
    "2.39:1": ((768, 320), (640, 272)),
    "9:16": ((432, 768), (368, 640)),
    "1:1": ((576, 576), (480, 480)),
    "4:3": ((640, 480), (544, 400)),
}

#: ComfyUI graph for text-to-video. Missing file is an honest error, not a
#: fallback: the studio never pretends to render a clip it cannot make.
VIDEO_WORKFLOW = "minimax_h3_t2v.json"

#: The 8-step distilled LoRA is on by default: 20 steps at 10 s is hours on an
#: 8 GB card, 8 steps is minutes and good enough for a first pass.
VIDEO_TURBO = (os.getenv("STUDIO_VIDEO_TURBO") or "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

ASPECT_SIZES: dict[str, tuple[int, int]] = {
    "2.39:1": (1024, 432),
    "21:9": (1008, 432),
    "16:9": (1024, 576),
    "4:3": (1024, 768),
    "1:1": (1024, 1024),
    "4:5": (896, 1120),
    "3:4": (864, 1152),
    "2:3": (832, 1248),
    "9:16": (576, 1024),
}

DEFAULT_ASPECT = {
    "cinema": "2.39:1",
    "ecommerce": "1:1",
    "auto": "2.39:1",
}
