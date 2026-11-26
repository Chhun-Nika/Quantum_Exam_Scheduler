import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(prefix="/api/cases", tags=["cases"])
EXAMPLE_PATH = Path(__file__).resolve().parents[2] / "data" / "example.json"


@router.get("/example")
def get_example() -> dict:
    """Return the shared example case used to verify local setup."""
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
