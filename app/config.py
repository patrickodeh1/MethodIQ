import os
from dotenv import load_dotenv
load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
STAFF_DEFAULT_PERMISSIONS = os.getenv("STAFF_DEFAULT_PERMISSIONS", "tasks")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./learnplatform.db")

PYTHON_BIN = os.getenv("PYTHON_BIN", "python3")
RUN_TIMEOUT_SECONDS = int(os.getenv("RUN_TIMEOUT_SECONDS", "5"))
RUN_MEMORY_LIMIT_MB = int(os.getenv("RUN_MEMORY_LIMIT_MB", "256"))
SANDBOX_USER = os.getenv("SANDBOX_USER", "")

# Groq API (OpenAI-compatible) for admin-triggered task generation.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
