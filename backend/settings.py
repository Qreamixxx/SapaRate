"""Settings, read from the .env file in the project root (no extra libraries needed)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_dotenv(ROOT / ".env")


def env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value.strip() if value is not None and value.strip() != "" else default


def env_float(name: str, default: float) -> float:
    try:
        return float(env(name, str(default)))
    except ValueError:
        return default


# --- data ---
DATA_API_URL = env("DATA_API_URL")          # organizers' GET link (group_id is replaced automatically)
DATA_DIR = ROOT / "data"                    # cached copies of downloaded datasets
DB_PATH = Path(env("DB_PATH")) if env("DB_PATH") else ROOT / "storage" / "cqa.db"
DEFAULT_CHECKLIST_FILE = ROOT / "config" / "checklist_v1.json"

# --- LLM providers ---
# PROVIDER: "auto" (default), "gemini", "openai", "mock", or a fallback chain like "gemini,openai"
PROVIDER = env("PROVIDER", "auto").lower()

GEMINI_API_KEY = env("GEMINI_API_KEY")
GEMINI_MODEL = env("GEMINI_MODEL", "gemini-3.8-flash")
# How much the model "thinks" before answering: minimal / low / medium / high (empty = model default).
# Lower is much faster; "low" keeps enough reasoning for N/A vs "not done" decisions.
GEMINI_THINKING = env("GEMINI_THINKING", "low").lower()

# Any OpenAI-compatible API. Default = Groq (free tier).
OPENAI_API_KEY = env("OPENAI_API_KEY")
OPENAI_BASE_URL = env("OPENAI_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
OPENAI_MODEL = env("OPENAI_MODEL", "openai/gpt-oss-120b")

# Prices in USD per 1M tokens, only used to show an estimated cost (0 = free tier)
PRICE_INPUT_PER_1M = env_float("PRICE_INPUT_PER_1M", 0.0)
PRICE_OUTPUT_PER_1M = env_float("PRICE_OUTPUT_PER_1M", 0.0)

# --- behaviour ---
BATCH_CONCURRENCY = max(1, int(env_float("BATCH_CONCURRENCY", 1)))  # keep 1–2 on free tiers
AUDIO_SKIP_PAUSES = env("AUDIO_SKIP_PAUSES", "1") == "1"  # recording pauses are not in the audio file
HOST = env("HOST", "127.0.0.1")
PORT = int(env_float("PORT", 8000))
