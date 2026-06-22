from typing import Any

from fastapi import APIRouter, Depends, status

from app.dependencies import get_current_user
from app.models import User
from app.utils.run_mode import run_mode_metadata

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/mode", status_code=status.HTTP_200_OK)
def mode(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    return {"data": run_mode_metadata(), "message": "ok"}
