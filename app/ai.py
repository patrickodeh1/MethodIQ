import json
import re
import httpx

from app.config import GROQ_API_KEY, GROQ_MODEL, GROQ_API_URL

SYSTEM_PROMPT = """You generate ONE coding exercise for a self-paced,
task-based course. You will be given the course's description, the current
topic's description and goal, and a summary of topics already completed
earlier in the course. Use ALL of this context to judge the student's current
skill level and infer what concepts, syntax, and difficulty are appropriate
right now.

Ground rules:
- The exercise must be solvable using only what the course description and
  the topics-so-far summary establish the student already knows, plus what
  the current topic's own description and goal teach. Do not assume knowledge
  from topics that come later in the course.
- Match the tone and level of the course/topic descriptions you're given: if
  they describe an absolute-beginner, self-paced course, write a small,
  concrete, plainly-worded exercise, not a competitive-programming problem.
- Pick entry_type based on what fits the topic's own material, not a default.
- Test cases should directly verify the topic's goal in a straightforward
  way, not test edge cases beyond what the topic covers.
- Output only JSON with: title, description, starter_code, entry_type,
  entry_function, class_name, test_cases. Include at least four valid test
  cases, exactly one marked as sample, and do not repeat existing task titles.
"""

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Strip HTML tags from Quill-editor content before sending it to the model."""
    if not text:
        return ""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = _TAG_RE.sub(" ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", text).strip()


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


def generate_task_draft(
    course_name: str,
    course_description: str,
    topic_name: str,
    topic_description: str,
    stage_goal: str,
    prior_topics: list,
    existing_task_titles: list,
) -> dict:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set in .env - add your Groq API key first.")

    prior_summary = "\n".join(
        f"- {t['name']}: {t['goal'] or '(no goal set)'}" for t in prior_topics
    ) or "(this is the first topic in the course)"

    prompt = (
        f"Course: {course_name}\n"
        f"Course description: {_strip_html(course_description) or '(none)'}\n\n"
        f"Topics already completed earlier in this course, in order:\n{prior_summary}\n\n"
        f"Current topic: {topic_name}\n"
        f"Current topic description: {_strip_html(topic_description) or '(none)'}\n"
        f"Current topic goal: {stage_goal or '(none)'}\n\n"
        f"Existing task titles in this topic (do not repeat): {', '.join(existing_task_titles) or '(none)'}\n\n"
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
