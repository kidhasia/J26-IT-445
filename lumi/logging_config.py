"""Request logging that never records health data (FR11).

Allowed in logs: request_id, client_id, input_type, HTTP status, error code, MIME type,
file size, whether a question was present, latency.
Never logged: file contents, filenames, question text, metadata values.
"""

import json
import logging
import time

from lumi.schemas import ErrorCode, InputType

logger = logging.getLogger("lumi")


def configure_logging(level: int = logging.INFO) -> None:
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(level)


def log_analyze(
    *,
    request_id: str,
    client_id: str,
    input_type: InputType,
    status_code: int,
    started: float,
    error_code: ErrorCode | None = None,
    mime_type: str | None = None,
    file_bytes: int | None = None,
    has_question: bool | None = None,
    explain: bool | None = None,
) -> None:
    record = {
        "event": "analyze",
        "request_id": request_id,
        "client_id": client_id,
        "input_type": input_type.value,
        "status": status_code,
        "error_code": error_code.value if error_code else None,
        "mime_type": mime_type,
        "file_bytes": file_bytes,
        "has_question": has_question,
        "explain_requested": explain,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    logger.info(json.dumps(record))


def log_ask(
    *,
    request_id: str,
    client_id: str,
    status_code: int,
    started: float,
    error_code: ErrorCode | None = None,
    input_type: str | None = None,
    intents: list[str] | None = None,
    answerable: bool | None = None,
) -> None:
    """One line per question. The question, the evidence and the answer are never logged; `intents` are internal topic
    labels such as "lab.row" or "skin.predicted_class"."""
    record = {
        "event": "ask",
        "request_id": request_id,
        "client_id": client_id,
        "input_type": input_type,
        "status": status_code,
        "error_code": error_code.value if error_code else None,
        "answerable": answerable,
        "intents": intents,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    logger.info(json.dumps(record))


def log_rag(
    *,
    request_id: str,
    client_id: str,
    status_code: int,
    started: float,
    error_code: ErrorCode | None = None,
    answerable: bool | None = None,
    sources: int | None = None,
    refusal_reason: str | None = None,
) -> None:
    """One line per reference-search request: counts and labels only. Never the question, the passages or the answer."""
    record = {
        "event": "rag_demo",
        "request_id": request_id,
        "client_id": client_id,
        "status": status_code,
        "error_code": error_code.value if error_code else None,
        "answerable": answerable,
        "sources": sources,
        "refusal_reason": refusal_reason,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    logger.info(json.dumps(record))


def log_rejected(*, path: str, status_code: int, error_code: ErrorCode) -> None:
    logger.info(json.dumps({"event": "rejected", "path": path, "status": status_code, "error_code": error_code.value}))
