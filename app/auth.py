from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request
from app.config import SECRET_KEY
import hashlib

SESSION_MAX_AGE = 60 * 60 * 24 * 14
_serializer = URLSafeTimedSerializer(SECRET_KEY)

STUDENT_COOKIE = "student_session"
ADMIN_COOKIE = "admin_session"


def make_token(data: dict) -> str:
    return _serializer.dumps(data)


def read_token(token: str):
    if not token:
        return None
    try:
        return _serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def get_current_student_id(request: Request):
    data = read_token(request.cookies.get(STUDENT_COOKIE))
    return data.get("student_id") if data else None


def is_admin(request: Request) -> bool:
    data = read_token(request.cookies.get(ADMIN_COOKIE))
    return bool(data and data.get("role") == "admin")


def is_staff(request: Request) -> bool:
    data = read_token(request.cookies.get(ADMIN_COOKIE))
    return bool(data and data.get("role") == "staff")


def get_admin_session(request: Request):
    return read_token(request.cookies.get(ADMIN_COOKIE))


def clear_cookie(response, cookie_name: str):
    response.delete_cookie(cookie_name, path="/")


def password_hash(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()
