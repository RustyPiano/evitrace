from fastapi import APIRouter, Depends

from app.dependencies import require_admin
from app.models import User

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/health")
def admin_health(_: User = Depends(require_admin)) -> dict:
    return {"data": {"status": "ok"}, "message": "ok"}
