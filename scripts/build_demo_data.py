#!/usr/bin/env python3
"""Generate deterministic EviTrace M5 demo cases."""

from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

import fitz
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DEMO_ROOT = ROOT / "demo_data"
SAMPLE_RATE = 16_000
MEDIA_SECONDS = 8


@dataclass(frozen=True)
class DemoCase:
    directory: str
    title: str
    conflict_type: str
    expected_left: str
    expected_right: str
    event_key: str
    left_fact: dict
    right_fact: dict
    brief_text: str
    report_text: str
    image_text: str
    audio_text: str
    video_audio_text: str
    video_frame_text: str
    readme: str


def fact_event(fact: dict, match: str, confidence: float = 0.88) -> dict:
    return {
        "event_key": fact["event_key"],
        "title": fact["title"],
        "subject": fact["subject"],
        "action": fact["action"],
        "object": fact["object"],
        "time_text": fact["time_text"],
        "time_normalized": fact["time_normalized"],
        "location": fact["location"],
        "quantity": {"value": fact["quantity_value"], "unit": fact["quantity_unit"]},
        "match": match,
        "confidence": confidence,
    }


def cases() -> list[DemoCase]:
    case_01_left = {
        "event_key": "Delta-convoy-check-in",
        "title": "Delta convoy checkpoint report",
        "subject": "Delta convoy",
        "action": "checked in",
        "object": "checkpoint",
        "time_text": "14:00",
        "time_normalized": "2026-06-01T14:00:00",
        "location": "Harbor Gate",
        "quantity_value": 3,
        "quantity_unit": "vehicles",
    }
    case_01_right = {
        **case_01_left,
        "time_text": "16:30",
        "time_normalized": "2026-06-01T16:30:00",
    }

    case_02_left = {
        "event_key": "Echo-team-delivery",
        "title": "Echo team delivery point",
        "subject": "Echo team",
        "action": "delivered",
        "object": "medical crates",
        "time_text": "09:15",
        "time_normalized": "2026-06-02T09:15:00",
        "location": "North Pier",
        "quantity_value": 2,
        "quantity_unit": "crates",
    }
    case_02_right = {
        **case_02_left,
        "location": "East Warehouse",
    }

    case_03_left = {
        "event_key": "Foxtrot-patrol-vehicle-count",
        "title": "Foxtrot patrol vehicle count",
        "subject": "Foxtrot patrol",
        "action": "counted",
        "object": "utility vehicles",
        "time_text": "11:20",
        "time_normalized": "2026-06-03T11:20:00",
        "location": "Training Yard",
        "quantity_value": 3,
        "quantity_unit": "vehicles",
    }
    case_03_right = {
        **case_03_left,
        "quantity_value": 5,
    }

    return [
        DemoCase(
            directory="case_01_time_conflict",
            title="Case 01 Time Conflict",
            conflict_type="time",
            expected_left="14:00",
            expected_right="16:30",
            event_key=case_01_left["event_key"],
            left_fact=case_01_left,
            right_fact=case_01_right,
            brief_text=(
                "Brief note: Delta convoy checked in at 14:00 at Harbor Gate with 3 vehicles.\n\n"
                "This fictional training note is intentionally short for evidence tracing."
            ),
            report_text=(
                "Report check: Delta checkpoint remained listed as 14:00 in the duty roster.\n\n"
                "The report adds a second parsed text source for the same side of the planted conflict."
            ),
            image_text="Board text: Delta check-in 14:00, Harbor Gate, 3 vehicles.",
            audio_text="Radio transcript: Delta check-in was actually 16:30 at Harbor Gate with 3 vehicles.",
            video_audio_text="Video audio: Delta convoy check-in time is 16:30 at Harbor Gate.",
            video_frame_text="Video slate shows Delta check-in 16:30.",
            readme=(
                "This case plants a time conflict. Text and image evidence say 14:00; "
                "audio and video evidence say 16:30. Other fields are held constant."
            ),
        ),
        DemoCase(
            directory="case_02_location_conflict",
            title="Case 02 Location Conflict",
            conflict_type="location",
            expected_left="North Pier",
            expected_right="East Warehouse",
            event_key=case_02_left["event_key"],
            left_fact=case_02_left,
            right_fact=case_02_right,
            brief_text=(
                "Brief note: Echo team delivered 2 medical crates at North Pier at 09:15.\n\n"
                "The note is fictional and exists only for deterministic testing."
            ),
            report_text=(
                "Report check: The logistics sheet repeats North Pier as the delivery point.\n\n"
                "The time and quantity match all other sources."
            ),
            image_text="Gate sign: Echo team delivery point East Warehouse, 2 crates, 09:15.",
            audio_text="Radio transcript: Echo team confirms North Pier delivery point at 09:15.",
            video_audio_text="Video audio: Echo team delivery point is East Warehouse.",
            video_frame_text="Video slate shows East Warehouse for Echo team.",
            readme=(
                "This case plants a location conflict. Text and audio evidence say North Pier; "
                "image and video evidence say East Warehouse. Time and quantity are stable."
            ),
        ),
        DemoCase(
            directory="case_03_quantity_conflict",
            title="Case 03 Quantity Conflict",
            conflict_type="quantity",
            expected_left="3 vehicles",
            expected_right="5 vehicles",
            event_key=case_03_left["event_key"],
            left_fact=case_03_left,
            right_fact=case_03_right,
            brief_text=(
                "Brief note: Foxtrot patrol counted 3 utility vehicles at Training Yard at 11:20.\n\n"
                "The location and time are stable across the fictional materials."
            ),
            report_text=(
                "Report check: The maintenance summary also records three vehicles for Foxtrot patrol.\n\n"
                "The conflicting count is planted in generated mock media transcripts."
            ),
            image_text="Whiteboard: Foxtrot patrol count 3 vehicles at Training Yard.",
            audio_text="Radio transcript: Foxtrot patrol counted 5 vehicles at Training Yard.",
            video_audio_text="Video audio: Foxtrot patrol count is 5 vehicles.",
            video_frame_text="Video slate shows Foxtrot count 5 vehicles.",
            readme=(
                "This case plants a quantity conflict. Text and image evidence say 3 vehicles; "
                "audio and video evidence say 5 vehicles. Time and location are stable."
            ),
        ),
    ]


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def wrapped_lines(text: str, max_chars: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > max_chars and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def write_png(path: Path, title: str, body: str) -> None:
    image = Image.new("RGB", (1000, 520), color=(242, 246, 250))
    draw = ImageDraw.Draw(image)
    title_font = font(40)
    body_font = font(30)
    small_font = font(22)
    draw.rectangle((32, 32, 968, 488), outline=(29, 78, 126), width=4)
    draw.text((60, 58), title, fill=(16, 42, 67), font=title_font)
    y = 136
    for line in wrapped_lines(body, 44):
        draw.text((60, y), line, fill=(31, 41, 55), font=body_font)
        y += 46
    draw.text((60, 430), "Synthetic M5 demo image", fill=(71, 85, 105), font=small_font)
    image.save(path, format="PNG")


def write_pdf(path: Path, title: str, body: str) -> None:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 84), title, fontsize=18, fontname="helv")
    page.insert_textbox(
        fitz.Rect(72, 128, 523, 760),
        body,
        fontsize=12,
        fontname="helv",
        lineheight=1.25,
    )
    document.save(path)
    document.close()


def write_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        for index in range(SAMPLE_RATE * MEDIA_SECONDS):
            value = int(1400 * math.sin(2 * math.pi * 440 * index / SAMPLE_RATE))
            output.writeframesraw(struct.pack("<h", value))


def write_video(path: Path, title: str, frame_text: str) -> str | None:
    if shutil.which("ffmpeg") is None:
        return "ffmpeg unavailable; skipped video.mp4"

    with TemporaryDirectory() as tmpdir:
        frame_path = Path(tmpdir) / "frame.png"
        write_png(frame_path, title, frame_text)
        command = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-loop",
            "1",
            "-i",
            str(frame_path),
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=channel_layout=mono:sample_rate={SAMPLE_RATE}",
            "-t",
            str(MEDIA_SECONDS),
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(path),
        ]
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            return f"ffmpeg failed for {path}: {completed.stderr.strip()}"
    return None


def write_case(case: DemoCase) -> list[str]:
    case_dir = DEMO_ROOT / case.directory
    case_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []

    (case_dir / "brief.txt").write_text(case.brief_text + "\n", encoding="utf-8")
    write_pdf(case_dir / "report.pdf", case.title, case.report_text)
    write_png(case_dir / "image.png", case.title, case.image_text)
    write_wav(case_dir / "audio.wav")
    video_warning = write_video(case_dir / "video.mp4", case.title, case.video_frame_text)
    if video_warning:
        warnings.append(video_warning)

    write_json(
        case_dir / "image.ocr.json",
        {
            "items": [
                {
                    "text": case.image_text,
                    "bbox": [56, 132, 920, 238],
                    "confidence": 0.94,
                }
            ]
        },
    )
    write_json(
        case_dir / "audio.asr.json",
        {
            "segments": [
                {
                    "text": case.audio_text,
                    "start_ms": 1200,
                    "end_ms": 5200,
                    "confidence": 0.91,
                }
            ]
        },
    )
    write_json(
        case_dir / "video.video.json",
        {
            "audio_segments": [
                {
                    "text": case.video_audio_text,
                    "start_ms": 800,
                    "end_ms": 4800,
                    "confidence": 0.9,
                }
            ],
            "frames": [
                {
                    "text": case.video_frame_text,
                    "timestamp_ms": 2000,
                    "bbox": [54, 118, 910, 226],
                    "confidence": 0.93,
                }
            ],
        },
    )

    events = [
        fact_event(case.left_fact, case.brief_text.split(".")[0]),
        fact_event(case.left_fact, case.report_text.split(".")[0]),
        fact_event(case.left_fact, case.image_text),
        fact_event(case.right_fact, case.audio_text),
        fact_event(case.right_fact, case.video_audio_text),
        fact_event(case.right_fact, case.video_frame_text),
    ]
    entities = [
        {"type": "location", "name": case.left_fact["location"], "match": case.left_fact["location"], "confidence": 0.86},
        {
            "type": "quantity",
            "name": f"{case.left_fact['quantity_value']:g} {case.left_fact['quantity_unit']}",
            "match": f"{case.left_fact['quantity_value']:g}",
            "confidence": 0.84,
        },
    ]
    if case.right_fact["location"] != case.left_fact["location"]:
        entities.append(
            {
                "type": "location",
                "name": case.right_fact["location"],
                "match": case.right_fact["location"],
                "confidence": 0.86,
            }
        )
    if case.right_fact["quantity_value"] != case.left_fact["quantity_value"]:
        entities.append(
            {
                "type": "quantity",
                "name": f"{case.right_fact['quantity_value']:g} {case.right_fact['quantity_unit']}",
                "match": f"{case.right_fact['quantity_value']:g}",
                "confidence": 0.84,
            }
        )
    write_json(case_dir / "extraction.json", {"entities": entities, "events": events})
    write_json(
        case_dir / "expected.json",
        {
            "expected_entities": [],
            "expected_events": [],
            "expected_conflicts": [
                {
                    "type": case.conflict_type,
                    "left": case.expected_left,
                    "right": case.expected_right,
                }
            ],
            "required_evidence_modalities": ["text", "image", "audio", "video"],
        },
    )
    (case_dir / "README.md").write_text(
        "\n".join(
            [
                f"# {case.title}",
                "",
                case.readme,
                "",
                "Files:",
                "- `brief.txt` and `report.pdf`: parsed by the real document parser.",
                "- `image.png`, `audio.wav`, `video.mp4`: real uploadable media files.",
                "- `image.ocr.json`, `audio.asr.json`, `video.video.json`: MOCK media sidecars.",
                "- `extraction.json`: deterministic MOCK extraction with `match` references.",
                "- `expected.json`: evaluator labels.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return warnings


def main() -> int:
    DEMO_ROOT.mkdir(parents=True, exist_ok=True)
    all_warnings: list[str] = []
    generated_files: list[Path] = []
    for case in cases():
        warnings = write_case(case)
        all_warnings.extend(warnings)
        generated_files.extend(sorted((DEMO_ROOT / case.directory).iterdir()))

    print(f"Generated {len(cases())} demo cases in {DEMO_ROOT}")
    for path in generated_files:
        print(f"- {path.relative_to(ROOT)}")
    if all_warnings:
        print("Warnings:")
        for warning in all_warnings:
            print(f"- {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
