from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, ForeignKey, DateTime, UniqueConstraint
)
from sqlalchemy.orm import relationship
from app.database import Base


class Course(Base):
    __tablename__ = "courses"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    description_format = Column(String(20), default="html")
    published = Column(Boolean, default=False, nullable=False)
    order = Column(Integer, default=0)

    topics = relationship("Topic", back_populates="course", order_by="Topic.order", cascade="all, delete-orphan")


class Topic(Base):
    __tablename__ = "topics"
    id = Column(Integer, primary_key=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    order = Column(Integer, default=0)
    goal = Column(Text, default="")  # what a student should be able to do after this topic/stage - used as AI context
    concepts_taught = Column(Text, default="")  # comma-separated whitelist of concepts allowed in AI-generated tasks; enforced as a hard boundary rather than inferred
    entry_mode = Column(String(20), default="function")  # "function" or "class" - default harness mode for tasks generated in this topic
    resources_json = Column(Text, default="[]")  # JSON list of {"title": str, "url": str, "note": str} curated resources for this topic

    course = relationship("Course", back_populates="topics")
    tasks = relationship("Task", back_populates="topic", order_by="Task.order", cascade="all, delete-orphan")


class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True)
    topic_id = Column(Integer, ForeignKey("topics.id"), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")
    description_format = Column(String(20), default="html")
    published = Column(Boolean, default=False, nullable=False)
    starter_code = Column(Text, default="")
    entry_function = Column(String(100), default="")  # function/method name students must define; blank = legacy stdin/stdout task
    params = Column(Text, default="")  # comma-separated parameter names, in call order
    entry_mode = Column(String(20), default="function")  # "function" or "class" - how this specific task is graded
    order = Column(Integer, default=0)

    topic = relationship("Topic", back_populates="tasks")
    test_cases = relationship("TestCase", back_populates="task", order_by="TestCase.order", cascade="all, delete-orphan")
    submissions = relationship("Submission", back_populates="task", cascade="all, delete-orphan")


class AITaskGenerationHistory(Base):
    __tablename__ = "ai_task_generation_history"
    id = Column(Integer, primary_key=True)
    topic_id = Column(Integer, ForeignKey("topics.id"), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class TestCase(Base):
    __tablename__ = "test_cases"
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)

    input_json = Column(Text, default="")
    expected_json = Column(Text, default="")

    is_sample = Column(Boolean, default=False)
    order = Column(Integer, default=0)

    task = relationship("Task", back_populates="test_cases")


class Student(Base):
    __tablename__ = "students"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    phone_number = Column(String(30), nullable=False, unique=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    course = relationship("Course")
    submissions = relationship("Submission", back_populates="student", cascade="all, delete-orphan")
    enrollments = relationship("StudentEnrollment", back_populates="student", cascade="all, delete-orphan")


class StudentEnrollment(Base):
    __tablename__ = "student_enrollments"
    __table_args__ = (UniqueConstraint("student_id", "course_id", name="uq_student_course"),)
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    student = relationship("Student", back_populates="enrollments")
    course = relationship("Course")


class Submission(Base):
    __tablename__ = "submissions"
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    code = Column(Text, nullable=False)
    passed = Column(Boolean, default=False)
    tests_passed = Column(Integer, default=0)
    tests_total = Column(Integer, default=0)
    error_output = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    student = relationship("Student", back_populates="submissions")
    task = relationship("Task", back_populates="submissions")


class StaffUser(Base):
    __tablename__ = "staff_users"
    id = Column(Integer, primary_key=True)
    username = Column(String(100), nullable=False, unique=True)
    password_hash = Column(String(128), nullable=False)
    permissions = Column(Text, default="tasks")
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AIHelpRequest(Base):
    __tablename__ = "ai_help_requests"
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    question = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    actor_role = Column(String(20), nullable=False, default="anonymous")
    actor_id = Column(Integer, nullable=True)
    action = Column(String(200), nullable=False)
    path = Column(String(300), nullable=False)
    method = Column(String(10), nullable=False)
    status_code = Column(Integer, nullable=True)
    details = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
