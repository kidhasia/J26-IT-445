"""FastAPI application: GET /health and POST /api/v1/analyze."""

import json
import time
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError

from lumi import __version__
from lumi.auth import ApiKeyAuthenticator
from lumi.config import CLINICAL_BOUNDARY_NOTICE, MULTIPART_OVERHEAD_BYTES, Settings
from lumi.errors import LumiError
from lumi.logging_config import configure_logging, log_analyze, log_ask, log_rag, log_rejected, logger
from lumi.qa.answerer import answer_question
from lumi.qa.evidence import EvidenceError, parse_evidence
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


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAG_PATH = "/api/v1/rag-demo"
RAG_MAX_BODY_BYTES = 4_096  # one short question
RAG_MAX_QUESTION_CHARS = 300
RAG_WARNINGS = [
    "PROJECT_DOCUMENTS_ONLY: the passages come from LUMI's own project documents. They are not an approved medical "
    "knowledge base and are not medical advice.",
    "EXTRACTIVE_PROTOTYPE: the passages are quoted word for word by a keyword search. No language model wrote or checked "
    "this answer, and the search has not been evaluated.",
]
RAG_NOTE_REFUSED_PERSONAL = (
    "This demo searches project documents only. It does not answer questions about a person's own health, diagnosis or treatment."
)
RAG_NOTE_REFUSED_WEAK = "No passage in the project documents matched the question well enough to answer it."
ASK_PATH = "/api/v1/ask"
ASK_MAX_BODY_BYTES = 300_000  # a question plus one analysis result; far smaller than an image upload
ASK_MAX_QUESTION_CHARS = 500
ASK_EVIDENCE_WARNING = (
    "EVIDENCE_NOT_VERIFIED: the answer comes only from the evidence you supplied. LUMI did not check that it is "
    "genuine or unchanged."
)
ASK_OPENAPI = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "required": ["question", "evidence"],
                    "additionalProperties": False,
                    "properties": {
                        "question": {"type": "string", "minLength": 1, "maxLength": ASK_MAX_QUESTION_CHARS},
                        "evidence": {"type": "object", "description": "The JSON that POST /api/v1/analyze returned for a skin photo or a lab report."},
                    },
                }
            }
        },
    }
}


async def _read_limited_body(request: Request, limit: int) -> bytes:
    """Read the request body but stop as soon as it is larger than `limit` (also catches chunked uploads)."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise LumiError(413, ErrorCode.FILE_TOO_LARGE, f"The request body exceeds the {limit} byte limit for questions.")
        chunks.append(chunk)
    return b"".join(chunks)


def _parse_ask_body(body: bytes) -> tuple[str, object]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise LumiError(422, ErrorCode.INVALID_FIELD, "The request body is not valid JSON.", field="body") from exc
    if not isinstance(payload, dict):
        raise LumiError(422, ErrorCode.INVALID_FIELD, "The request body must be a JSON object.", field="body")
    unexpected = sorted(set(payload) - {"question", "evidence"})
    if unexpected:
        raise LumiError(422, ErrorCode.INVALID_FIELD, "Only 'question' and 'evidence' are allowed.", field=str(unexpected[0])[:40])
    for name in ("question", "evidence"):
        if name not in payload:
            raise LumiError(422, ErrorCode.MISSING_FIELD, f"Required field '{name}' is missing.", field=name)
    question = payload["question"]
    if not isinstance(question, str):
        raise LumiError(422, ErrorCode.INVALID_FIELD, "The question must be text.", field="question")
    question = question.strip()
    if not question:
        raise LumiError(422, ErrorCode.INVALID_FIELD, "The question is empty.", field="question")
    if len(question) > ASK_MAX_QUESTION_CHARS:
        raise LumiError(422, ErrorCode.INVALID_FIELD, f"The question is longer than {ASK_MAX_QUESTION_CHARS} characters.", field="question")
    if any(ord(ch) < 32 and ch not in "\t\n\r" for ch in question):
        raise LumiError(422, ErrorCode.INVALID_FIELD, "The question contains control characters.", field="question")
    return question, payload["evidence"]


def _parse_rag_body(body: bytes) -> str:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise LumiError(422, ErrorCode.INVALID_FIELD, "The request body is not valid JSON.", field="body") from exc
    if not isinstance(payload, dict):
        raise LumiError(422, ErrorCode.INVALID_FIELD, "The request body must be a JSON object.", field="body")
    unexpected = sorted(set(payload) - {"question"})
    if unexpected:
        raise LumiError(422, ErrorCode.INVALID_FIELD, "Only 'question' is allowed.", field=str(unexpected[0])[:40])
    if "question" not in payload:
        raise LumiError(422, ErrorCode.MISSING_FIELD, "Required field 'question' is missing.", field="question")
    question = payload["question"]
    if not isinstance(question, str):
        raise LumiError(422, ErrorCode.INVALID_FIELD, "The question must be text.", field="question")
    question = question.strip()
    if not question:
        raise LumiError(422, ErrorCode.INVALID_FIELD, "The question is empty.", field="question")
    if len(question) > RAG_MAX_QUESTION_CHARS:
        raise LumiError(422, ErrorCode.INVALID_FIELD, f"The question is longer than {RAG_MAX_QUESTION_CHARS} characters.", field="question")
    if any(ord(ch) < 32 and ch not in "\t\n\r" for ch in question):
        raise LumiError(422, ErrorCode.INVALID_FIELD, "The question contains control characters.", field="question")
    return question


def _load_rag(settings: Settings):
    """Build the retriever once at start-up. Returns (retriever or None, corpus or None). Never raises: a broken corpus
    switches the feature to 'unavailable' (503) and leaves everything else working."""
    try:
        from lumi.rag.corpus import load_corpus
        from lumi.rag.retrieve import Retriever

        manifest = Path(settings.rag_manifest)
        corpus = load_corpus(manifest if manifest.is_absolute() else PROJECT_ROOT / manifest)
        return Retriever(corpus), corpus
    except Exception as exc:  # noqa: BLE001  (CorpusError, or a library problem; the type is logged, never the message)
        logger.error(json.dumps({"event": "rag_corpus_load_failed", "type": type(exc).__name__}))
        return None, None


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
        small_limits = {ASK_PATH: ASK_MAX_BODY_BYTES, RAG_PATH: RAG_MAX_BODY_BYTES}
        limit = small_limits.get(request.url.path, settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES)
        if request.url.path.startswith("/api/") and length.isdigit() and int(length) > limit:
            log_rejected(path=request.url.path, status_code=413, error_code=ErrorCode.FILE_TOO_LARGE)
            error = ErrorDetail(
                code=ErrorCode.FILE_TOO_LARGE,
                message=f"The request body exceeds the {limit if request.url.path in small_limits else settings.max_upload_bytes} byte limit.",
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

    rag_retriever, rag_corpus = _load_rag(settings) if settings.rag_demo else (None, None)

    @app.get("/health")
    def health() -> dict:
        # pipelines: per input type, "ready", "placeholder" (no real analysis) or "unavailable" (model not set up).
        # models: facts about any trained model that is loaded (name, training run, held-out score), for the About page.
        body = {
            "status": "ok",
            "service": "lumi",
            "version": __version__,
            "pipelines": service.statuses(),
            "models": service.model_summaries(),
        }
        if settings.rag_demo:  # this key exists only while the demo is switched on
            body["reference_search"] = {"status": "ready" if rag_retriever else "unavailable",
                                        "documents": len(rag_corpus.documents) if rag_corpus else 0,
                                        "passages": len(rag_corpus.passages) if rag_corpus else 0}
        return body

    if settings.demo_ui:
        from fastapi.responses import HTMLResponse, RedirectResponse, Response

        from lumi.demo_ui import ASSET_HEADERS, DEMO_PAGE_HEADERS, read_asset, render_demo_page

        @app.get("/", include_in_schema=False)
        def root() -> RedirectResponse:
            return RedirectResponse("/demo")

        @app.get("/demo", include_in_schema=False)
        def demo() -> HTMLResponse:
            return HTMLResponse(render_demo_page(settings.demo_ui_key), headers=DEMO_PAGE_HEADERS)

        @app.get("/demo/assets/{name}", include_in_schema=False)
        def demo_asset(name: str) -> Response:
            asset = read_asset(name)  # only allow-listed file names; anything else is a plain 404
            if asset is None:
                return Response("Not found", status_code=404, media_type="text/plain")
            content, media_type = asset
            return Response(content, media_type=media_type, headers=ASSET_HEADERS)

    @app.post("/api/v1/analyze", response_model=AnalyzeResponse)
    async def analyze(
        input_type: InputType = Form(...),
        file: UploadFile = File(...),
        question: str | None = Form(None),
        metadata: str | None = Form(None),
        explain: bool = Form(False),
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
            response = service.analyze(request_id, input_type, validated, clean_question, parsed_metadata, explain)
        except LumiError as exc:
            log_analyze(
                request_id=request_id,
                client_id=client_id,
                input_type=input_type,
                status_code=exc.status_code,
                started=started,
                error_code=exc.code,
                explain=explain,
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
            explain=explain,
        )
        return response

    @app.post(ASK_PATH, response_model=AnalyzeResponse, openapi_extra=ASK_OPENAPI)
    async def ask(request: Request, client_id: str = Depends(require_client)):
        """Answer a simple factual question using ONLY the analysis result you supply as evidence.

        Not a medical chatbot: no model, no network, nothing stored. Anything the evidence cannot answer (and any request
        for a diagnosis, advice, or whether a result is normal) gets: "I cannot answer this from the available evidence."
        """
        request_id = _new_request_id()
        started = time.perf_counter()
        input_type_seen: str | None = None
        try:
            if not request.headers.get("content-type", "").lower().startswith("application/json"):
                raise LumiError(415, ErrorCode.UNSUPPORTED_MEDIA_TYPE, "Send the question as JSON (Content-Type: application/json).")
            question, raw_evidence = _parse_ask_body(await _read_limited_body(request, ASK_MAX_BODY_BYTES))
            try:
                evidence = parse_evidence(raw_evidence)
            except EvidenceError as exc:
                raise LumiError(422, ErrorCode.INVALID_EVIDENCE, exc.message, field="evidence") from exc
            input_type_seen = evidence.input_type
            answer = answer_question(question, evidence)
        except LumiError as exc:
            log_ask(request_id=request_id, client_id=client_id, status_code=exc.status_code, started=started, error_code=exc.code, input_type=input_type_seen)
            error = ErrorDetail(code=exc.code, message=exc.message, field=exc.field)
            return _error_response(exc.status_code, error, request_id=request_id, headers=exc.headers)

        log_ask(request_id=request_id, client_id=client_id, status_code=200, started=started, input_type=input_type_seen,
                intents=answer.intents, answerable=answer.answerable)
        return AnalyzeResponse(
            request_id=request_id,
            input_type=InputType(evidence.input_type),
            result={"mode": "evidence_grounded_qa", "answerable": answer.answerable, "intents": answer.intents, "evidence_used": answer.evidence_used},
            answer=answer.text,
            explanation=answer.note,
            warnings=[ASK_EVIDENCE_WARNING],
            clinical_boundary_notice=CLINICAL_BOUNDARY_NOTICE,
        )

    if settings.rag_demo:
        from lumi.rag.retrieve import CANNOT_ANSWER, compose_answer, is_personal_medical_question

        @app.post(RAG_PATH, response_model=AnalyzeResponse, openapi_extra={"requestBody": {"required": True, "content": {"application/json": {"schema": {
            "type": "object", "required": ["question"], "additionalProperties": False,
            "properties": {"question": {"type": "string", "minLength": 1, "maxLength": RAG_MAX_QUESTION_CHARS}}}}}}})
        async def rag_demo(request: Request, client_id: str = Depends(require_client)):
            """Extractive retrieval demo: quotes the best-matching passages from LUMI's own project documents, with citations.

            Not a medical chatbot and not generative: no language model, no network, nothing stored. Questions about a
            person's health, and questions the documents do not cover, get: "I cannot answer this from the available evidence."
            """
            request_id = _new_request_id()
            started = time.perf_counter()
            try:
                if rag_retriever is None:
                    raise LumiError(503, ErrorCode.REFERENCE_UNAVAILABLE, "The reference documents are not available on this server, so nothing was searched.")
                if not request.headers.get("content-type", "").lower().startswith("application/json"):
                    raise LumiError(415, ErrorCode.UNSUPPORTED_MEDIA_TYPE, "Send the question as JSON (Content-Type: application/json).")
                question = _parse_rag_body(await _read_limited_body(request, RAG_MAX_BODY_BYTES))
            except LumiError as exc:
                log_rag(request_id=request_id, client_id=client_id, status_code=exc.status_code, started=started, error_code=exc.code)
                error = ErrorDetail(code=exc.code, message=exc.message, field=exc.field)
                return _error_response(exc.status_code, error, request_id=request_id, headers=exc.headers)

            refusal_reason = None
            hits = []
            if is_personal_medical_question(question):
                refusal_reason = "personal_medical_question"
            else:
                hits = rag_retriever.search(question)
                if not hits:
                    refusal_reason = "insufficient_evidence"
            sources = []
            for number, hit in enumerate(hits, start=1):
                info = next(d for d in rag_corpus.documents if d.doc_id == hit.passage.doc_id)
                sources.append({
                    "citation": f"R{number}", "doc_id": info.doc_id, "title": info.title, "section": hit.passage.section,
                    "passage_id": hit.passage.passage_id, "lines": f"{hit.passage.line_start}-{hit.passage.line_end}",
                    "path": info.path, "source_sha256": info.sha256, "source_type": info.source_type,
                    "approved_for_medical_use": info.approved_for_medical_use, "score": hit.score,
                    "query_coverage": hit.coverage, "excerpt": hit.excerpt, "excerpt_truncated": hit.truncated,
                })
            answerable = refusal_reason is None
            log_rag(request_id=request_id, client_id=client_id, status_code=200, started=started, answerable=answerable,
                    sources=len(sources), refusal_reason=refusal_reason)
            return AnalyzeResponse(
                request_id=request_id,
                input_type=None,
                result={"mode": "extractive_retrieval_demo", "answerable": answerable, "refusal_reason": refusal_reason,
                        "corpus": {"kind": "LUMI project documents (not an approved medical knowledge base)", "documents": len(rag_corpus.documents)},
                        "sources": sources},
                answer=compose_answer(hits) if answerable else CANNOT_ANSWER,
                explanation=None if answerable else (RAG_NOTE_REFUSED_PERSONAL if refusal_reason == "personal_medical_question" else RAG_NOTE_REFUSED_WEAK),
                warnings=list(RAG_WARNINGS),
                clinical_boundary_notice=CLINICAL_BOUNDARY_NOTICE,
            )

    return app


def _build_runtime_app() -> FastAPI:
    configure_logging()
    return create_app(Settings.from_env())


app = _build_runtime_app()
