import json
import re
import httpx

from app.config import GROQ_API_KEY, GROQ_MODEL, GROQ_API_URL
from app.judge import run_code

# ---------------------------------------------------------------------------
# Pipeline overview
# ---------------------------------------------------------------------------
# A single model call cannot both invent a problem description AND invent
# matching test data AND keep the answer out of the description, because it
# has to hold the answer in its own output to do the second part. Splitting
# generation into separate calls, each of which only sees what it needs,
# removes the leak vector instead of trying to filter it out after the fact:
#
#   1. SPEC       -> title, description, starter_code (no test data at all)
#   2. SOLUTION   -> a private reference solution for that spec (never shown
#                    to students, never fed back into the spec step)
#   3. TEST INPUT -> raw stdin strings only (no expected output invented)
#   4. EXECUTE    -> run the reference solution against each input for real;
#                    whatever it prints becomes expected_json. Test cases are
#                    therefore guaranteed correct, not guessed.
#   5. LEAK CHECK -> deterministic containment check: does any expected
#                    output string appear in the description/starter_code?
#                    If so, regenerate only the spec step and re-check.
# ---------------------------------------------------------------------------

SPEC_SYSTEM_PROMPT = """You write ONE coding exercise's public-facing spec for
a self-paced, task-based course. You will be given the course's description,
the current topic's description and goal, a hard whitelist of concepts the
student is allowed to use, and a history of tasks already created for this
topic (including deleted ones) to avoid repeating.

Ground rules:
- The whitelist of concepts is a hard boundary, not a suggestion. Do not use
  any Python keyword, built-in, data structure, syntax, or construct outside
  it, even if it seems like a natural fit for the course's subject matter.
- If the topic's goal cannot be fully achieved within the whitelist, write a
  smaller exercise that stays completely within it.
- Do not assume knowledge from topics that come later in the course.
- Match the tone and level of the course/topic descriptions given to you: for
  an absolute-beginner, self-paced course, write a small, concrete, plainly
  worded exercise, not a competitive-programming problem.
- The exercise is always a complete Python program that reads input with
  input() (when the whitelist includes it) and prints the required result.
  Describe the input format and the required output behavior in plain
  language. Do NOT include any worked example with concrete numbers, sample
  calculations, or a specific expected output string anywhere in the
  description. You do not know the hidden test data yet, so there is nothing
  to leak, and it must stay that way: never write example input/output pairs.
- starter_code must be a neutral blank scaffold only (e.g. a short comment).
  Never include variable names, literal values, print statements, TODO
  examples, or anything that hints at the solution's shape.
- Do not repeat the idea of any task in the provided history; if an earlier
  task used the same basic idea, write a meaningfully different or slightly
  more advanced exercise while staying within the whitelist.
- Output only JSON with exactly these fields: title, description,
  starter_code.
"""

SOLUTION_SYSTEM_PROMPT = """You write a private reference solution for a
coding exercise. This solution is never shown to students or admins - it
exists only so the grading system can compute correct expected outputs by
actually running it. You will be given the exercise's title, description, and
the whitelist of concepts the student is allowed to use.

Rules:
- Write ONE complete, correct Python script that reads all required input
  with input() and prints exactly the output the description asks for,
  nothing extra.
- Prefer using only the given whitelist so the exercise stays solvable by a
  student who only knows those concepts, but prioritize correctness if the
  whitelist is ambiguous or incomplete for the task.
- Do not print any debug output, prompts, or extra text beyond what the
  description specifies.
- Output only JSON with exactly one field: solution_code (a string containing
  the full script).
"""

TESTGEN_SYSTEM_PROMPT = """You generate raw stdin test inputs for a coding
exercise, given its title and description. You do NOT generate expected
output - that is computed separately by actually running a reference
solution.

Rules:
- Produce at least 5 distinct, varied inputs that meaningfully exercise the
  behavior described (different values, not just cosmetic variants).
- Each input is the exact raw text that would be typed/piped to the program's
  stdin, matching the number and order of values the description implies.
- Mark exactly ONE input as a sample (is_sample: true); all others are
  is_sample: false.
- Output only JSON with exactly one field: test_inputs, a list of objects
  each shaped {"input": "...", "is_sample": true|false}.
"""

_TAG_RE = re.compile(r"<[^>]+>")
SAFE_STARTER_CODE = "# Write your solution here.\n"
_MIN_LEAK_TOKEN_LEN = 3  # ignore trivial/short outputs (e.g. "0", "1") in the containment check


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


def _call_json(system_prompt: str, user_prompt: str, required_fields: set) -> dict:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    try:
        data = json.loads(_post(messages, json_mode=True))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Groq did not return valid JSON: {exc}")
    missing = required_fields - data.keys()
    if missing:
        raise RuntimeError(f"AI response is missing fields: {', '.join(sorted(missing))}")
    return data


def _description_leaks_answer(description: str, starter_code: str, test_cases: list) -> bool:
    """Deterministic containment check: does any real expected output show up
    verbatim in the public-facing text? This replaces keyword-guessing with
    an exact substring check against the actual computed answers."""
    haystack = f"{_strip_html(description)}\n{starter_code}".lower()
    for tc in test_cases:
        expected = str(tc.get("expected_json", "")).strip().lower()
        if len(expected) >= _MIN_LEAK_TOKEN_LEN and expected in haystack:
            return True
    return False


def _generate_spec(context_prompt: str) -> dict:
    return _call_json(
        SPEC_SYSTEM_PROMPT, context_prompt, {"title", "description", "starter_code"}
    )


def _generate_solution(title: str, description: str, concepts_taught: str) -> str:
    prompt = (
        f"Title: {title}\n"
        f"Description: {description}\n"
        f"Concepts whitelist (prefer these, but be correct above all): "
        f"{concepts_taught or '(none listed)'}\n"
    )
    data = _call_json(SOLUTION_SYSTEM_PROMPT, prompt, {"solution_code"})
    return data["solution_code"]


def _generate_test_inputs(title: str, description: str) -> list:
    prompt = f"Title: {title}\nDescription: {description}\n"
    data = _call_json(TESTGEN_SYSTEM_PROMPT, prompt, {"test_inputs"})
    inputs = data.get("test_inputs") or []
    if not isinstance(inputs, list) or len(inputs) < 4:
        raise RuntimeError("AI did not return enough test inputs.")
    return inputs


def _build_test_cases(solution_code: str, test_inputs: list) -> list:
    """Run the reference solution for real against each input. Expected
    output is whatever the solution actually prints - never guessed."""
    test_cases = []
    sample_seen = False
    for item in test_inputs:
        stdin_text = str(item.get("input", ""))
        result = run_code(solution_code, stdin_text)
        if result["error"] or result["stderr"].strip():
            raise RuntimeError(
                "Reference solution failed to run cleanly on a generated "
                f"input: {result['error'] or result['stderr'].strip()}"
            )
        is_sample = bool(item.get("is_sample")) and not sample_seen
        sample_seen = sample_seen or is_sample
        test_cases.append({
            "input_json": stdin_text,
            "expected_json": (result["stdout"] or "").strip(),
            "is_sample": is_sample,
        })
    if not sample_seen and test_cases:
        test_cases[0]["is_sample"] = True
    return test_cases


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

    context_prompt = (
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
        f"{generated_history_summary}\n"
    )

    spec = _generate_spec(context_prompt)

    # Solution and test-input generation don't need the full course context -
    # only the finished spec and the whitelist, so they can't reintroduce
    # anything the spec step deliberately left out.
    solution_code = _generate_solution(spec["title"], spec["description"], concepts_taught)
    test_inputs = _generate_test_inputs(spec["title"], spec["description"])
    test_cases = _build_test_cases(solution_code, test_inputs)

    if _description_leaks_answer(spec["description"], spec["starter_code"], test_cases):
        # Only the spec is at fault here (it's the only step that produced
        # public-facing text), so only regenerate that, with the concrete
        # leaked context stripped, before failing outright.
        retry_prompt = (
            context_prompt
            + "\nA previous attempt at this spec leaked a computed answer "
              "value into the description or starter_code. Rewrite the spec "
              "so it describes the input format and required behavior only, "
              "with no example numbers, no sample calculation, and no "
              "specific output text anywhere."
        )
        spec = _generate_spec(retry_prompt)
        solution_code = _generate_solution(spec["title"], spec["description"], concepts_taught)
        test_inputs = _generate_test_inputs(spec["title"], spec["description"])
        test_cases = _build_test_cases(solution_code, test_inputs)
        if _description_leaks_answer(spec["description"], spec["starter_code"], test_cases):
            raise RuntimeError(
                "Generated task leaked an answer value twice in a row. "
                "The draft was blocked; try generating again."
            )

    return {
        "title": spec["title"],
        "description": spec["description"],
        # Never trust model-generated starter code, even after the leak
        # check: a clean-looking scaffold can still bias the student toward
        # specific variable names or an approach. Always blank it.
        "starter_code": SAFE_STARTER_CODE,
        "test_cases": test_cases,
    }


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
