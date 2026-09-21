from urllib.parse import quote

from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import asc

from app.database import get_db
from app.models import Student, Task, Topic, Submission, AIHelpRequest, StudentEnrollment
from app.auth import (
    make_token, get_current_student_id, get_admin_session,
    STUDENT_COOKIE, ADMIN_COOKIE, SESSION_MAX_AGE, clear_cookie,
)
from app.judge import judge_submission, run_code
from app.templates_env import templates
from app.phone import normalize_phone_number
from app.ai import generate_hint

router = APIRouter()


def _ordered_tasks_for_course(db: Session, course_id: int):
    return (
        db.query(Task).join(Topic, Task.topic_id == Topic.id)
        .filter(Topic.course_id == course_id, Task.published.is_(True), Topic.course.has(published=True))
        .order_by(asc(Topic.order), asc(Task.order)).all()
    )


def _next_task_for_course(db: Session, student: Student, course_id: int, passed_ids=None):
    passed_ids = passed_ids if passed_ids is not None else {
        submission.task_id
        for submission in db.query(Submission).filter(
            Submission.student_id == student.id,
            Submission.passed.is_(True),
        ).all()
    }
    return next(
        (task for task in _ordered_tasks_for_course(db, course_id) if task.id not in passed_ids),
        None,
    )


def _task_is_locked(db: Session, task: Task, passed_ids):
    for course_task in _ordered_tasks_for_course(db, task.topic.course_id):
        if course_task.id == task.id:
            return False
        if course_task.id not in passed_ids:
            return True
    return False


def _enrolled_courses(student: Student):
    return [
        enrollment.course for enrollment in student.enrollments
        if enrollment.course and enrollment.course.published
    ]


def _enrolled_course_ids(student: Student):
    return {course.id for course in _enrolled_courses(student)}


def _student_progress(db: Session, student: Student):
    course_ids = _enrolled_course_ids(student)
    if not course_ids:
        return None, set(), []
    all_tasks = (
        db.query(Task).join(Topic, Task.topic_id == Topic.id)
        .filter(
            Topic.course_id.in_(course_ids),
            Task.published.is_(True),
            Topic.course.has(published=True),
        )
        .order_by(asc(Topic.order), asc(Task.order)).all()
    )
    passed_task_ids = {
        s.task_id for s in db.query(Submission)
        .filter(Submission.student_id == student.id, Submission.passed.is_(True)).all()
    }
    current_task = None
    for t in all_tasks:
        if t.id not in passed_task_ids:
            current_task = t
            break
    return current_task, passed_task_ids, all_tasks


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login")
def login_submit(request: Request, phone_number: str = Form(...), db: Session = Depends(get_db)):
    phone_number = normalize_phone_number(phone_number)
    student = next(
        (
            candidate
            for candidate in db.query(Student).all()
            if normalize_phone_number(candidate.phone_number) == phone_number
        ),
        None,
    )
    if not student:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Phone number not recognized. Ask your admin to add you."},
        )
    token = make_token({"student_id": student.id})
    resp = RedirectResponse(url="/dashboard", status_code=303)
    resp.set_cookie(STUDENT_COOKIE, token, max_age=SESSION_MAX_AGE, httponly=True)
    clear_cookie(resp, ADMIN_COOKIE)
    return resp


@router.get("/logout")
def logout():
    resp = RedirectResponse(url="/login", status_code=303)
    clear_cookie(resp, STUDENT_COOKIE)
    return resp


def _require_student(request: Request, db: Session):
    student_id = get_current_student_id(request)
    if not student_id:
        return None
    return db.query(Student).get(student_id)


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), page: int = Query(1, ge=1)):
    admin_session = get_admin_session(request)
    if admin_session:
        return RedirectResponse(
            url="/staff" if admin_session.get("role") == "staff" else "/admin",
            status_code=303,
        )
    student = _require_student(request, db)
    if not student:
        return RedirectResponse(url="/login", status_code=303)

    enrolled_courses = _enrolled_courses(student)
    current_task, passed_ids, all_tasks = _student_progress(db, student)
    total = len(all_tasks)
    score_pct = round(100 * len(passed_ids) / total) if total else 0
    course_sections = []
    for course in enrolled_courses:
        topics = []
        previous_in_course_incomplete = False
        course_tasks = []
        for topic in course.topics:
            tasks = [task for task in topic.tasks if task.published]
            course_tasks.extend(tasks)
            if tasks:
                completed_count = sum(task.id in passed_ids for task in tasks)
                active_task = next(
                    (task for task in tasks if task.id not in passed_ids),
                    None,
                )
                topic_locked = previous_in_course_incomplete
                topics.append(
                    {
                        "topic": topic,
                        "task_count": len(tasks),
                        "completed_count": completed_count,
                        "active_task": active_task if not topic_locked else None,
                        "locked": topic_locked,
                    }
                )
                if active_task:
                    previous_in_course_incomplete = True
        course_completed = sum(task.id in passed_ids for task in course_tasks)
        course_current_task = next(
            (task for task in course_tasks if task.id not in passed_ids),
            None,
        )
        course_sections.append(
            {
                "course": course,
                "topics": topics,
                "task_count": len(course_tasks),
                "completed_count": course_completed,
                "progress_pct": round(100 * course_completed / len(course_tasks)) if course_tasks else 0,
                "current_task": course_current_task,
            }
        )

    completed_tasks = [task for task in all_tasks if task.id in passed_ids]
    history_page_size = 5
    history_total_pages = max(1, (len(completed_tasks) + history_page_size - 1) // history_page_size)
    history_page = min(page, history_total_pages)
    history_page_tasks = completed_tasks[
        (history_page - 1) * history_page_size:history_page * history_page_size
    ]

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request, "student": student, "current_task": current_task,
            "score_pct": score_pct,
            "passed_count": len(passed_ids), "total_count": total,
            "all_tasks": all_tasks, "passed_ids": passed_ids,
            "course_sections": course_sections,
            "history_page_tasks": history_page_tasks,
            "history_page": history_page,
            "history_total_pages": history_total_pages,
            "enrolled_courses": enrolled_courses,
        },
    )


@router.get("/topic/{topic_id}", response_class=HTMLResponse)
def topic_page(topic_id: int, request: Request, db: Session = Depends(get_db)):
    student = _require_student(request, db)
    if not student:
        return RedirectResponse(url="/login", status_code=303)

    topic = db.query(Topic).get(topic_id)
    if (
        not topic
        or not topic.course.published
        or topic.course_id not in _enrolled_course_ids(student)
    ):
        return RedirectResponse(url="/dashboard", status_code=303)

    passed_ids = {
        submission.task_id
        for submission in db.query(Submission).filter(
            Submission.student_id == student.id,
            Submission.passed.is_(True),
        ).all()
    }
    tasks = []
    for task in topic.tasks:
        if not task.published:
            continue
        tasks.append(
            {
                "task": task,
                "completed": task.id in passed_ids,
                "locked": _task_is_locked(db, task, passed_ids),
            }
        )

    return templates.TemplateResponse(
        "topic.html",
        {
            "request": request,
            "student": student,
            "topic": topic,
            "tasks": tasks,
            "completed_count": sum(item["completed"] for item in tasks),
        },
    )


@router.get("/task/{task_id}", response_class=HTMLResponse)
def task_page(task_id: int, request: Request, db: Session = Depends(get_db)):
    student = _require_student(request, db)
    if not student:
        return RedirectResponse(url="/login", status_code=303)

    task = db.query(Task).get(task_id)
    if not task or not task.published or not task.topic.course.published or task.topic.course_id not in _enrolled_course_ids(student):
        return RedirectResponse(url="/dashboard", status_code=303)

    _, passed_ids, all_tasks = _student_progress(db, student)
    is_locked = _task_is_locked(db, task, passed_ids)

    sample_tests = [tc for tc in task.test_cases if tc.is_sample]
    already_passed = task.id in passed_ids
    next_task = _next_task_for_course(db, student, task.topic.course_id, passed_ids)

    last_submission = (
        db.query(Submission)
        .filter(Submission.student_id == student.id, Submission.task_id == task.id)
        .order_by(Submission.created_at.desc()).first()
    )

    return templates.TemplateResponse(
        "task.html",
        {
            "request": request, "student": student, "task": task,
            "sample_tests": sample_tests, "is_locked": is_locked,
            "already_passed": already_passed, "last_submission": last_submission,
            "next_task": next_task,
        },
    )


@router.post("/task/{task_id}/submit", response_class=HTMLResponse)
def submit_task(task_id: int, request: Request, code: str = Form(...), db: Session = Depends(get_db)):
    student = _require_student(request, db)
    if not student:
        return RedirectResponse(url="/login", status_code=303)

    task = db.query(Task).get(task_id)
    if not task or not task.published or not task.topic.course.published or task.topic.course_id not in _enrolled_course_ids(student):
        return RedirectResponse(url="/dashboard", status_code=303)

    passed_ids = {
        submission.task_id
        for submission in db.query(Submission).filter(
            Submission.student_id == student.id,
            Submission.passed.is_(True),
        ).all()
    }
    if _task_is_locked(db, task, passed_ids):
        return RedirectResponse(url="/dashboard", status_code=303)

    result = judge_submission(
        code, task.test_cases, entry_function=task.entry_function,
    )

    submission = Submission(
        student_id=student.id, task_id=task.id, code=code,
        passed=result["passed"], tests_passed=result["tests_passed"],
        tests_total=result["tests_total"], error_output=result["error_output"],
    )
    db.add(submission)
    db.commit()

    next_task = (
        _next_task_for_course(db, student, task.topic.course_id)
        if result["passed"] else None
    )
    return templates.TemplateResponse(
        "partials/submission_result.html",
        {
            "request": request,
            "result": result,
            "task": task,
            "next_task": next_task,
        },
    )


@router.post("/task/{task_id}/run", response_class=HTMLResponse)
def run_task_code(
    task_id: int, request: Request, code: str = Form(...),
    db: Session = Depends(get_db),
):
    student = _require_student(request, db)
    if not student:
        return RedirectResponse(url="/login", status_code=303)

    task = db.query(Task).get(task_id)
    if not task or not task.published or not task.topic.course.published or task.topic.course_id not in _enrolled_course_ids(student):
        return RedirectResponse(url="/dashboard", status_code=303)

    # Interactive execution is deliberately mode-agnostic. Students can run
    # any Python program directly before formal verification. The editor
    # content is the complete program; there is no separate task input field.
    result = run_code(code, "")

    return templates.TemplateResponse(
        "partials/run_result.html", {"request": request, "result": result},
    )


@router.get("/task/{task_id}/help", response_class=HTMLResponse)
def ask_for_help(task_id: int, request: Request, db: Session = Depends(get_db)):
    student = _require_student(request, db)
    if not student:
        return RedirectResponse(url="/login", status_code=303)

    task = db.query(Task).get(task_id)
    if not task or not task.published or not task.topic.course.published or task.topic.course_id not in _enrolled_course_ids(student):
        return RedirectResponse(url="/dashboard", status_code=303)

    helpers = (
        db.query(Student)
        .join(Submission, Submission.student_id == Student.id)
        .join(StudentEnrollment, StudentEnrollment.student_id == Student.id)
        .filter(
            Submission.task_id == task_id,
            Submission.passed.is_(True),
            Student.id != student.id,
            StudentEnrollment.course_id == task.topic.course_id,
        )
        .distinct()
        .all()
    )

    message = (
        f"Hi! I'm working on \"{task.title}\" ({task.topic.name}) and I'm stuck. "
        "Would you mind if I asked you a quick question about it? "
        "(Please describe exactly what you tried and where it's going wrong, "
        "rather than asking for the answer outright \u2014 it'll be easier for them to help.)"
    )

    helper_links = [
        {
            "name": h.name,
            "wa_link": f"https://wa.me/{normalize_phone_number(h.phone_number)}?text={quote(message)}",
        }
        for h in helpers
    ]

    return templates.TemplateResponse(
        "partials/help_list.html",
        {"request": request, "helpers": helper_links, "task": task, "ai_enabled": True},
    )


@router.post("/task/{task_id}/ai-help", response_class=HTMLResponse)
def ai_help(
    task_id: int, request: Request, question: str = Form(...),
    code: str = Form(""), db: Session = Depends(get_db),
):
    student = _require_student(request, db)
    if not student:
        return RedirectResponse(url="/login", status_code=303)
    task = db.query(Task).get(task_id)
    if not task or not task.published or not task.topic.course.published or task.topic.course_id not in _enrolled_course_ids(student):
        return RedirectResponse(url="/dashboard", status_code=303)
    history_rows = (
        db.query(AIHelpRequest)
        .filter(AIHelpRequest.student_id == student.id, AIHelpRequest.task_id == task.id)
        .order_by(AIHelpRequest.created_at.asc())
        .all()
    )
    history = []
    for row in history_rows:
        history.extend([
            {"role": "user", "content": row.question},
            {"role": "assistant", "content": row.response},
        ])
    try:
        response = generate_hint(task.title, task.description, question.strip(), code, history)
    except RuntimeError as exc:
        response = f"AI help is temporarily unavailable: {exc}"
    db.add(AIHelpRequest(student_id=student.id, task_id=task.id, question=question.strip(), response=response))
    db.commit()
    return templates.TemplateResponse(
        "partials/ai_help.html",
        {"request": request, "response": response, "question": question, "task_id": task.id},
    )
