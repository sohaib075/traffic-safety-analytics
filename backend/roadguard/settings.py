"""Process-wide settings, overridable through environment variables."""
from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("ROADGUARD_DATA", BACKEND_DIR / "data"))
EVIDENCE_DIR = DATA_DIR / "evidence"
UPLOAD_DIR = DATA_DIR / "uploads"
CONFIG_DIR = Path(os.environ.get("ROADGUARD_CONFIG", BACKEND_DIR / "config"))
CAMERA_CONFIG_DIR = CONFIG_DIR / "cameras"
DB_URL = os.environ.get("ROADGUARD_DB", f"sqlite:///{(DATA_DIR / 'roadguard.db').as_posix()}")

MODEL_PATH = os.environ.get("ROADGUARD_MODEL", "yolov8n.pt")
DEVICE = os.environ.get("ROADGUARD_DEVICE", "cpu")

# Login is OFF by default (single-user local mode: everyone gets full access, no sign-in).
# Set ROADGUARD_AUTH=1 to turn on accounts, roles, the login page and the Users page.
AUTH_ENABLED = os.environ.get("ROADGUARD_AUTH", "0") == "1"
# Signing secret for bearer tokens. A random per-install secret is generated on first
# run and stored in the data dir unless one is provided explicitly.
SECRET_ENV = os.environ.get("ROADGUARD_SECRET")
TOKEN_TTL_HOURS = int(os.environ.get("ROADGUARD_TOKEN_TTL_HOURS", "12"))

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")

CORS_ORIGINS = os.environ.get("ROADGUARD_CORS", "http://localhost:3000,http://127.0.0.1:3000").split(",")


def ensure_dirs() -> None:
    for d in (DATA_DIR, EVIDENCE_DIR, UPLOAD_DIR, CAMERA_CONFIG_DIR):
        d.mkdir(parents=True, exist_ok=True)


def secret_key() -> bytes:
    if SECRET_ENV:
        return SECRET_ENV.encode()
    ensure_dirs()
    path = DATA_DIR / ".secret"
    if not path.exists():
        path.write_bytes(os.urandom(32).hex().encode())
    return path.read_bytes()
