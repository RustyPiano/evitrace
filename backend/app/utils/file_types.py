import mimetypes
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

    guessed_type, _ = mimetypes.guess_type(safe_name)
    actual_type = (content_type or guessed_type or "").split(";")[0].strip().lower()
    if actual_type == "application/octet-stream":
        actual_type = guessed_type or actual_type
    allowed_types = ALLOWED_MIME_TYPES[extension]
    if actual_type and actual_type not in allowed_types:
        raise unsupported_file_type()

    return safe_name, extension, SUPPORTED_EXTENSIONS[extension]
