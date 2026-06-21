import re
from pathlib import PurePosixPath

from fastapi import status

from app.schemas import AppError

SUPPORTED_EXTENSIONS = {
    "txt": "text",
    "md": "text",
    "pdf": "document",
    "docx": "document",
    "jpg": "image",
    "jpeg": "image",
    "png": "image",
    "wav": "audio",
    "mp3": "audio",
    "m4a": "audio",
    "mp4": "video",
}

BLOCKED_EXTENSIONS = {
    "bat",
    "cmd",
    "com",
    "dll",
    "exe",
    "js",
    "msi",
    "ps1",
    "scr",
    "sh",
    "vbs",
}

ALLOWED_MIME_TYPES = {
    "txt": {"text/plain"},
    "md": {"text/markdown", "text/plain", "text/x-markdown"},
    "pdf": {"application/pdf"},
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    "jpg": {"image/jpeg"},
    "jpeg": {"image/jpeg"},
    "png": {"image/png"},
    "wav": {"audio/wav", "audio/wave", "audio/x-wav", "audio/vnd.wave"},
    "mp3": {"audio/mpeg", "audio/mp3", "audio/x-mpeg"},
    "m4a": {"audio/mp4", "audio/x-m4a", "audio/mp4a-latm"},
    "mp4": {"video/mp4", "application/mp4"},
}

GENERIC_MIME_TYPES = {"", "application/octet-stream"}
HEADER_READ_BYTES = 64 * 1024


def unsupported_file_type() -> AppError:
    return AppError(
        "FILE_TYPE_NOT_SUPPORTED",
        "文件格式不支持",
        status.HTTP_400_BAD_REQUEST,
    )


def sanitize_filename(filename: str | None) -> str:
    raw_name = (filename or "upload").replace("\\", "/")
    name = PurePosixPath(raw_name).name
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    return name or "upload"


def _normalized_content_type(content_type: str | None) -> str:
    return (content_type or "").split(";")[0].strip().lower()


def validate_upload_type(filename: str | None, content_type: str | None) -> tuple[str, str, str]:
    safe_name = sanitize_filename(filename)
    suffixes = [suffix.lower().lstrip(".") for suffix in PurePosixPath(safe_name).suffixes]
    if not suffixes:
        raise unsupported_file_type()

    extension = suffixes[-1]
    if extension not in SUPPORTED_EXTENSIONS:
        raise unsupported_file_type()
    if any(suffix in BLOCKED_EXTENSIONS for suffix in suffixes):
        raise unsupported_file_type()

    actual_type = _normalized_content_type(content_type)
    allowed_types = ALLOWED_MIME_TYPES[extension]
    if actual_type not in GENERIC_MIME_TYPES and actual_type not in allowed_types:
        raise unsupported_file_type()

    return safe_name, extension, SUPPORTED_EXTENSIONS[extension]


def _is_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _has_mp4_ftyp(data: bytes) -> bool:
    return len(data) >= 12 and data[4:8] == b"ftyp"


def validate_file_signature(extension: str, data: bytes) -> None:
    valid = False
    if extension in {"txt", "md"}:
        valid = _is_text(data)
    elif extension == "pdf":
        valid = data.startswith(b"%PDF-")
    elif extension == "png":
        valid = data.startswith(b"\x89PNG")
    elif extension in {"jpg", "jpeg"}:
        valid = data.startswith(b"\xff\xd8\xff")
    elif extension == "wav":
        valid = len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WAVE"
    elif extension == "mp4":
        valid = _has_mp4_ftyp(data)
    elif extension == "docx":
        valid = (
            data.startswith(b"PK\x03\x04")
            and b"[Content_Types].xml" in data
            and b"word/" in data
        )
    elif extension == "mp3":
        valid = data.startswith(b"ID3") or (
            len(data) >= 2 and data[0] == 0xFF and data[1] in {0xFB, 0xF3, 0xF2}
        )
    elif extension == "m4a":
        valid = _has_mp4_ftyp(data)

    if not valid:
        raise unsupported_file_type()
