"""Small, explicit application settings.

Only settings used by the current MVP are loaded here. DeepSeek credentials
will be added in a later phase with the LLM service, not stored in code.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def _resolve_path(raw_value: str | None, default: Path) -> Path:
    if not raw_value:
        return default
    path = Path(raw_value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


DATA_DIR = _resolve_path(os.getenv("AIGC_DATA_DIR"), PROJECT_ROOT / "data")
DB_PATH = _resolve_path(os.getenv("AIGC_DB_PATH"), DATA_DIR / "aigc_agent.sqlite3")
OUTPUT_DIR = _resolve_path(os.getenv("AIGC_OUTPUT_DIR"), PROJECT_ROOT / "output")

try:
    DURATION_TOLERANCE_SECONDS = float(
        os.getenv("DURATION_TOLERANCE_SECONDS", "0.5")
    )
except ValueError as exc:
    raise ValueError("DURATION_TOLERANCE_SECONDS must be a number") from exc

if DURATION_TOLERANCE_SECONDS < 0:
    raise ValueError("DURATION_TOLERANCE_SECONDS must be >= 0")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = (
    os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com"
).strip().rstrip("/")
DEEPSEEK_MODEL = (
    os.getenv("DEEPSEEK_MODEL") or "deepseek-chat"
).strip()
DEEPSEEK_JSON_MODE = os.getenv("DEEPSEEK_JSON_MODE", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

try:
    DEEPSEEK_TIMEOUT_SECONDS = float(
        os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "60")
    )
except ValueError as exc:
    raise ValueError("DEEPSEEK_TIMEOUT_SECONDS must be a number") from exc
if DEEPSEEK_TIMEOUT_SECONDS <= 0:
    raise ValueError("DEEPSEEK_TIMEOUT_SECONDS must be > 0")

try:
    DEEPSEEK_MAX_RETRIES = int(os.getenv("DEEPSEEK_MAX_RETRIES", "2"))
except ValueError as exc:
    raise ValueError("DEEPSEEK_MAX_RETRIES must be an integer") from exc
if DEEPSEEK_MAX_RETRIES < 0:
    raise ValueError("DEEPSEEK_MAX_RETRIES must be >= 0")

TARGET_VIDEO_MODEL = (
    os.getenv("TARGET_VIDEO_MODEL") or "generic"
).strip()

try:
    MAX_CLIPS_PER_PROJECT = int(os.getenv("AIGC_MAX_CLIPS", "12"))
except ValueError as exc:
    raise ValueError("AIGC_MAX_CLIPS must be an integer") from exc
if not 1 <= MAX_CLIPS_PER_PROJECT <= 60:
    raise ValueError("AIGC_MAX_CLIPS must be between 1 and 60")

# ---------------------------------------------------------------------------
# Local generation backend (ComfyUI)
# ---------------------------------------------------------------------------
#: Where the local ComfyUI server listens. The desktop app uses 8188 by default.
COMFYUI_URL = (
    os.getenv("AIGC_COMFYUI_URL") or "http://127.0.0.1:8188"
).strip().rstrip("/")

#: Directory of API-format workflows. Export one from ComfyUI with
#: "Workflow → Export (API)" and drop the JSON here; the studio fills in the
#: prompt and the clip length and submits it unchanged.
WORKFLOW_DIR = _resolve_path(os.getenv("AIGC_WORKFLOW_DIR"), PROJECT_ROOT / "workflows")

#: Rendered clips and stills live here, one folder per project.
MEDIA_DIR = _resolve_path(os.getenv("AIGC_MEDIA_DIR"), OUTPUT_DIR / "media")

try:
    COMFYUI_HTTP_TIMEOUT_SECONDS = float(
        os.getenv("AIGC_COMFYUI_HTTP_TIMEOUT", "15")
    )
except ValueError as exc:
    raise ValueError("AIGC_COMFYUI_HTTP_TIMEOUT must be a number") from exc
if COMFYUI_HTTP_TIMEOUT_SECONDS <= 0:
    raise ValueError("AIGC_COMFYUI_HTTP_TIMEOUT must be > 0")

try:
    COMFYUI_JOB_TIMEOUT_SECONDS = float(
        os.getenv("AIGC_COMFYUI_JOB_TIMEOUT", "1800")
    )
except ValueError as exc:
    raise ValueError("AIGC_COMFYUI_JOB_TIMEOUT must be a number") from exc
if COMFYUI_JOB_TIMEOUT_SECONDS <= 0:
    raise ValueError("AIGC_COMFYUI_JOB_TIMEOUT must be > 0")

try:
    COMFYUI_POLL_SECONDS = float(os.getenv("AIGC_COMFYUI_POLL", "1"))
except ValueError as exc:
    raise ValueError("AIGC_COMFYUI_POLL must be a number") from exc
if COMFYUI_POLL_SECONDS <= 0:
    raise ValueError("AIGC_COMFYUI_POLL must be > 0")

#: Optional auto-start. When the three paths below are set, the 本地生成 page
#: can bring ComfyUI up itself instead of asking the user to open it first.
COMFYUI_PYTHON = (os.getenv("AIGC_COMFYUI_PYTHON") or "").strip()
COMFYUI_HOME = (os.getenv("AIGC_COMFYUI_HOME") or "").strip()
COMFYUI_MODELS_DIR = (os.getenv("AIGC_COMFYUI_MODELS_DIR") or "").strip()

try:
    COMFYUI_START_TIMEOUT = float(os.getenv("AIGC_COMFYUI_START_TIMEOUT", "180"))
except ValueError as exc:
    raise ValueError("AIGC_COMFYUI_START_TIMEOUT must be a number") from exc
if COMFYUI_START_TIMEOUT <= 0:
    raise ValueError("AIGC_COMFYUI_START_TIMEOUT must be > 0")


def guide_mode() -> str:
    """Whether the conversation layer may call the model.

    ``auto``  - use the model when a key is configured (default);
    ``llm``   - always try the model, fail loudly in the logs if unavailable;
    ``rules`` - never call the model, always run the deterministic policy.

    Read at call time so tests and the CLI can switch it without reimporting.
    """

    value = (os.getenv("AIGC_GUIDE_MODE") or "auto").strip().lower()
    if value not in {"auto", "llm", "rules"}:
        raise ValueError("AIGC_GUIDE_MODE must be auto, llm or rules")
    return value


GUIDE_MODE = guide_mode()


try:
    MAX_REVISIONS = int(os.getenv("MAX_REVISIONS", "2"))
except ValueError as exc:
    raise ValueError("MAX_REVISIONS must be an integer") from exc
if not 0 <= MAX_REVISIONS <= 2:
    raise ValueError("MAX_REVISIONS must be between 0 and 2")
