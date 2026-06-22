from pathlib import Path
from typing import Iterable

from app.config import settings

MAX_HEALTH_DETAIL_LENGTH = 160


def _sensitive_values() -> Iterable[tuple[str, str]]:
    values = [
        ("[data-root]", str(settings.data_root_path)),
        ("[secret]", settings.secret_key),
        ("[llm-base-url]", settings.local_llm_base_url),
    ]
    if settings.vlm_base_url:
        values.append(("[vlm-base-url]", settings.vlm_base_url))
    if settings.ocr_base_url:
        values.append(("[ocr-base-url]", settings.ocr_base_url))
    if settings.asr_base_url:
        values.append(("[asr-base-url]", settings.asr_base_url))
    if settings.local_llm_api_key and settings.local_llm_api_key != "local":
        values.append(("[llm-api-key]", settings.local_llm_api_key))
    if settings.vlm_api_key:
        values.append(("[vlm-api-key]", settings.vlm_api_key))
    for label, raw in (("[ocr-model-dir]", settings.ocr_model_dir), ("[asr-model-dir]", settings.asr_model_dir)):
        if raw:
            path = Path(raw).expanduser()
            values.append((label, str(path)))
            values.append((label, str(path.resolve())))
    return values


def redact_health_detail(value: object) -> str:
    text = str(value or "unavailable")
    for label, sensitive in _sensitive_values():
        if sensitive:
            text = text.replace(sensitive, label)
    return text[:MAX_HEALTH_DETAIL_LENGTH]


def public_health_detail(value: object) -> str:
    text = redact_health_detail(value)
    lowered = text.lower()
    if (
        "ocr_model_dir" in lowered
        or "asr_model_dir" in lowered
        or "model directory" in lowered
        or "模型目录" in text
        or "[ocr-model-dir]" in text
        or "[asr-model-dir]" in text
    ):
        return "模型目录未就绪"
    if "missing dependency" in lowered or "dependency not installed" in lowered:
        return "依赖未安装"
    if "ffmpeg" in lowered or "missing executable" in lowered:
        return "FFmpeg 不可用"
    if (
        "vlm_base_url" in lowered
        or "vlm_model" in lowered
        or "vlm_api_key" in lowered
        or "vlm configuration" in lowered
        or "vlm 配置" in text
    ):
        return "VLM 配置未就绪"
    return text
