from urllib.parse import quote

from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
import json
from app.models import (
    Course, Topic, Task, TestCase, Student, StudentEnrollment, StaffUser,
    AuditLog, AIHelpRequest, AITaskGenerationHistory,
)
from app.config import ADMIN_USERNAME, ADMIN_PASSWORD, GROQ_API_KEY
from app.auth import make_token, is_admin, is_staff, get_admin_session, ADMIN_COOKIE, SESSION_MAX_AGE, password_hash
from app.templates_env import templates
from app.ai import generate_task_draft
from app.phone import normalize_phone_number

router = APIRouter(prefix="/admin")
staff_router = APIRouter(prefix="/staff")


def _guard(request: Request, permission: str = "dashboard"):
    if not is_admin(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    return None


def _staff_guard(request: Request):
    if not is_staff(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    return None


@router.get("/login", response_class=HTMLResponse)
def admin_login_page(request: Request):
    return templates.TemplateResponse("admin/login.html", {"request": request, "error": None})


@router.post("/login")
def admin_login_submit(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        token = make_token({"admin": True, "role": "admin", "permissions": ["*"]})
        resp = RedirectResponse(url="/admin", status_code=303)
        resp.set_cookie(ADMIN_COOKIE, token, max_age=SESSION_MAX_AGE, httponly=True)
        return resp
    staff = db.query(StaffUser).filter(StaffUser.username == username, StaffUser.active.is_(True)).first()
    if staff and staff.password_hash == password_hash(password):
        token = make_token({"role": "staff", "staff_id": staff.id})
        resp = RedirectResponse(url="/staff", status_code=303)
        resp.set_cookie(ADMIN_COOKIE, token, max_age=SESSION_MAX_AGE, httponly=True)
        return resp
    return templates.TemplateResponse("admin/login.html", {"request": request, "error": "Invalid credentials."})


@router.get("/logout")
def admin_logout():
    resp = RedirectResponse(url="/admin/login", status_code=303)
    resp.delete_cookie("admin_session")
    return resp


@router.get("", response_class=HTMLResponse)
def admin_home(request: Request, db: Session = Depends(get_db)):
    guard = _guard(request)
    if guard:
        return guard
    courses = db.query(Course).order_by(Course.order).all()
    return templates.TemplateResponse(
        "admin/dashboard.html",
        {
            "request": request, "courses": courses, "ai_enabled": bool(GROQ_API_KEY),
            "session": get_admin_session(request),
        },
    )


@router.get("/audit", response_class=HTMLResponse)
def audit_log_page(request: Request, db: Session = Depends(get_db), page: int = Query(1, ge=1)):
    guard = _guard(request, "dashboard")
    if guard:
        return guard
    page_size = 20
    total_logs = db.query(AuditLog).count()
    total_pages = max(1, (total_logs + page_size - 1) // page_size)
    page = min(page, total_pages)
    logs = (
        db.query(AuditLog)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    students = {s.id: s.name for s in db.query(Student).all()}
    staff = {s.id: s.username for s in db.query(StaffUser).all()}
    return templates.TemplateResponse(
        "admin/audit.html",
        {
            "request": request, "logs": logs, "students": students, "staff": staff,
            "page": page, "total_pages": total_pages,
        },
    )


@router.get("/prompt-history", response_class=HTMLResponse)
def prompt_history_page(
    request: Request, student_id: int = None, db: Session = Depends(get_db)
):
    guard = _guard(request, "dashboard")
    if guard:
        return guard
    students = db.query(Student).order_by(Student.name).all()
    prompts = []
    selected_student = None
    if student_id:
        selected_student = db.query(Student).get(student_id)
        if selected_student:
            prompts = (
                db.query(AIHelpRequest)
                .filter(AIHelpRequest.student_id == student_id)
                .order_by(AIHelpRequest.created_at.desc())
                .all()
            )
    return templates.TemplateResponse(
        "admin/prompt_history.html",
        {
            "request": request,
            "students": students,
            "prompts": prompts,
            "selected_student": selected_student,
        },
    )


@router.post("/staff")
async def create_staff(request: Request, db: Session = Depends(get_db)):
    guard = _guard(request, "staff")
    if guard:
        return guard
    form = await request.form()
    username = (form.get("username") or "").strip()
    password = form.get("password") or ""
    if not username or db.query(StaffUser).filter(StaffUser.username == username).first():
        return RedirectResponse(url="/admin/staff?error=Staff+username+is+already+in+use.", status_code=303)
    db.add(StaffUser(username=username, password_hash=password_hash(password), permissions="fixed"))
    db.commit()
    return RedirectResponse(url="/admin/staff", status_code=303)


@router.get("/staff", response_class=HTMLResponse)
def staff_management_page(request: Request, db: Session = Depends(get_db), error: str = None):
    guard = _guard(request)
    if guard:
        return guard
    return templates.TemplateResponse(
        "admin/staff.html",
        {
            "request": request,
            "staff_users": db.query(StaffUser).order_by(StaffUser.username).all(),
            "error": error,
        },
    )


@router.post("/staff/{staff_id}/delete")
def delete_staff(staff_id: int, request: Request, db: Session = Depends(get_db)):
    guard = _guard(request, "staff")
    if guard:
        return guard
    staff = db.query(StaffUser).get(staff_id)
    if staff:
        db.delete(staff)
        db.commit()
    return RedirectResponse(url="/admin/staff", status_code=303)


# ---- Staff workspace: read-only curriculum, task publishing, student creation ----

@staff_router.get("", response_class=HTMLResponse)
def staff_home(request: Request, db: Session = Depends(get_db)):
    guard = _staff_guard(request)
    if guard:
        return guard
    courses = db.query(Course).order_by(Course.order).all()
    return templates.TemplateResponse(
        "staff/dashboard.html",
        {"request": request, "courses": courses, "session": get_admin_session(request)},
    )


@staff_router.get("/courses/{course_id}", response_class=HTMLResponse)
def staff_course_detail(course_id: int, request: Request, db: Session = Depends(get_db)):
    guard = _staff_guard(request)
    if guard:
        return guard
    course = db.query(Course).get(course_id)
    if not course:
        return RedirectResponse(url="/staff", status_code=303)
    return templates.TemplateResponse("staff/course_detail.html", {"request": request, "course": course})


@staff_router.get("/tasks/{task_id}", response_class=HTMLResponse)
def staff_task_detail(task_id: int, request: Request, db: Session = Depends(get_db)):
    guard = _staff_guard(request)
    if guard:
        return guard
    task = db.query(Task).get(task_id)
    if not task:
        return RedirectResponse(url="/staff", status_code=303)
    return templates.TemplateResponse("staff/task_detail.html", {"request": request, "task": task})


@staff_router.post("/tasks/{task_id}/publish")
def staff_publish_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    guard = _staff_guard(request)
    if guard:
        return guard
    task = db.query(Task).get(task_id)
    if not task:
        return RedirectResponse(url="/staff", status_code=303)
    task.published = True
    db.commit()
    return RedirectResponse(url=f"/staff/tasks/{task_id}", status_code=303)


@staff_router.get("/students", response_class=HTMLResponse)
def staff_students(request: Request, db: Session = Depends(get_db), error: str = None):
    guard = _staff_guard(request)
    if guard:
        return guard
    return templates.TemplateResponse(
        "staff/students.html",
        {"request": request, "students": db.query(Student).order_by(Student.created_at.desc()).all(), "error": error},
    )


@staff_router.post("/students")
def staff_create_student(
    request: Request, name: str = Form(...), phone_number: str = Form(...),
    db: Session = Depends(get_db),
):
    guard = _staff_guard(request)
    if guard:
        return guard
    phone_number = normalize_phone_number(phone_number)
    if not phone_number:
        return RedirectResponse(url="/staff/students?error=Phone+number+is+required.", status_code=303)
    if any(normalize_phone_number(s.phone_number) == phone_number for s in db.query(Student).all()):
        return RedirectResponse(url="/staff/students?error=That+phone+number+already+exists.", status_code=303)
    db.add(Student(name=name.strip(), phone_number=phone_number, course_id=None))
    db.commit()
    return RedirectResponse(url="/staff/students", status_code=303)


# ---- Courses ----

@router.post("/courses")
def create_course(request: Request, name: str = Form(...), description: str = Form(""), db: Session = Depends(get_db)):
    guard = _guard(request, "courses")
    if guard:
        return guard
    db.add(Course(name=name.strip(), description=description))
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/courses/{course_id}/edit")
async def edit_course(course_id: int, request: Request, db: Session = Depends(get_db)):
    guard = _guard(request, "courses")
    if guard:
        return guard
    course = db.query(Course).get(course_id)
    if not course:
        return RedirectResponse(url="/admin", status_code=303)
    form = await request.form()
    course.name = (form.get("name") or course.name).strip()
    course.description = form.get("description") or ""
    db.commit()
    return RedirectResponse(url=f"/admin/courses/{course_id}", status_code=303)


@router.get("/courses/{course_id}", response_class=HTMLResponse)
def course_detail(course_id: int, request: Request, db: Session = Depends(get_db), ai_error: str = None):
    guard = _guard(request, "courses")
    if guard:
        return guard
    course = db.query(Course).get(course_id)
    if not course:
        return RedirectResponse(url="/admin", status_code=303)
    return templates.TemplateResponse(
        "admin/course_detail.html", {"request": request, "course": course, "ai_error": ai_error}
    )


@router.post("/courses/{course_id}/delete")
def delete_course(course_id: int, request: Request, db: Session = Depends(get_db)):
    guard = _guard(request, "courses")
    if guard:
        return guard
    course = db.query(Course).get(course_id)
    if course:
        db.delete(course)
        db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/courses/{course_id}/publish")
def publish_course(course_id: int, request: Request, db: Session = Depends(get_db)):
    guard = _guard(request, "courses")
    if guard:
        return guard
    course = db.query(Course).get(course_id)
    if not course:
        return RedirectResponse(url="/admin", status_code=303)
    course.published = not course.published
    db.commit()
    return RedirectResponse(url=f"/admin/courses/{course_id}", status_code=303)


# ---- Topics ----

@router.post("/courses/{course_id}/topics")
def create_topic(
    course_id: int, request: Request, name: str = Form(...),
    description: str = Form(""), goal: str = Form(""),
    concepts_taught: str = Form(""), order: int = Form(0),
    db: Session = Depends(get_db),
):
    guard = _guard(request, "courses")
    if guard:
        return guard
    if not db.query(Course).get(course_id):
        return RedirectResponse(url="/admin", status_code=303)
    db.add(Topic(
        course_id=course_id, name=name.strip(), description=description,
        goal=goal, concepts_taught=concepts_taught.strip(), order=order,
    ))
    db.commit()
    return RedirectResponse(url=f"/admin/courses/{course_id}", status_code=303)


@router.post("/topics/{topic_id}/delete")
def delete_topic(topic_id: int, request: Request, db: Session = Depends(get_db)):
    guard = _guard(request, "courses")
    if guard:
        return guard
    topic = db.query(Topic).get(topic_id)
    course_id = topic.course_id if topic else None
    if topic:
        db.delete(topic)
        db.commit()
    return RedirectResponse(url=f"/admin/courses/{course_id}" if course_id else "/admin", status_code=303)


# ---- Tasks ----

@router.get("/tasks/{task_id}", response_class=HTMLResponse)
def task_detail(task_id: int, request: Request, db: Session = Depends(get_db)):
    guard = _guard(request, "tasks")
    if guard:
        return guard
    task = db.query(Task).get(task_id)
    if not task:
        return RedirectResponse(url="/admin", status_code=303)
    return templates.TemplateResponse("admin/task_detail.html", {"request": request, "task": task})


@router.post("/topics/{topic_id}/tasks")
def create_task(
    topic_id: int, request: Request,
    title: str = Form(...), description: str = Form(""),
    starter_code: str = Form(""), order: int = Form(0),
    db: Session = Depends(get_db),
):
    guard = _guard(request, "tasks")
    if guard:
        return guard
    topic = db.query(Topic).get(topic_id)
    if not topic:
        return RedirectResponse(url="/admin", status_code=303)
    task = Task(
        topic_id=topic_id, title=title.strip(), description=description,
        starter_code=starter_code, order=order,
    )
    db.add(task)
    db.commit()
    return RedirectResponse(url=f"/admin/courses/{topic.course_id}", status_code=303)


@router.post("/tasks/{task_id}/edit")
async def edit_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    guard = _guard(request, "tasks")
    if guard:
        return guard
    task = db.query(Task).get(task_id)
    if not task:
        return RedirectResponse(url="/admin", status_code=303)
    form = await request.form()
    task.title = (form.get("title") or task.title).strip()
    task.description = form.get("description") or ""
    task.starter_code = form.get("starter_code") or ""
    task.order = int(form.get("order") or 0)
    db.commit()
    return RedirectResponse(url=f"/admin/tasks/{task_id}", status_code=303)


@router.post("/tasks/{task_id}/delete")
def delete_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    guard = _guard(request, "tasks")
    if guard:
        return guard
    task = db.query(Task).get(task_id)
    course_id = task.topic.course_id if task else None
    if task:
        db.delete(task)
        db.commit()
    return RedirectResponse(url=f"/admin/courses/{course_id}" if course_id else "/admin", status_code=303)


@router.post("/tasks/{task_id}/publish")
def publish_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    guard = _guard(request, "tasks")
    if guard:
        return guard
    task = db.query(Task).get(task_id)
    if not task:
        return RedirectResponse(url="/admin", status_code=303)
    task.published = not task.published
    db.commit()
    return RedirectResponse(url=f"/admin/tasks/{task_id}", status_code=303)


# ---- AI-assisted task generation (admin-triggered, always reviewed before saving) ----

@router.post("/topics/{topic_id}/ai-generate", response_class=HTMLResponse)
def ai_generate_task(topic_id: int, request: Request, db: Session = Depends(get_db)):
    guard = _guard(request, "tasks")
    if guard:
        return guard
    topic = db.query(Topic).get(topic_id)
    if not topic:
        return RedirectResponse(url="/admin", status_code=303)

    existing_titles = [t.title for t in topic.tasks]
    generated_history = (
        db.query(AITaskGenerationHistory)
        .filter(AITaskGenerationHistory.topic_id == topic.id)
        .order_by(AITaskGenerationHistory.created_at.asc(), AITaskGenerationHistory.id.asc())
        .all()
    )
    generated_task_history = [
        {"title": item.title, "description": item.description}
        for item in generated_history
    ]
    prior_topics = [
        {"name": t.name, "goal": t.goal, "concepts_taught": t.concepts_taught}
        for t in topic.course.topics
        if t.order < topic.order
    ]
    try:
        draft = generate_task_draft(
            topic.course.name,
            topic.course.description,
            topic.name,
            topic.description,
            topic.goal,
            topic.concepts_taught,
            prior_topics,
            existing_titles,
            generated_task_history,
        )
    except RuntimeError as exc:
        return RedirectResponse(
            url=f"/admin/courses/{topic.course_id}?ai_error={quote(str(exc))}", status_code=303
        )

    db.add(AITaskGenerationHistory(
        topic_id=topic.id,
        title=(draft.get("title") or "Untitled generated task").strip(),
        description=draft.get("description") or "",
    ))
    db.commit()

    return templates.TemplateResponse(
        "admin/task_draft.html",
        {"request": request, "draft": draft, "topic_id": topic_id, "course_id": topic.course_id},
    )


@router.post("/topics/{topic_id}/tasks/from-draft")
async def create_task_from_draft(topic_id: int, request: Request, db: Session = Depends(get_db)):
    guard = _guard(request, "tasks")
    if guard:
        return guard
    topic = db.query(Topic).get(topic_id)
    if not topic:
        return RedirectResponse(url="/admin", status_code=303)

    form = await request.form()
    title = (form.get("title") or "").strip()
    description = form.get("description") or ""
    starter_code = form.get("starter_code") or ""
    entry_function = (form.get("entry_function") or "").strip()
    params = (form.get("params") or "").strip()
    order = int(form.get("order") or 0)

    if not title:
        return RedirectResponse(
            url=f"/admin/courses/{topic.course_id}?ai_error=Task+title+was+empty+-+not+saved.", status_code=303
        )

    task = Task(
        topic_id=topic_id, title=title, description=description, starter_code=starter_code,
        entry_function=entry_function, params=params, entry_mode="function" if entry_function else "",
        order=order,
    )
    db.add(task)
    db.flush()  # get task.id before commit so we can attach test cases

    count = int(form.get("tc_count") or 0)
    for i in range(count):
        input_json = form.get(f"tc_input_{i}")
        expected_json = form.get(f"tc_expected_{i}")
        if input_json is None or expected_json is None:
            continue
        is_sample = form.get(f"tc_is_sample_{i}") == "true"
        db.add(TestCase(task_id=task.id, input_json=input_json, expected_json=expected_json, is_sample=is_sample, order=i))

    db.commit()
    return RedirectResponse(url=f"/admin/courses/{topic.course_id}", status_code=303)


# ---- Test cases ----

@router.post("/tasks/{task_id}/testcases")
def create_testcase(
    task_id: int, request: Request,
    input_json: str = Form(""), expected_json: str = Form(...),
    is_sample: bool = Form(False), order: int = Form(0),
    db: Session = Depends(get_db),
):
    guard = _guard(request, "tasks")
    if guard:
        return guard
    if not db.query(Task).get(task_id):
        return RedirectResponse(url="/admin", status_code=303)
    db.add(TestCase(
        task_id=task_id, input_json=input_json, expected_json=expected_json,
        is_sample=is_sample, order=order,
    ))
    db.commit()
    return RedirectResponse(url=f"/admin/tasks/{task_id}", status_code=303)


@router.post("/testcases/{testcase_id}/edit")
def edit_testcase(
    testcase_id: int, request: Request, input_json: str = Form(""),
    expected_json: str = Form(...), is_sample: bool = Form(False),
    order: int = Form(0), db: Session = Depends(get_db),
):
    guard = _guard(request, "tasks")
    if guard:
        return guard
    testcase = db.query(TestCase).get(testcase_id)
    if not testcase:
        return RedirectResponse(url="/admin", status_code=303)
    testcase.input_json = input_json
    testcase.expected_json = expected_json
    testcase.is_sample = is_sample
    testcase.order = order
    db.commit()
    return RedirectResponse(url=f"/admin/tasks/{testcase.task_id}", status_code=303)


@router.post("/testcases/{testcase_id}/delete")
def delete_testcase(testcase_id: int, request: Request, db: Session = Depends(get_db)):
    guard = _guard(request, "tasks")
    if guard:
        return guard
    tc = db.query(TestCase).get(testcase_id)
    task_id = tc.task_id if tc else None
    if tc:
        db.delete(tc)
        db.commit()
    return RedirectResponse(url=f"/admin/tasks/{task_id}" if task_id else "/admin", status_code=303)


# ---- Students ----

@router.get("/students", response_class=HTMLResponse)
def students_page(request: Request, db: Session = Depends(get_db), error: str = None):
    guard = _guard(request, "students")
    if guard:
        return guard
    students = db.query(Student).order_by(Student.created_at.desc()).all()
    courses = db.query(Course).order_by(Course.order).all()
    enrolled_course_ids = {
        student.id: {enrollment.course_id for enrollment in student.enrollments}
        for student in students
    }
    return templates.TemplateResponse(
        "admin/students.html",
        {
            "request": request, "students": students, "courses": courses, "error": error,
            "enrolled_course_ids": enrolled_course_ids,
        },
    )


@router.post("/students")
def create_student(request: Request, name: str = Form(...), phone_number: str = Form(...), db: Session = Depends(get_db)):
    guard = _guard(request, "students")
    if guard:
        return guard

    phone_number = normalize_phone_number(phone_number)
    if not phone_number:
        return RedirectResponse(url="/admin/students?error=Phone+number+is+required.", status_code=303)

    if any(
        normalize_phone_number(student.phone_number) == phone_number
        for student in db.query(Student).all()
    ):
        return RedirectResponse(
            url="/admin/students?error=A+student+with+that+phone+number+already+exists.", status_code=303,
        )

    db.add(Student(name=name.strip(), phone_number=phone_number, course_id=None))
    db.commit()
    return RedirectResponse(url="/admin/students", status_code=303)


@router.post("/students/{student_id}/assign-course")
async def assign_course(student_id: int, request: Request, db: Session = Depends(get_db)):
    guard = _guard(request, "students")
    if guard:
        return guard

    student = db.query(Student).get(student_id)
    if not student:
        return RedirectResponse(url="/admin/students?error=Student+not+found.", status_code=303)

    form = await request.form()
    selected_ids = {int(value) for value in form.getlist("course_ids") if str(value).isdigit()}
    valid_ids = {course.id for course in db.query(Course).filter(Course.id.in_(selected_ids)).all()} if selected_ids else set()
    student.enrollments.clear()
    for course_id in valid_ids:
        student.enrollments.append(StudentEnrollment(course_id=course_id))
    db.commit()
    return RedirectResponse(url="/admin/students", status_code=303)


@router.post("/students/{student_id}/delete")
def delete_student(student_id: int, request: Request, db: Session = Depends(get_db)):
    guard = _guard(request, "students")
    if guard:
        return guard
    student = db.query(Student).get(student_id)
    if student:
        db.delete(student)
        db.commit()
    return RedirectResponse(url="/admin/students", status_code=303)
