import os
import sys
import tempfile
from pathlib import Path

# Isolate tests from the real data directory / database.
os.environ.setdefault("ROADGUARD_DATA", tempfile.mkdtemp(prefix="roadguard-test-"))
os.environ.setdefault("ROADGUARD_AUTH", "1")  # account tests exercise the login system (off by default in the app)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
