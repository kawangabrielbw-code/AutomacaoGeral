from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from src.engine.execution_history import ExecutionHistory
from webapp.services import (FREQUENCIES, ROOT, catalog_rows, execute_scheduler_action,
    operations, save_frequency, scheduler_dry_run, scheduler_status, source_history)
from src.engine.google_sheets_exporter import GoogleSheetsExporter, ExportError
from webapp.security import valid_hash, verify_password

logger = logging.getLogger("oppes.web")
export_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="oppes-export")
export_guard = threading.Lock()
active_export_id: Optional[str] = None
WEB_DIR = Path(__file__).resolve().parent
SESSION_SECRET = os.environ.get("OPPES_SESSION_SECRET") or secrets.token_urlsafe(48)
ADMIN_PASSWORD_HASH = os.environ.get("OPPES_ADMIN_PASSWORD_HASH", "")
app = FastAPI(title="OPPES | Observatório de Diadema", docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, session_cookie="oppes_session",
                   max_age=8 * 60 * 60, same_site="strict", https_only=False)
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
templates = Jinja2Templates(directory=WEB_DIR / "templates")
history = ExecutionHistory(ROOT / "data/history")
login_attempts: dict[str, list[float]] = {}


@app.on_event("startup")
async def verify_security_configuration() -> None:
    if not valid_hash(ADMIN_PASSWORD_HASH):
        raise RuntimeError("Configure OPPES_ADMIN_PASSWORD_HASH com um hash PBKDF2 gerado por scripts/gerar_hash_senha.py.")
    if len(os.environ.get("OPPES_SESSION_SECRET", "")) < 40:
        raise RuntimeError("Configure OPPES_SESSION_SECRET com pelo menos 40 caracteres aleatórios.")
    history.interrupt_open_web_operations()
    GoogleSheetsExporter(ROOT)
    db = sqlite3.connect(ROOT / "data/history/historico.sqlite3", timeout=30)
    try:
        db.execute("UPDATE export_jobs SET status='INTERROMPIDA',fim_utc=?,mensagem='Servidor reiniciado antes de concluir.' WHERE status='EM_ANDAMENTO'",
                   (datetime.now(timezone.utc).isoformat(),))
        db.commit()
    finally:
        db.close()


@app.middleware("http")
async def security_headers(request: Request, call_next):
    client = request.client.host if request.client else ""
    if client not in {"127.0.0.1", "::1", "testclient"} and request.url.scheme != "https":
        response = JSONResponse({"detail": "Acesso remoto exige HTTPS. Configure TLS no servidor."}, status_code=426)
    else:
        response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
    response.headers["Cache-Control"] = "no-store"
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=86400"
        cookies = response.headers.getlist("set-cookie")
        if cookies:
            del response.headers["set-cookie"]
            for cookie in cookies:
                response.headers.append("set-cookie", cookie + ("; Secure" if "; Secure" not in cookie else ""))
    return response


def require_auth(request: Request) -> None:
    if request.session.get("authenticated") is not True:
        raise HTTPException(401, "Autenticação necessária.")


def check_csrf(request: Request, supplied: Optional[str]) -> None:
    expected = request.session.get("csrf")
    if not expected or not supplied or not hmac.compare_digest(str(expected), str(supplied)):
        raise HTTPException(403, "Token CSRF inválido ou ausente.")


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


class LoginPayload(BaseModel):
    password: str = Field(min_length=1, max_length=512)


class OperationPayload(BaseModel):
    operation: str
    source_id: Optional[str] = Field(default=None, max_length=220)
    confirm: bool = False


class FrequencyPayload(BaseModel):
    frequency: str
    periodicity_source: Optional[str] = Field(default=None, max_length=240)


class SchedulePayload(BaseModel):
    action: str
    frequency: str = "weekly"
    time: str = "06:00"
    confirm: bool = False


class DryRunPayload(BaseModel):
    action: str
    frequency: str = "weekly"
    time: str = "06:00"


class ExportPayload(BaseModel):
    source_ids: list[str] = Field(default_factory=list, max_length=150)
    all: bool = False
    confirm: bool = False


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if not request.session.get("csrf"):
        request.session["csrf"] = secrets.token_urlsafe(32)
    return templates.TemplateResponse(request, "login.html", {})


@app.get("/api/session")
async def get_session(request: Request):
    if not request.session.get("csrf"):
        request.session["csrf"] = secrets.token_urlsafe(32)
    return {"authenticated": request.session.get("authenticated") is True,
            "csrf_token": request.session["csrf"]}


@app.post("/api/login")
async def login(payload: LoginPayload, request: Request, x_csrf_token: Optional[str] = Header(default=None)):
    check_csrf(request, x_csrf_token)
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    attempts = [t for t in login_attempts.get(ip, []) if now - t < 900]
    if len(attempts) >= 5:
        raise HTTPException(429, "Muitas tentativas. Aguarde 15 minutos.")
    if not verify_password(payload.password, ADMIN_PASSWORD_HASH):
        attempts.append(now)
        login_attempts[ip] = attempts
        raise HTTPException(401, "Senha inválida.")
    login_attempts.pop(ip, None)
    request.session.clear()
    request.session.update({"authenticated": True, "csrf": secrets.token_urlsafe(32)})
    return {"authenticated": True, "csrf_token": request.session["csrf"]}


@app.post("/api/logout")
async def logout(request: Request, x_csrf_token: Optional[str] = Header(default=None)):
    require_auth(request)
    check_csrf(request, x_csrf_token)
    request.session.clear()
    return {"authenticated": False}


@app.get("/api/dashboard")
async def dashboard(request: Request):
    require_auth(request)
    sources = catalog_rows(history)
    records = history.get_records()
    jobs = history.get_web_operations(30)
    counts = Counter(row["status"] for row in sources)
    trend: dict[str, dict[str, int]] = {}
    for row in records:
        day = str(row.get("data_fim_utc", ""))[:10]
        if not day:
            continue
        cell = trend.setdefault(day, {"success": 0, "failure": 0})
        if row.get("status") in {"SUCESSO", "VAZIO"}:
            cell["success"] += 1
        elif str(row.get("status", "")).startswith(("FALHA", "REQUER_AUTENTICACAO")):
            cell["failure"] += 1
    latest = records[-1] if records else None
    return {"total_sources": len(sources), "counts": dict(counts),
            "last_execution": latest, "active_operation": operations.active(),
            "recent_operations": jobs[:10],
            "trend": [{"date": d, **trend[d]} for d in sorted(trend)[-30:]],
            "schedule": scheduler_status()}


@app.get("/api/sources")
async def list_sources(request: Request, search: str = "", type: str = "", status: str = "",
                       page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)):
    require_auth(request)
    rows = catalog_rows(history)
    term = search.casefold().strip()
    if term:
        rows = [r for r in rows if term in " ".join(str(r.get(k) or "") for k in ("id", "name", "dashboard", "url")).casefold()]
    if type:
        rows = [r for r in rows if r["type"] == type]
    if status:
        rows = [r for r in rows if r["status"] == status]
    total = len(rows)
    start = (page - 1) * page_size
    return {"items": rows[start:start + page_size], "total": total, "page": page, "page_size": page_size}


@app.get("/api/exports")
async def export_status(request: Request):
    require_auth(request)
    exporter = GoogleSheetsExporter(ROOT)
    status = exporter.status()
    sources = catalog_rows(history)
    exported = set(status["latest"])
    status["sources"] = [{"id": s["id"], "name": s["name"], "type": s["type"], "status": s["status"],
                          "last_success": s["last_success"], "csv_path": s["csv_path"],
                          "export": status["latest"].get(s["id"])} for s in sources]
    status["exported_count"] = sum(1 for sid in exported if status["latest"][sid].get("resultado") == "SUCESSO")
    db = sqlite3.connect(ROOT / "data/history/historico.sqlite3", timeout=30)
    try:
        db.row_factory = sqlite3.Row
        job = db.execute("SELECT id,status,total,completed,inicio_utc FROM export_jobs WHERE status='EM_ANDAMENTO' ORDER BY inicio_utc DESC LIMIT 1").fetchone()
        status["active_job"] = dict(job) if job else None
    finally:
        db.close()
    return status


@app.post("/api/exports/test")
async def test_export_connection(request: Request, x_csrf_token: Optional[str] = Header(default=None)):
    require_auth(request)
    check_csrf(request, x_csrf_token)
    try:
        return GoogleSheetsExporter(ROOT).test_connection()
    except ExportError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/api/exports")
async def export_sources(payload: ExportPayload, request: Request,
                         x_csrf_token: Optional[str] = Header(default=None)):
    require_auth(request)
    check_csrf(request, x_csrf_token)
    if operations.active():
        raise HTTPException(409, "Aguarde o fim da coleta atual antes de exportar snapshots locais.")
    exporter = GoogleSheetsExporter(ROOT)
    if payload.all and not payload.confirm:
        raise HTTPException(400, "Confirme explicitamente a exportação geral.")
    if payload.all and not payload.source_ids:
        selected = list(exporter._sources())
    elif payload.source_ids:
        selected = list(dict.fromkeys(payload.source_ids))
    else:
        raise HTTPException(422, "Selecione ao menos uma fonte ou confirme a exportação geral.")
    if len(selected) > 150:
        raise HTTPException(422, "A exportação aceita no máximo 150 fontes por solicitação.")
    if not exporter.configured:
        raise HTTPException(503, exporter.status()["message"])
    allowed = exporter._sources()
    if any(sid not in allowed for sid in selected):
        raise HTTPException(422, "A seleção contém fonte fora do catálogo cadastrado.")
    global active_export_id
    with export_guard:
        if active_export_id:
            raise HTTPException(409, "Uma exportação já está em andamento.")
        job_id = str(uuid.uuid4())
        active_export_id = job_id
        db = sqlite3.connect(ROOT / "data/history/historico.sqlite3", timeout=30)
        try:
            db.execute("""CREATE TABLE IF NOT EXISTS export_jobs (
                id TEXT PRIMARY KEY, status TEXT NOT NULL, total INTEGER NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0, inicio_utc TEXT NOT NULL,
                fim_utc TEXT, resultado_json TEXT, mensagem TEXT)""")
            db.execute("INSERT INTO export_jobs(id,status,total,inicio_utc) VALUES(?,?,?,?)",
                       (job_id, "EM_ANDAMENTO", len(selected), datetime.now(timezone.utc).isoformat()))
            db.commit()
        finally:
            db.close()
        export_executor.submit(_execute_export_job, job_id, selected)
    return {"id": job_id, "status": "EM_ANDAMENTO", "total": len(selected), "completed": 0}


def _execute_export_job(job_id: str, source_ids: list[str]) -> None:
    global active_export_id
    results = []
    try:
        exporter = GoogleSheetsExporter(ROOT)
        for source_id in source_ids:
            results.append(exporter.export(source_id))
            db = sqlite3.connect(ROOT / "data/history/historico.sqlite3", timeout=30)
            try:
                db.execute("UPDATE export_jobs SET completed=?,resultado_json=? WHERE id=?",
                           (len(results), json.dumps(results, ensure_ascii=False), job_id))
                db.commit()
            finally:
                db.close()
        status = "SUCESSO" if all(r["status"] == "SUCESSO" for r in results) else "PARCIAL"
        error = None
    except Exception as exc:
        status, error = "FALHA", str(exc)[:500]
    db = sqlite3.connect(ROOT / "data/history/historico.sqlite3", timeout=30)
    try:
        db.execute("UPDATE export_jobs SET status=?,fim_utc=?,resultado_json=?,mensagem=? WHERE id=?",
                   (status, datetime.now(timezone.utc).isoformat(), json.dumps(results, ensure_ascii=False), error, job_id))
        db.commit()
    finally:
        db.close()
    with export_guard:
        if active_export_id == job_id:
            active_export_id = None


@app.get("/api/exports/jobs/{job_id}")
async def export_job_status(job_id: str, request: Request):
    require_auth(request)
    try:
        uuid.UUID(job_id)
    except ValueError as exc:
        raise HTTPException(422, "Identificador de exportação inválido.") from exc
    db = sqlite3.connect(ROOT / "data/history/historico.sqlite3", timeout=30)
    try:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM export_jobs WHERE id=?", (job_id,)).fetchone()
    finally:
        db.close()
    if not row:
        raise HTTPException(404, "Exportação não encontrada.")
    result = dict(row)
    result["items"] = json.loads(result.pop("resultado_json") or "[]")
    result["success"] = sum(x.get("status") == "SUCESSO" for x in result["items"])
    result["failed"] = sum(x.get("status") != "SUCESSO" for x in result["items"])
    return result


@app.get("/api/sources/{source_id:path}")
async def source_detail(source_id: str, request: Request):
    require_auth(request)
    row = next((item for item in catalog_rows(history) if item["id"] == source_id), None)
    if not row:
        raise HTTPException(404, "Fonte não encontrada.")
    attempts = source_history(source_id, history)
    latest_export = GoogleSheetsExporter(ROOT).status()["latest"].get(source_id)
    csv_path = Path(row.get("csv_path") or "")
    try:
        csv_relative = csv_path.resolve().relative_to((ROOT / "data/raw").resolve()).as_posix()
    except (OSError, ValueError):
        csv_relative = None
    row["storage"] = {"origin": row.get("url"), "local_csv": csv_relative,
        "sqlite_database": "data/history/historico.sqlite3",
        "execution_id": attempts[-1].get("execucao_id") if attempts else None,
        "central_sheet": latest_export.get("sheet_title") if latest_export else None,
        "last_export": latest_export}
    return {"source": row, "history": attempts}


@app.patch("/api/sources/{source_id:path}/frequency")
async def update_frequency(source_id: str, payload: FrequencyPayload, request: Request,
                           x_csrf_token: Optional[str] = Header(default=None)):
    require_auth(request)
    check_csrf(request, x_csrf_token)
    try:
        result = save_frequency(source_id, payload.frequency, payload.periodicity_source)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except OSError as exc:
        logger.exception("Falha ao persistir periodicidade da fonte %s", source_id)
        raise HTTPException(503, "Não foi possível salvar a configuração no disco.") from exc
    return {**result, "next_run": result["next_run"].isoformat() if result["next_run"] else None}


@app.get("/api/history")
async def list_history(request: Request, source_id: str = "", source_type: str = "", status: str = "",
                       date_from: str = "", date_to: str = "", page: int = Query(1, ge=1),
                       page_size: int = Query(50, ge=1, le=200)):
    require_auth(request)
    for value in (date_from, date_to):
        if value:
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError as exc:
                raise HTTPException(422, "Datas devem estar no formato AAAA-MM-DD.") from exc
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "A data inicial deve ser anterior ou igual à data final.")
    rows = history.get_records()
    if source_id:
        rows = [r for r in rows if r.get("fonte_id") == source_id]
    if source_type:
        rows = [r for r in rows if r.get("fonte_tipo") == source_type]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if date_from:
        rows = [r for r in rows if r.get("data_fim_utc", "")[:10] >= date_from]
    if date_to:
        rows = [r for r in rows if r.get("data_fim_utc", "")[:10] <= date_to]
    rows.reverse()
    total = len(rows)
    start = (page - 1) * page_size
    return {"items": rows[start:start + page_size], "total": total, "page": page, "page_size": page_size,
            "operations": history.get_web_operations(50)}


@app.post("/api/operations")
async def start_operation(payload: OperationPayload, request: Request,
                          x_csrf_token: Optional[str] = Header(default=None)):
    require_auth(request)
    check_csrf(request, x_csrf_token)
    if active_export_id:
        raise HTTPException(409, "Aguarde o fim da exportação atual antes de iniciar uma coleta.")
    allowed = {"all", "due", "due_metabase", "sheets", "metabase", "failed", "source"}
    if payload.operation not in allowed:
        raise HTTPException(422, "Operação não permitida.")
    if payload.operation != "source" and not payload.confirm:
        raise HTTPException(400, "Confirme a operação em lote.")
    if payload.operation == "source" and not payload.source_id:
        raise HTTPException(422, "Selecione uma fonte.")
    try:
        operation = operations.start(payload.operation, payload.source_id)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return operation


@app.get("/api/operations")
async def get_operations(request: Request, limit: int = Query(50, ge=1, le=200), status: str = ""):
    require_auth(request)
    rows = history.get_web_operations(limit)
    if status:
        rows = [r for r in rows if r.get("status") == status]
    return {"items": rows, "active": operations.active()}


@app.get("/api/operations/{operation_id}")
async def get_operation(operation_id: str, request: Request):
    require_auth(request)
    try:
        import uuid
        uuid.UUID(operation_id)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(422, "Identificador inválido.") from exc
    row = next((r for r in history.get_web_operations(500) if r["id"] == operation_id), None)
    if not row:
        raise HTTPException(404, "Operação não encontrada.")
    return row


@app.get("/api/settings")
async def get_settings(request: Request):
    require_auth(request)
    sys_config = read_json(ROOT / "config/sistema.json", {})
    return {"paths": sys_config.get("geral", {}), "frequencies": FREQUENCIES,
            "scheduler": scheduler_status(), "metabase_cards": read_json(ROOT / "config/metabase_cards.json", {"cards": {}}).get("cards", {}),
            "network_access": "HTTPS obrigatório fora do loopback; porta local padrão 8000."}


@app.get("/api/scheduler")
async def get_scheduler(request: Request):
    require_auth(request)
    return scheduler_status()


@app.post("/api/scheduler/dry-run")
async def scheduler_preview(payload: DryRunPayload, request: Request,
                            x_csrf_token: Optional[str] = Header(default=None)):
    require_auth(request)
    check_csrf(request, x_csrf_token)
    try:
        command = scheduler_dry_run(payload.action, payload.frequency, payload.time)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"command_preview": command, "task_created": False}


@app.post("/api/scheduler")
async def change_scheduler(payload: SchedulePayload, request: Request,
                           x_csrf_token: Optional[str] = Header(default=None)):
    require_auth(request)
    check_csrf(request, x_csrf_token)
    try:
        return execute_scheduler_action(payload.action, payload.frequency, payload.time, payload.confirm)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        logger.exception("Falha no comando do Agendador")
        raise HTTPException(500, "Falha ao executar o comando do Agendador.") from exc


@app.get("/api/reports")
async def reports(request: Request):
    require_auth(request)
    directory = ROOT / "docs/relatorios"
    return {"items": [{"name": p.name, "modified": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat()}
                       for p in sorted(directory.glob("*.md")) if p.is_file()]}


@app.get("/api/reports/{name}")
async def report_content(name: str, request: Request):
    require_auth(request)
    directory = (ROOT / "docs/relatorios").resolve()
    candidate = (directory / name).resolve()
    if candidate.parent != directory or candidate.suffix.lower() != ".md" or not candidate.is_file():
        raise HTTPException(404, "Relatório não encontrado.")
    return {"name": candidate.name, "content": candidate.read_text(encoding="utf-8")[:100_000]}


@app.get("/api/logs")
async def get_logs(request: Request, lines: int = Query(100, ge=1, le=500)):
    require_auth(request)
    path = ROOT / "logs/coleta.log"
    if not path.exists():
        return {"lines": []}
    return {"lines": path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]}


@app.get("/{section}", response_class=HTMLResponse)
async def web_page(section: str, request: Request):
    allowed = {"dashboard", "sources", "collections", "history", "settings", "exports"}
    if section not in allowed:
        raise HTTPException(404, "Página não encontrada.")
    if request.session.get("authenticated") is not True:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "index.html", {"section": section})


@app.get("/", include_in_schema=False)
async def home(request: Request):
    target = "/dashboard" if request.session.get("authenticated") else "/login"
    return RedirectResponse(target, status_code=303)
