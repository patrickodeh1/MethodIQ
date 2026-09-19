from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import DATABASE_URL

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def ensure_schema():
    """Add fields introduced after the initial SQLite scaffold."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT OR IGNORE INTO student_enrollments (student_id, course_id) "
            "SELECT id, course_id FROM students WHERE course_id IS NOT NULL"
        ))
        for table, column, definition in (
            ("courses", "description_format", "VARCHAR(20) DEFAULT 'html'"),
            ("tasks", "description_format", "VARCHAR(20) DEFAULT 'html'"),
            ("topics", "concepts_taught", "TEXT DEFAULT ''"),
            ("courses", "published", "BOOLEAN DEFAULT 0"),
            ("tasks", "published", "BOOLEAN DEFAULT 0"),
        ):
            columns = connection.execute(text(f"PRAGMA table_info({table})")).fetchall()
            if not any(row[1] == column for row in columns):
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
                if column == "published":
                    connection.execute(text(f"UPDATE {table} SET published = 1"))

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
