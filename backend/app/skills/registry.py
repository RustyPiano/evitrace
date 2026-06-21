from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.constants import SKILL_STATUS_UNKNOWN
from app.models import SkillConfig


@dataclass(frozen=True)
class SkillManifest:
    id: str
    name: str
    version: str
    description: str
    enabled_by_default: bool
    required: bool
    input_types: list[str]
    output_type: str


SKILL_MANIFESTS = [
    SkillManifest(
        id="document_parse",
        name="文档解析",
        version="1.0.0",
        description="解析 TXT、MD、PDF 和 DOCX，并生成文本证据",
        enabled_by_default=True,
        required=False,
        input_types=["txt", "md", "pdf", "docx"],
        output_type="evidence_list",
    ),
    SkillManifest(
        id="image_ocr",
        name="图片 OCR",
        version="1.0.0",
        description="解析 JPG 和 PNG 图片中的文字",
        enabled_by_default=True,
        required=False,
        input_types=["jpg", "jpeg", "png"],
        output_type="evidence_list",
    ),
    SkillManifest(
        id="audio_transcribe",
        name="音频转写",
        version="1.0.0",
        description="转写 WAV、MP3 和 M4A 音频",
        enabled_by_default=True,
        required=False,
        input_types=["wav", "mp3", "m4a"],
        output_type="evidence_list",
    ),
    SkillManifest(
        id="video_parse",
        name="视频解析",
        version="1.0.0",
        description="解析 MP4 音轨和关键帧",
        enabled_by_default=True,
        required=False,
        input_types=["mp4"],
        output_type="evidence_list",
    ),
    SkillManifest(
        id="intelligence_extract",
        name="要素事件提取",
        version="1.0.0",
        description="从证据列表提取实体、事件和时间线",
        enabled_by_default=True,
        required=True,
        input_types=["evidence_list"],
        output_type="analysis_entities_events",
    ),
    SkillManifest(
        id="conflict_detect",
        name="冲突检测",
        version="1.0.0",
        description="检测时间、地点和数量冲突",
        enabled_by_default=True,
        required=True,
        input_types=["events"],
        output_type="conflict_list",
    ),
    SkillManifest(
        id="report_generate",
        name="报告生成与引用验证",
        version="1.0.0",
        description="生成 Markdown 报告并验证证据引用",
        enabled_by_default=True,
        required=True,
        input_types=["analysis_results"],
        output_type="report_markdown",
    ),
]


def sync_skill_configs(db: Session) -> None:
    for manifest in SKILL_MANIFESTS:
        existing = db.get(SkillConfig, manifest.id)
        if existing is None:
            db.add(
                SkillConfig(
                    skill_id=manifest.id,
                    name=manifest.name,
                    version=manifest.version,
                    enabled=manifest.enabled_by_default,
                    required=manifest.required,
                    last_status=SKILL_STATUS_UNKNOWN,
                )
            )
            continue

        existing.name = manifest.name
        existing.version = manifest.version
        existing.required = manifest.required

    db.commit()
