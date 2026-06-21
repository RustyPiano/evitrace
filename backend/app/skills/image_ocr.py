from pathlib import Path
from time import perf_counter
from typing import Any

from app.config import PROJECT_ROOT, settings

from .base import SkillContext, SkillManifest, SkillResult
from .utils import coerce_items, original_file_path, sidecar_fixture

_OCR_MODEL = None
NO_TEXT_WARNING = "OCR 未识别到文本"


def _bbox_from_points(points: list[Any]) -> list[int]:
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]


def _evidence_from_item(item: dict[str, Any], default_text: str = "") -> dict | None:
    text = str(item.get("text") or item.get("content") or default_text).strip()
    if not text:
        return None
    bbox = item.get("bbox") or [10, 10, 220, 60]
    return {
        "content": text,
        "modality": "image",
        "evidence_type": "ocr",
        "locator": {"kind": "image", "bbox": [int(value) for value in bbox]},
        "confidence": item.get("confidence"),
    }


def _default_items() -> list[dict[str, Any]]:
    return [{"text": "MOCK OCR 文本", "bbox": [10, 10, 220, 60], "confidence": 0.9}]


def resolve_ocr_model_dirs() -> dict[str, str]:
    if not settings.ocr_model_dir:
        raise RuntimeError("OCR_MODEL_DIR 未配置，真实 OCR 需要本地模型目录")

    model_root = Path(settings.ocr_model_dir).expanduser()
    if not model_root.is_absolute():
        model_root = PROJECT_ROOT / model_root
    model_root = model_root.resolve()
    if not model_root.is_dir():
        raise RuntimeError(f"OCR_MODEL_DIR 不存在: {model_root}")

    det_dir = model_root / "det"
    rec_dir = model_root / "rec"
    cls_dir = model_root / "cls"
    if not det_dir.is_dir() or not rec_dir.is_dir():
        raise RuntimeError("OCR_MODEL_DIR 必须包含 det/ 和 rec/ 本地模型目录")

    dirs = {"det_model_dir": str(det_dir), "rec_model_dir": str(rec_dir)}
    if cls_dir.is_dir():
        dirs["cls_model_dir"] = str(cls_dir)
    return dirs


def mock_ocr_evidence(context: SkillContext, file_info: dict[str, Any]) -> tuple[list[dict], list[str]]:
    fixture = sidecar_fixture(context, file_info, "ocr")
    raw_items = coerce_items(fixture, ("items", "boxes", "ocr"))
    if fixture is None:
        raw_items = _default_items()

    evidence = []
    for raw in raw_items:
        if isinstance(raw, dict):
            item = _evidence_from_item(raw)
            if item is not None:
                evidence.append(item)

    warnings = [NO_TEXT_WARNING] if not evidence else []
    return evidence, warnings


def real_ocr_evidence(path: Path) -> tuple[list[dict], list[str]]:
    global _OCR_MODEL
    if _OCR_MODEL is None:
        from paddleocr import PaddleOCR

        _OCR_MODEL = PaddleOCR(
            use_angle_cls=True,
            lang="ch",
            download_enable=False,
            **resolve_ocr_model_dirs(),
        )

    result = _OCR_MODEL.ocr(str(path), cls=True)
    rows = result[0] if result and isinstance(result[0], list) else result
    evidence: list[dict] = []
    for row in rows or []:
        try:
            points, text_info = row
            text, confidence = text_info
            item = _evidence_from_item(
                {
                    "text": text,
                    "bbox": _bbox_from_points(points),
                    "confidence": float(confidence),
                }
            )
        except Exception:
            item = None
        if item is not None:
            evidence.append(item)

    warnings = [NO_TEXT_WARNING] if not evidence else []
    return evidence, warnings


class ImageOcrSkill:
    manifest = SkillManifest(
        id="image_ocr",
        name="图片 OCR",
        version="1.0.0",
        description="解析 JPG 和 PNG 图片中的文字",
        enabled_by_default=True,
        required=False,
        input_types=["jpg", "jpeg", "png"],
        output_type="evidence_list",
    )

    def run(self, context: SkillContext, payload: Any) -> SkillResult:
        started = perf_counter()
        file_info = payload["file"]
        try:
            if settings.mock_ai:
                evidence, warnings = mock_ocr_evidence(context, file_info)
            else:
                evidence, warnings = real_ocr_evidence(original_file_path(context, file_info))
        except Exception as exc:
            return SkillResult(
                success=False,
                errors=[f"OCR 解析失败: {type(exc).__name__}: {exc}"],
                data={"evidence": []},
                metrics={"duration_ms": int((perf_counter() - started) * 1000)},
            )

        return SkillResult(
            success=True,
            warnings=warnings,
            data={"evidence": evidence},
            metrics={"duration_ms": int((perf_counter() - started) * 1000), "evidence_count": len(evidence)},
        )
