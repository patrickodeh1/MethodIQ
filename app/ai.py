import json
import httpx

from app.config import GROQ_API_KEY, GROQ_MODEL, GROQ_API_URL

SYSTEM_PROMPT = """You generate a single coding exercise. Output only JSON with
title, description, starter_code, entry_type, entry_function, class_name and
test_cases. Include at least four valid test cases, exactly one sample, and do
not repeat existing task titles."""


def _post(messages, temperature=0.7, json_mode=False):
    payload = {"model": GROQ_MODEL, "messages": messages, "temperature": temperature}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    try:
        response = httpx.post(
            GROQ_API_URL,
            json=payload,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError) as exc:
        raise RuntimeError(f"Could not get a response from Groq: {exc}")


def generate_task_draft(program_name: str, stage_name: str, stage_goal: str, existing_task_titles: list) -> dict:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set in .env - add your Groq API key first.")
    prompt = (
        f"Program: {program_name}\nStage: {stage_name}\nGoal: {stage_goal or '(none)'}\n"
        f"Existing titles: {', '.join(existing_task_titles) or '(none)'}\n"
        "Use this JSON schema: title, description, starter_code, entry_type, "
        "entry_function, class_name, test_cases. Each test case has input_json, "
        "expected_json and is_sample."
    )
    try:
        draft = json.loads(_post([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ], json_mode=True))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Groq did not return valid JSON: {exc}")
    required = {"title", "description", "starter_code", "entry_type", "entry_function", "class_name", "test_cases"}
    missing = required - draft.keys()
    if missing:
        raise RuntimeError(f"AI draft is missing fields: {', '.join(sorted(missing))}")
    return draft


HINT_SYSTEM_PROMPT = """You are a patient coding tutor. Give clues, questions,
analogies, explanations, and small unrelated examples only. Never provide the
student's exact solution, completed code, a line-by-line patch, the exact
answer, or code that can be copied to solve the task. Never reveal hidden tests.
If asked for the answer, politely refuse and give the next smallest hint. You
may show generic pseudocode or a different example with different names and
values. Keep responses concise and encourage an attempt first."""


def generate_hint(task_title: str, task_description: str, question: str, code: str, history: list) -> str:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set in .env - add your Groq API key first.")
    messages = [{"role": "system", "content": HINT_SYSTEM_PROMPT}]
    messages.extend(history[-6:])
    messages.append({
        "role": "user",
        "content": (
            f"Task: {task_title}\nDescription: {task_description}\n"
            f"Student question: {question}\nStudent code (do not rewrite):\n{code[:6000]}\n"
            "Give a clue-only tutoring response."
        ),
    })
    answer = _post(messages, temperature=0.4)
    if "```" in answer or len(answer) > 3000:
        return "Try one smaller step: choose one simple input, predict the result, and identify which part of your code should produce it."
    return answer.strip()
