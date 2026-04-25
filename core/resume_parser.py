"""
Resume PDF parsing utilities.

Extracts plain text from an uploaded resume PDF using pdfplumber. Designed to
fail soft — callers can decide whether to abort the upload or continue with an
empty text body (the entry-level flow intentionally continues and falls back
to generic questions for the chosen career field).
"""
from __future__ import annotations

import io
import logging
from typing import Optional

import pdfplumber

logger = logging.getLogger("resume_parser")

# Keep resumes modest — 5 MB is plenty for a real-world PDF resume.
MAX_RESUME_BYTES = 5 * 1024 * 1024

# A resume with fewer than ~80 characters of extracted text is almost
# certainly a scan/image-only PDF or a corrupted file. We treat these as
# "not helpful" rather than rejecting them outright.
MIN_USEFUL_TEXT_LEN = 80


class ResumeParseError(Exception):
    """Raised when a PDF cannot be opened or contains no extractable text."""


def parse_pdf_bytes(data: bytes) -> str:
    """Extract concatenated text from a PDF byte blob.

    Raises ``ResumeParseError`` if the bytes are not a valid PDF. Returns the
    stripped text otherwise — callers should check ``is_text_useful`` before
    assuming the resume is informative.
    """
    if not data:
        raise ResumeParseError("Resume file is empty.")

    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages_text = []
            for page in pdf.pages:
                extracted = page.extract_text() or ""
                if extracted:
                    pages_text.append(extracted)
    except Exception as exc:  # pdfplumber surfaces PDFSyntaxError, etc.
        logger.warning("Failed to parse resume PDF: %s", exc)
        raise ResumeParseError(f"Could not read PDF: {exc}") from exc

    return "\n".join(pages_text).strip()


def is_text_useful(text: Optional[str]) -> bool:
    """Return True when the extracted text has enough signal for the LLM."""
    return bool(text) and len(text.strip()) >= MIN_USEFUL_TEXT_LEN


def validate_resume_upload(filename: str, content_type: str, size: int) -> None:
    """Validate client-provided file metadata. Raises ``ResumeParseError``."""
    if size <= 0:
        raise ResumeParseError("Resume file is empty.")
    if size > MAX_RESUME_BYTES:
        raise ResumeParseError(
            f"Resume is too large ({size} bytes). Maximum is {MAX_RESUME_BYTES} bytes."
        )
    lower_name = (filename or "").lower()
    allowed_types = {"application/pdf", "application/x-pdf"}
    if content_type not in allowed_types and not lower_name.endswith(".pdf"):
        raise ResumeParseError("Only PDF resumes are supported.")
