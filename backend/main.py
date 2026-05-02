import urllib3
from contextlib import asynccontextmanager
import logging
from pathlib import Path
from threading import Thread
import sys

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from database import create_db_and_tables, get_pool_status
from routers import admin, agent_workflow, ai_director, assistant, auth, canvas, channel, creative_center, director_agent, external_agent, gen, generate, openclaw_api, panel, project_workspace, provider_callbacks, resource, script, sluvo, tasks, team, user
from services.generation_record_service import repair_generation_record_previews
from services.openclaw_catalog_service import render_openclaw_skill_markdown
from services.temp_media_service import start_temporary_upload_cleanup_loop

urllib3.util.connection.HAS_IPV6 = False


class _SuppressCreativeRecordsAccessFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        if '"GET /api/creative/records' in message and '" 200' in message:
            return False
        return True


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_db_and_tables()
    Thread(target=repair_generation_record_previews, kwargs={"batch_size": 100, "max_batches": 20}, daemon=True).start()
    Thread(target=start_temporary_upload_cleanup_loop, kwargs={"interval_seconds": 600, "batch_size": 100}, daemon=True).start()
    yield


app = FastAPI(lifespan=lifespan)

logging.getLogger("uvicorn.access").addFilter(_SuppressCreativeRecordsAccessFilter())
logger = logging.getLogger(__name__)

ALLOWED_CORS_ORIGINS = [
    "https://ai.shenlu.top",
    "https://api.shenlu.top",
    "https://shenlu.top",
    "https://admin.shenlu.top",
    "https://sluvo.shenlu.top",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:9000",
    "http://127.0.0.1:9000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(user.router)
app.include_router(script.router)
app.include_router(canvas.router)
app.include_router(panel.router)
app.include_router(generate.router)
app.include_router(admin.router)
app.include_router(channel.router)
app.include_router(ai_director.router)
app.include_router(resource.router)
app.include_router(project_workspace.router)
app.include_router(team.router)
app.include_router(external_agent.router)
app.include_router(openclaw_api.router)
app.include_router(creative_center.router)
app.include_router(tasks.router)
app.include_router(sluvo.router)
app.include_router(gen.router)
app.include_router(provider_callbacks.router)
app.include_router(agent_workflow.router)
app.include_router(assistant.router, prefix="/api/assistant", tags=["assistant"])
app.include_router(director_agent.router, prefix="/api/director-agent", tags=["director-agent"])


def _is_productized_api_path(path: str) -> bool:
    path_text = str(path or "")
    return path_text.startswith("/api/openclaw/") or path_text.startswith("/api/creative/")


def _build_productized_error(status_code: int, detail):
    if isinstance(detail, dict) and detail.get("success") is False and detail.get("error"):
        payload = dict(detail)
        payload.setdefault("retryable", status_code >= 500)
        return JSONResponse(status_code=status_code, content=payload)

    error = "generation_failed" if status_code >= 500 else "invalid_request"
    message = "请求失败，请稍后重试"
    retryable = status_code >= 500
    field = None

    if isinstance(detail, dict):
        error = str(detail.get("error") or detail.get("code") or error)
        message = str(detail.get("message") or detail.get("detail") or message)
        retryable = bool(detail.get("retryable", retryable))
        field = detail.get("field")
    elif isinstance(detail, str) and detail.strip():
        message = detail
        if status_code == 401:
            error = "token_invalid"
        elif status_code == 403:
            error = "permission_denied"
        elif status_code == 404:
            error = "record_not_found"

    payload = {
        "success": False,
        "error": error,
        "message": message,
        "retryable": retryable,
    }
    if field:
        payload["field"] = field
    return JSONResponse(status_code=status_code, content=payload)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if _is_productized_api_path(request.url.path):
        return _build_productized_error(exc.status_code, exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    if _is_productized_api_path(request.url.path):
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": "invalid_request",
                "message": "请求参数不合法，请检查后重试",
                "retryable": False,
                "details": exc.errors(),
            },
        )
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.exception_handler(SQLAlchemyTimeoutError)
async def sqlalchemy_timeout_exception_handler(request: Request, exc: SQLAlchemyTimeoutError):
    logger.error(
        "database connection pool timeout path=%s pool=%s error=%s",
        request.url.path,
        get_pool_status(),
        exc,
    )
    if _is_productized_api_path(request.url.path):
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "error": "db_pool_timeout",
                "message": "数据库连接繁忙，请稍后重试",
                "retryable": True,
            },
        )
    return JSONResponse(
        status_code=503,
        content={
            "detail": "数据库连接繁忙，请稍后重试",
            "code": "db_pool_timeout",
            "retryable": True,
        },
    )


@app.get("/skill.md", response_class=PlainTextResponse)
def get_public_skill_markdown(request: Request):
    base_url = str(request.base_url).rstrip("/")
    return PlainTextResponse(
        render_openclaw_skill_markdown(base_url=base_url),
        media_type="text/plain; charset=utf-8",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
