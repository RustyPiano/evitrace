import json
from pathlib import Path
from typing import Any

from app.schemas import AppError
from fastapi import status

from .base import SkillContext


def task_directory(context: SkillContext) -> Path:
    return (Path(context.data_root) / "tasks" / context.task_id).resolve()


def original_file_path(context: SkillContext, file_info: dict[str, Any]) -> Path:
    root = task_directory(context)
    path = (root / "original" / file_info["stored_name"]).resolve()
    if not path.is_relative_to(root):
        raise AppError("FORBIDDEN", "文件路径非法", status.HTTP_403_FORBIDDEN)
    return path


def derived_path(context: SkillContext, relative_path: str) -> Path:
    root = task_directory(context)
    path = (root / relative_path).resolve()
    if not path.is_relative_to(root):
        raise AppError("FORBIDDEN", "文件路径非法", status.HTTP_403_FORBIDDEN)
    return path


def ensure_derived_dir(context: SkillContext, name: str) -> Path:
    directory = derived_path(context, f"derived/{name}")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def sidecar_fixture(
    context: SkillContext,
    file_info: dict[str, Any],
    suffix: str,
) -> dict[str, Any] | list[Any] | None:
    original_dir = task_directory(context) / "original"
    stored_name = file_info["stored_name"]
    original_name = file_info["original_name"]
    original_path = Path(original_name)
    candidates = [
        original_dir / f"{stored_name}.mock.json",
        original_dir / f"{stored_name}.{suffix}.json",
        original_dir / f"{original_name}.mock.json",
        original_dir / f"{original_name}.{suffix}.json",
        original_dir / f"{original_path.stem}.{suffix}.json",
    ]
    for candidate in candidates:
        path = candidate.resolve()
        if not path.is_relative_to(task_directory(context)):
            continue
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    return None


def coerce_items(fixture: dict[str, Any] | list[Any] | None, keys: tuple[str, ...]) -> list[Any]:
    if fixture is None:
        return []
    if isinstance(fixture, list):
        return fixture
    for key in keys:
        value = fixture.get(key)
        if isinstance(value, list):
            return value
    return []
