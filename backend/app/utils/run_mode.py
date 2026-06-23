from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.config import settings

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"}


def _mode_label(mode: str) -> str:
    labels = {
        "real": "全真实链路",
        "mock": "演示Fixture",
        "hybrid": "混合模式",
    }
    return labels[mode]


def _deployment_from_url(base_url: str | None) -> str | None:
    if not base_url:
        return None
    hostname = urlparse(base_url).hostname
    if not hostname:
        return None
    return "local" if hostname in LOCAL_HOSTS else "remote"


def _media_source(real: bool, base_url: str | None) -> str:
    if not real:
        return "fixture"
    return "http" if base_url else "lib"


def _media_deployment(real: bool, base_url: str | None) -> str | None:
    if not real:
        return None
    return _deployment_from_url(base_url) if base_url else "local"


def _deployment_mode(deployments: list[str | None]) -> str | None:
    real_deployments = {deployment for deployment in deployments if deployment is not None}
    if not real_deployments:
        return None
    if real_deployments == {"local"}:
        return "local"
    if real_deployments == {"remote"}:
        return "remote"
    return "mixed"


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
    llm_deployment = _deployment_from_url(settings.local_llm_base_url) if llm_real else None
    vision_deployment = _deployment_from_url(settings.vlm_base_url) if vision_real else None
    ocr_deployment = _media_deployment(media_real, settings.ocr_base_url)
    asr_deployment = _media_deployment(media_real, settings.asr_base_url)

    return {
        "mode": mode,
        "execution_mode": mode,
        "mode_label": _mode_label(mode),
        "deployment_mode": _deployment_mode(
            [llm_deployment, vision_deployment, ocr_deployment, asr_deployment]
        ),
        "mock_llm": mock_llm,
        "mock_media": mock_media,
        "mock_vision": mock_vision,
        "llm": {
            "real": llm_real,
            "model": settings.local_llm_model if llm_real else None,
            "deployment": llm_deployment,
        },
        "vision": {
            "real": vision_real,
            "model": settings.vlm_model if vision_real else None,
            "deployment": vision_deployment,
        },
        "ocr": {
            "real": media_real,
            "source": _media_source(media_real, settings.ocr_base_url),
            "deployment": ocr_deployment,
        },
        "asr": {
            "real": media_real,
            "source": _media_source(media_real, settings.asr_base_url),
            "deployment": asr_deployment,
        },
        "skills": _skills_metadata(),
    }
