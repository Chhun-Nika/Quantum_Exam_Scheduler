from pathlib import Path

from fastapi import APIRouter

from backend.core.case import SchedulingCase

router = APIRouter(prefix="/api/cases", tags=["cases"])
EXAMPLE_PATH = Path(__file__).resolve().parents[2] / "data" / "example.json"


@router.get("/example", response_model_exclude_unset=True)
def get_example() -> SchedulingCase:
    """Return the shared example case used to verify local setup."""
    return SchedulingCase.model_validate_json(EXAMPLE_PATH.read_bytes())
