"""FastAPI application: GET /health and POST /api/v1/analyze."""

import json
import time
import uuid

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError

from lumi import __version__
from lumi.auth import ApiKeyAuthenticator
from lumi.config import CLINICAL_BOUNDARY_NOTICE, MULTIPART_OVERHEAD_BYTES, Settings
from lumi.errors import LumiError
from lumi.logging_config import configure_logging, log_analyze, log_rejected, logger
from lumi.ratelimit import RateLimiter
from lumi.schemas import AnalyzeResponse, ErrorCode, ErrorDetail, InputType, RequestMetadata
from lumi.service import AnalysisService, build_default_service
from lumi.validation import validate_upload


def _new_request_id() -> str:
    return uuid.uuid4().hex


def _error_response(
    status_code: int,
    error: ErrorDetail,
    request_id: str | None = None,
    input_type: InputType | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = AnalyzeResponse(
        request_id=request_id or _new_request_id(),
        input_type=input_type,
        clinical_boundary_notice=CLINICAL_BOUNDARY_NOTICE,
        error=error,
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"), headers=headers)


def _clean_question(question: str | None, settings: Settings) -> str | None:
    if question is None or not question.strip():
        return None
    question = question.strip()
    if len(question) > settings.max_question_chars:
        raise LumiError(
            422,
            ErrorCode.INVALID_FIELD,
            f"The question is longer than {settings.max_question_chars} characters.",
            field="question",
        )
    return question


def _parse_metadata(raw: str | None) -> RequestMetadata | None:
    if raw is None or not raw.strip():
        return None
    allowed = ", ".join(RequestMetadata.model_fields)
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("metadata must be a JSON object")
        return RequestMetadata.model_validate(parsed)
    except (ValueError, ValidationError) as exc:  # json.JSONDecodeError is a ValueError
        # Deliberately do not echo the submitted values back: they might be sensitive.
        raise LumiError(
            422,
            ErrorCode.INVALID_METADATA,
            f"metadata must be a JSON object containing only these optional keys: {allowed}.",
            field="metadata",
        ) from exc


def create_app(settings: Settings | None = None, service: AnalysisService | None = None) -> FastAPI:
    settings = settings or Settings()
    service = service or build_default_service(settings)
    authenticator = ApiKeyAuthenticator(settings.api_key_hashes)
    rate_limiter = RateLimiter(settings.rate_limit_per_minute)
    if not settings.api_key_hashes:
        logger.warning("No API keys configured (LUMI_API_KEYS); every /api request will be rejected with 401.")

    app = FastAPI(title="LUMI API", version=__version__)

    @app.middleware("http")
    async def reject_oversized_bodies(request: Request, call_next):
        # Rejects obviously oversized uploads from the Content-Length header, before the body is read.
        # Chunked uploads without Content-Length are still caught later by the per-file size check.
        length = request.headers.get("content-length", "")
        if (
            request.url.path.startswith("/api/")
            and length.isdigit()
            and int(length) > settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES
        ):
            log_rejected(path=request.url.path, status_code=413, error_code=ErrorCode.FILE_TOO_LARGE)
            error = ErrorDetail(
                code=ErrorCode.FILE_TOO_LARGE,
                message=f"The request body exceeds the {settings.max_upload_bytes} byte upload limit.",
            )
            return _error_response(413, error)
        return await call_next(request)

    @app.exception_handler(LumiError)
    async def handle_lumi_error(request: Request, exc: LumiError) -> JSONResponse:
        log_rejected(path=request.url.path, status_code=exc.status_code, error_code=exc.code)
        error = ErrorDetail(code=exc.code, message=exc.message, field=exc.field)
        return _error_response(exc.status_code, error, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0]
        field = str(first["loc"][-1]) if first.get("loc") else None
        if first.get("type") == "missing":
            error = ErrorDetail(code=ErrorCode.MISSING_FIELD, message=f"Required field '{field}' is missing.", field=field)
        elif field == "input_type":
            allowed = ", ".join(t.value for t in InputType)
            error = ErrorDetail(
                code=ErrorCode.INVALID_INPUT_TYPE, message=f"input_type must be one of: {allowed}.", field=field
            )
        else:
            error = ErrorDetail(code=ErrorCode.INVALID_FIELD, message=str(first.get("msg")), field=field)
        log_rejected(path=request.url.path, status_code=422, error_code=error.code)
        return _error_response(422, error)

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Log only the exception type: messages from parsers can contain fragments of the uploaded data.
        logger.error(json.dumps({"event": "internal_error", "path": request.url.path, "type": type(exc).__name__}))
        error = ErrorDetail(code=ErrorCode.INTERNAL_ERROR, message="An internal error occurred.")
        return _error_response(500, error)

    # HTTPBearer documents the scheme in OpenAPI, which adds the "Authorize" button to /docs.
    # auto_error=False lets our authenticator produce the standard LUMI 401 envelope.
    bearer = HTTPBearer(auto_error=False, description="LUMI API key")

    def require_client(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
        header = f"{credentials.scheme} {credentials.credentials}" if credentials else None
        client_id = authenticator.authenticate(header)
        rate_limiter.check(client_id)
        return client_id

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "lumi", "version": __version__}

    @app.post("/api/v1/analyze", response_model=AnalyzeResponse)
    async def analyze(
        input_type: InputType = Form(...),
        file: UploadFile = File(...),
        question: str | None = Form(None),
        metadata: str | None = Form(None),
        client_id: str = Depends(require_client),
    ):
        request_id = _new_request_id()
        started = time.perf_counter()
        try:
            clean_question = _clean_question(question, settings)
            parsed_metadata = _parse_metadata(metadata)
            # Read at most one byte over the limit, enough to know the file is too large.
            data = await file.read(settings.max_upload_bytes + 1)
            validated = validate_upload(input_type, data, file.content_type, file.filename, settings)
            # Pipelines may also raise LumiError (e.g. OCR engine unavailable -> 503).
            response = service.analyze(request_id, input_type, validated, clean_question, parsed_metadata)
        except LumiError as exc:
            log_analyze(
                request_id=request_id,
                client_id=client_id,
                input_type=input_type,
                status_code=exc.status_code,
                started=started,
                error_code=exc.code,
            )
            error = ErrorDetail(code=exc.code, message=exc.message, field=exc.field)
            return _error_response(
                exc.status_code, error, request_id=request_id, input_type=input_type, headers=exc.headers
            )

        log_analyze(
            request_id=request_id,
            client_id=client_id,
            input_type=input_type,
            status_code=200,
            started=started,
            mime_type=validated.mime_type,
            file_bytes=len(validated.data),
            has_question=clean_question is not None,
        )
        return response

    return app


def _build_runtime_app() -> FastAPI:
    configure_logging()
    return create_app(Settings.from_env())


app = _build_runtime_app()
