#!/usr/bin/env python
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings  # noqa: E402
from app.database import SessionLocal, initialize_database  # noqa: E402
from app.services.auth_service import seed_default_admin  # noqa: E402


def main() -> None:
    initialize_database()
    with SessionLocal() as db:
        seed_default_admin(db, reset_password=True)
    print(f"Seeded admin user: {settings.first_admin_username}")


if __name__ == "__main__":
    main()
