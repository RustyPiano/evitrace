from __future__ import annotations

from typing import Any

from app.config import settings


def _mode_label(mode: str) -> str:
    labels = {
        "real": "本地真实",
        "mock": "演示Fixture",
        "hybrid": "混合模式",
    }
    return labels[mode]


def _media_source(real: bool, base_url: str | None) -> str:
    if not real:
        return "fixture"
    return "http" if base_url else "lib"


def _skills_metadata() -> list[dict[str, str]]:
    from app.skills.registry import SKILL_REGISTRY

    return [
        {
            "id": manifest.id,
            "name": manifest.name,
            "version": manifest.version,
        }
        for manifest in (skill.manifest for skill in SKILL_REGISTRY.values())
    ]


def run_mode_metadata() -> dict[str, Any]:
    mock_llm = settings.effective_mock_llm
    mock_media = settings.effective_mock_media
    mock_vision = settings.effective_mock_vision

    if mock_llm and mock_media and mock_vision:
        mode = "mock"
    elif not mock_llm and not mock_media and not mock_vision:
        mode = "real"
    else:
        mode = "hybrid"

    llm_real = not mock_llm
    vision_real = not mock_vision
    media_real = not mock_media

    return {
        "mode": mode,
        "mode_label": _mode_label(mode),
        "mock_llm": mock_llm,
        "mock_media": mock_media,
        "mock_vision": mock_vision,
        "llm": {
            "real": llm_real,
            "model": settings.local_llm_model if llm_real else None,
        },
        "vision": {
            "real": vision_real,
            "model": settings.vlm_model if vision_real else None,
        },
        "ocr": {
            "real": media_real,
            "source": _media_source(media_real, settings.ocr_base_url),
        },
        "asr": {
            "real": media_real,
            "source": _media_source(media_real, settings.asr_base_url),
        },
        "skills": _skills_metadata(),
    }
