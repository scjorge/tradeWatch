from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.deps import SAFE_METHODS, require_module
from app.core.errors import install_error_handlers
from app.core.logging import setup_logging
from app.core.origins import origin_allowed
from app.db import get_db
from app.models import WorkerHeartbeat
from app.models.base import utcnow
from app.modules.registry import REGISTRY

log = logging.getLogger("app.main")


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)
    app = FastAPI(
        title="TradeWatch API",
        version="0.1.0",
        description="API interna do TradeWatch (somente leitura nas corretoras).",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    install_error_handlers(app)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        # Bloqueia envios de formulários cross-site (text/plain, urlencoded) em rotas que alteram estado.
        if request.method not in SAFE_METHODS and request.url.path.startswith("/api/"):
            ctype = request.headers.get("content-type", "")
            if ctype and not ctype.startswith("application/json"):
                return JSONResponse({"error": {"code": "unsupported_media_type", "message": "Content-Type não suportado."}}, status_code=415)
            origin = request.headers.get("origin")
            if not origin_allowed(origin, request.headers.get("host"), request.url.scheme, settings.app_base_url, settings.allowed_origins):
                log.warning("bad_origin", extra={"origin": origin, "host": request.headers.get("host"), "path": request.url.path})
                return JSONResponse(
                    {"error": {"code": "bad_origin", "message": "Origem não permitida. Acesse pelo endereço configurado em APP_BASE_URL ou inclua-o em ALLOWED_ORIGINS."}},
                    status_code=403,
                )
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    for spec in REGISTRY:
        deps = [] if spec.core else [Depends(require_module(spec.key))]
        for r in spec.routers:
            app.include_router(r, dependencies=deps)

    @app.get("/api/health/live", tags=["health"])
    def live():
        return {"status": "ok"}

    @app.get("/api/health/ready", tags=["health"])
    def ready(db: Session = Depends(get_db)):
        checks = {"api": "ok"}
        try:
            db.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception:  # noqa: BLE001
            checks["database"] = "error"
        try:
            hb = db.scalars(select(WorkerHeartbeat).order_by(WorkerHeartbeat.last_seen.desc()).limit(1)).first()
            checks["worker"] = "ok" if hb and utcnow() - hb.last_seen < timedelta(minutes=2) else "stale"
            checks["worker_last_seen"] = hb.last_seen.isoformat() if hb else None
        except Exception:  # noqa: BLE001
            checks["worker"] = "unknown"
        healthy = checks["database"] == "ok"
        return JSONResponse({"status": "ok" if healthy else "degraded", "checks": checks}, status_code=200 if healthy else 503)

    return app


app = create_app()
