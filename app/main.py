from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.database import Base, engine, ensure_schema, SessionLocal
from app import models  # noqa: F401
from app.routers import student, admin
from app.auth import get_current_student_id, get_admin_session

Base.metadata.create_all(bind=engine)
ensure_schema()

app = FastAPI(title="MethodIQ")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(student.router)
app.include_router(admin.router)
app.include_router(admin.staff_router)


def _should_audit_request(path: str, method: str) -> bool:
    """Keep the audit trail focused on authentication and meaningful actions."""
    if path in {"/login", "/admin/login"}:
        return method == "POST"
    if path in {"/logout", "/admin/logout"}:
        return method == "GET"
    if method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return False
    return (
        path.startswith("/admin/courses")
        or path.startswith("/admin/topics")
        or path.startswith("/admin/tasks")
        or path.startswith("/admin/testcases")
        or path.startswith("/admin/students")
        or path.startswith("/admin/staff")
        or path.startswith("/admin/publish")
        or path.startswith("/staff/tasks")
        or path.startswith("/staff/students")
        or path.startswith("/task/")
    )


@app.middleware("http")
async def audit_requests(request: Request, call_next):
    response = await call_next(request)
    if _should_audit_request(request.url.path, request.method):
        admin_session = get_admin_session(request)
        student_id = get_current_student_id(request)
        if admin_session:
            actor_role = admin_session.get("role", "admin")
            actor_id = admin_session.get("staff_id")
        elif student_id:
            actor_role = "student"
            actor_id = student_id
        else:
            actor_role = "anonymous"
            actor_id = None
        db = SessionLocal()
        try:
            db.add(models.AuditLog(
                actor_role=actor_role,
                actor_id=actor_id,
                action=f"{request.method} {request.url.path}",
                path=request.url.path,
                method=request.method,
                status_code=response.status_code,
            ))
            db.commit()
        finally:
            db.close()
    return response


def _error_page(title: str, message: str, back_url: str = "/") -> HTMLResponse:
    html = f"""
    <!doctype html><html><head><meta charset="utf-8">
    <title>{title}</title>
    <link rel="stylesheet" href="/static/style.css"></head>
    <body><main class="container"><div class="card">
    <h1>{title}</h1><p>{message}</p>
    <a class="btn" href="{back_url}">Go back</a>
    </div></main></body></html>
    """
    return HTMLResponse(html)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return _error_page(
        "Something about that request wasn\'t right",
        "Please go back and check the form, then try again.",
    )


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
    return _error_page(str(exc.status_code), str(exc.detail))


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    return _error_page(
        "Something went wrong",
        "That didn\'t work - please try again, or go back to the dashboard.",
    )


@app.get("/")
def root():
    return RedirectResponse(url="/dashboard")
