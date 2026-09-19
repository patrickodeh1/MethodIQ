import json
import re
import httpx

from app.config import GROQ_API_KEY, GROQ_MODEL, GROQ_API_URL

SYSTEM_PROMPT = """You generate ONE coding exercise for a self-paced,
task-based course. You will be given the course's description, the current
topic's description and goal, and a summary of topics already completed
earlier in the course. Use ALL of this context to understand the student's
current skill level and the intended difficulty.

Ground rules:
- The current topic includes a whitelist of concepts the student is allowed to
  use. This whitelist is a hard boundary, not a suggestion. Do not use any
  Python keyword, built-in, data structure, syntax, or construct outside that
  whitelist, even if it seems like a natural fit for the course subject
  matter. For example, do not reach for functions or dictionaries just because
  the course is about data science if they are not whitelisted yet.
- If the topic's goal cannot be fully achieved within the whitelist, write a
  smaller exercise that stays completely within the whitelist.
- The exercise must also be consistent with the current topic's description
  and goal. Do not assume knowledge from topics that come later in the course.
- Match the tone and level of the course/topic descriptions you're given: if
  they describe an absolute-beginner, self-paced course, write a small,
  concrete, plainly-worded exercise, not a competitive-programming problem.
- Every task is a complete Python program. Test-case input is raw stdin text
  and expected output is exact raw stdout text, never a JSON object wrapper.
- Design tasks around observable behavior with private test inputs. Do not ask
  students to hard-code exact grader values or exact variable names when the
  same skill can be tested with values supplied through input(). For
  assignment/conversion exercises, have the program read values from stdin,
  store them in variables, and print the required result; the test cases then
  supply different private values.
- Do not put hidden test values, expected outputs, or answer-specific literal
  values in the task description. Describe the input format and required
  behavior instead. Never generate a task that says not to read input, gives
  exact values to copy, or requires a fixed answer to be hard-coded. If the
  current whitelist cannot support an input-driven task, create a generic
  concept-practice task whose answer is not specified in the description.
- Test cases should directly verify the topic's goal in a straightforward
  way, not test edge cases beyond what the topic covers.
- Test cases are private grading data. Never include their expected output,
  exact solution, or answer in the task description or starter_code.
- The generated-task history includes tasks previously created for this topic,
  including tasks that were later deleted. Do not repeat those tasks. If an
  earlier task used the same basic idea, create a meaningfully different or
  slightly more advanced exercise while staying within the hard concept
  whitelist.
- Never put task-specific solution information in starter_code. Do not include
  variable names from the task, literal values, print statements, type checks,
  conversion calls, algorithm steps, expected output, TODO examples, or any
  executable code that reveals how to solve the exercise. The application will
  replace the model's starter_code with a neutral blank scaffold.
- Output only JSON with: title, description, starter_code, test_cases.
  Include at least four valid test
  cases, exactly one marked as sample, and do not repeat existing task titles.
"""

_TAG_RE = re.compile(r"<[^>]+>")
SAFE_STARTER_CODE = "# Write your solution here.\n"
UNSAFE_TASK_MARKERS = (
    "must not read any input",
    "must not read input",
    "should not read any input",
    "should not read input",
    "directly output",
    "exact values below",
    "exact values shown",
    "exact values",
    "exact value below",
    "exactly seven lines",
)


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


def _is_unsafe_static_task(draft: dict, concepts_taught: str = "") -> bool:
    """Reject drafts that make the answer a copyable hard-coded exercise."""
    description = _strip_html(draft.get("description", "")).lower()
    if any(marker in description for marker in UNSAFE_TASK_MARKERS):
        return True
    for test_case in draft.get("test_cases", []):
        if not isinstance(test_case, dict):
            return True
        if str(test_case.get("input_json", "")).strip() in ("", "{}"):
            expected = str(test_case.get("expected_json", ""))
            if expected and any(token in expected for token in ("<class", "Name:", "Student:", "Sum:", "Combined:")):
                return True
    return False


def generate_task_draft(
    course_name: str,
    course_description: str,
    topic_name: str,
    topic_description: str,
    stage_goal: str,
    concepts_taught: str,
    prior_topics: list,
    existing_task_titles: list,
    generated_task_history: list,
) -> dict:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set in .env - add your Groq API key first.")

    prior_summary = "\n".join(
        f"- {t['name']}: {t['goal'] or '(no goal set)'}; "
        f"concepts allowed there: {t.get('concepts_taught') or '(none listed)'}"
        for t in prior_topics
    ) or "(this is the first topic in the course)"
    generated_history_summary = "\n".join(
        f"- {task['title']}: {_strip_html(task.get('description', '')) or '(no description)'}"
        for task in generated_task_history
    ) or "(no task has previously been generated for this topic)"

    prompt = (
        f"Course: {course_name}\n"
        f"Course description: {_strip_html(course_description) or '(none)'}\n\n"
        f"Topics already completed earlier in this course, in order:\n{prior_summary}\n\n"
        f"Current topic: {topic_name}\n"
        f"Current topic description: {_strip_html(topic_description) or '(none)'}\n"
        f"Current topic goal: {stage_goal or '(none)'}\n\n"
        f"Current topic concepts taught (hard whitelist; use only these): "
        f"{concepts_taught or '(none listed)'}\n\n"
        f"Existing task titles in this topic (do not repeat): {', '.join(existing_task_titles) or '(none)'}\n\n"
        f"Tasks previously generated for this topic, including deleted tasks "
        f"(do not repeat; build a different or slightly more advanced task):\n"
        f"{generated_history_summary}\n\n"
        "Use this JSON schema: title, description, starter_code, test_cases. "
        "Each test case has input_json, "
        "expected_json and is_sample."
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    try:
        draft = json.loads(_post(messages, json_mode=True))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Groq did not return valid JSON: {exc}")
    required = {"title", "description", "starter_code", "test_cases"}
    missing = required - draft.keys()
    if missing:
        raise RuntimeError(f"AI draft is missing fields: {', '.join(sorted(missing))}")
    if _is_unsafe_static_task(draft, concepts_taught):
        input_allowed = "input(" in concepts_taught.lower()
        correction = (
            "Create an input-driven task: describe the input format, read "
            "values from stdin, and use varied private test inputs."
            if input_allowed
            else
            "Create a generic concept-practice task using only the whitelist. "
            "Do not prescribe exact variable names, literal values, fixed "
            "output lines, or a no-input answer that students can copy."
        )
        messages.append({"role": "assistant", "content": json.dumps(draft)})
        messages.append({
            "role": "user",
            "content": (
                "Reject that draft and regenerate it. It is unsafe because it "
                "asks for exact hard-coded values or a copyable fixed answer. "
                f"{correction} Do not mention exact hidden values, exact "
                "output lines, or exact variable names. Return only the "
                "required JSON schema."
            ),
        })
        try:
            draft = json.loads(_post(messages, json_mode=True))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Groq did not return valid JSON after safety retry: {exc}")
        missing = required - draft.keys()
        if missing or _is_unsafe_static_task(draft, concepts_taught):
            raise RuntimeError(
                "Groq generated an unsafe hard-coded task twice. "
                "The draft was blocked; try generating again."
            )
    # Never trust model-generated starter code: even TODOs can reveal the
    # variable names, values, algorithm, and final output of the exercise.
    draft["starter_code"] = SAFE_STARTER_CODE
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
