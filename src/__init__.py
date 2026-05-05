"""Package init.

Loading .env here (rather than only in src.settings) means any code path
that touches `src.*` — including `from src.tools.bq import ...` — gets
GOOGLE_APPLICATION_CREDENTIALS, GOOGLE_API_KEY, etc. set on os.environ
before any third-party SDK constructor runs. This is what tools like
google-cloud-bigquery actually need.
"""
from pathlib import Path

from dotenv import load_dotenv

# Repo-root .env (one level up from this file's parent).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
