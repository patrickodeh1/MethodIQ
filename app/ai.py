import json
import re
import httpx

from app.config import GROQ_API_KEY, GROQ_MODEL, GROQ_API_URL
from app.judge import run_function

# ---------------------------------------------------------------------------
# Pipeline overview
# ---------------------------------------------------------------------------
# Tasks are function-call exercises, like LeetCode: the student fills in the
# body of a provided function stub, and hidden tests call that function with
# varied arguments and check the return value. This guarantees real, private
# input variability at every stage of the course - even before a topic
# formally teaches stdin/input(), because function parameters are the input
# channel, not typed keystrokes.
#
# Convention: from the very first topic, the student's code goes inside a
# provided `def entry_function(...):` stub. This is a harness contract, not a
# concept being taught early - the student doesn't need to understand scope,
# default args, or multiple return paths to use it, the same way beginners
# are told to just use print() before they understand streams. The formal
# "Functions" topic later teaches what's actually happening inside the box.
#
# Generation is split into separate calls so nothing can leak the answer into
# public-facing text - each step only ever sees what it needs:
#
#   1. SPEC       -> title, description, entry_function name, param names.
#                    No test data, no starter code (built deterministically
#                    server-side from entry_function + params).
#   2. SOLUTION   -> a private reference implementation of entry_function,
#                    from the spec alone. Never shown to students/admins.
#   3. TEST ARGS  -> sets of keyword arguments only, no expected output
#                    invented.
#   4. EXECUTE    -> call the reference solution for real with each arg set
#                    via judge.run_function(); whatever it returns becomes
#                    expected_json. Test cases are therefore guaranteed
#                    correct, never guessed.
#   5. LEAK CHECK -> deterministic containment check: does any expected
#                    return value appear verbatim in the description? If so,
#                    regenerate only the spec step and re-check.
# ---------------------------------------------------------------------------

SPEC_SYSTEM_PROMPT = """You write ONE coding exercise's public-facing spec for
a self-paced, task-based course, in the style of a LeetCode problem: the
student fills in the body of a function, and hidden tests call it with
varied arguments to check the return value.

You will be given the course's description, the current topic's description
and goal, a hard whitelist of concepts the student is allowed to use, and a
history of tasks already created for this topic (including deleted ones) to
avoid repeating.

Ground rules:
- CRITICAL framing: the student will be given a working function signature
  already filled in for them (e.g. `def process_values(num_str, flag):`),
  with the parameters already holding real values. Their only job is to
  write what happens inside the body and end it with a `return` statement.
  NEVER phrase the description as "write a function that...", "define a
  function named...", or anything implying the student creates the
  function itself - they don't need to know function-definition syntax at
  all if it isn't in their whitelist. Instead phrase it like: "You are
  given num_str and flag. Do X with them and return Y." Treat `return` the
  same way early topics treat print() - a tool they're told to just use,
  not a concept they need to understand deeply yet.
- The whitelist of concepts governs the CORE LOGIC of the task: the actual
  reasoning/computation the exercise is testing must be fully solvable using
  only the whitelist. However, a small, single, discoverable stretch just
  beyond the whitelist is allowed if it's only needed to construct or return
  the final result (e.g. using + to join two already-computed strings, when
  operators are only one topic away) - this kind of gap is a reasonable
  "look this up or ask for help" moment, not a scope violation. Do NOT use
  this allowance to require a whole extra CONCEPT CATEGORY the student has no
  exposure to at all (e.g. writing/defining a function themselves, using a
  data structure like a list/dict when none has been introduced, using a
  loop or conditional when none has been introduced) - that is still a hard
  violation. The distinction: one small, nameable operator or built-in a
  single topic away is fine; an entire untaught category of syntax is not.
- Avoid built-ins whose behavior is a common beginner "gotcha" unless the
  exercise is specifically teaching that gotcha with an explanation. In
  particular: bool() of any non-empty string or non-zero number is always
  True regardless of its content (bool("False") is True, bool("0") is
  True) - never build an exercise around converting a string or number to
  bool as if it reflects the value's apparent meaning.
- If the topic's goal cannot be reasonably achieved within the whitelist plus
  the small-stretch allowance above, write a smaller exercise that stays
  within it.
- You will be told which task number this is within the topic, and given a
  summary of every earlier task already generated for it (title, description,
  and roughly how much it required). Task 1 in a topic must be small and
  test a single concept in isolation - a true on-ramp, not a challenge. Every
  task after the first must be MORE difficult than every earlier task in the
  topic: combine more of the whitelist together, handle more cases, or
  require a longer chain of reasoning, while staying within the same
  whitelist (and the same small-stretch allowance) as the rest of the topic.
  Do not simply produce a same-difficulty variation with different names.
- Do not assume knowledge from topics that come later in the course.
- Match the tone and level of the course/topic descriptions given to you: for
  an absolute-beginner, self-paced course, write a small, concrete, plainly
  worded exercise, not a competitive-programming problem.
- Choose a clear, descriptive entry_function name in snake_case, and 1-4
  short, descriptive parameter names in snake_case. Parameters should be
  simple values (numbers, strings, booleans, or - only if the whitelist
  includes them - lists/dicts), never objects the whitelist hasn't covered.
- Describe the function's required parameters and return value in plain
  language: what each parameter represents, and exactly what the function
  should return. Do NOT include any worked example with concrete argument
  values, a sample calculation, or a specific return value anywhere in the
  description. You do not know the hidden test data yet, and it must stay
  that way: never write example input/output pairs.
- Do not repeat the idea of any task in the provided history; if an earlier
  task used the same basic idea, write a meaningfully different or slightly
  more advanced exercise while staying within the whitelist.
- Output only JSON with exactly these fields: title, description,
  entry_function, params (a list of parameter name strings, in call order).
"""

SOLUTION_SYSTEM_PROMPT = """You write a private reference implementation for
a coding exercise's function. This solution is never shown to students or
admins - it exists only so the grading system can compute correct expected
return values by actually calling it. You will be given the exercise's
title, description, entry_function name, its parameters, and the whitelist
of concepts the student is allowed to use for the body.

Rules:
- Write ONE complete Python function definition named exactly the given
  entry_function, taking exactly the given parameters (in that order), that
  correctly implements what the description asks for and returns the
  required value (never prints it).
- Prefer using only the given whitelist inside the body so the exercise stays
  solvable by a student who only knows those concepts, but prioritize
  correctness if the whitelist is ambiguous or incomplete for the task.
- Avoid built-ins whose behavior is a common beginner "gotcha" unless the
  description explicitly calls for it. In particular, do not convert a
  string or number to bool with bool() expecting it to reflect the value's
  apparent meaning (bool("False") and bool("0") are both True).
- Define nothing except that one function. No prints, no top-level code, no
  example calls.
- Output only JSON with exactly one field: solution_code (a string
  containing the full function definition).
"""

TESTGEN_SYSTEM_PROMPT = """You generate test argument sets for a coding
exercise's function, given its title, description, entry_function name, and
parameters. You do NOT generate expected return values - those are computed
separately by actually calling a reference solution.

Rules:
- Produce at least 5 distinct, varied argument sets that meaningfully
  exercise the behavior described (different values, not just cosmetic
  variants; include simple edge cases where relevant, e.g. zero, empty,
  boundary values, only if they still fit within a beginner-appropriate
  version of the task).
- Each argument set is a JSON object mapping every parameter name to a
  concrete value of the correct type.
- Mark exactly ONE argument set as a sample (is_sample: true); all others
  are is_sample: false.
- Output only JSON with exactly one field: test_args, a list of objects each
  shaped {"args": {...param_name: value...}, "is_sample": true|false}.
"""

_TAG_RE = re.compile(r"<[^>]+>")
_MIN_LEAK_TOKEN_LEN = 3  # ignore trivial/short return values (e.g. "0", "1") in the containment check


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


def _valid_identifier(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""))


def _build_starter_code(entry_function: str, params: list) -> str:
    """Always built server-side from names alone - the model never authors
    starter code, so it cannot hint at an approach, a variable's role, or
    the solution's shape."""
    signature = ", ".join(params)
    return (
        f"def {entry_function}({signature}):\n"
        f"    # Write your solution here.\n"
        f"    pass\n"
    )


def _description_leaks_answer(description: str, test_cases: list) -> bool:
    """Deterministic containment check: does any real return value show up
    verbatim in the public-facing text?"""
    haystack = _strip_html(description).lower()
    for tc in test_cases:
        expected = str(tc.get("expected_json", "")).strip().lower()
        if len(expected) >= _MIN_LEAK_TOKEN_LEN and expected in haystack:
            return True
    return False


def _generate_spec(context_prompt: str) -> dict:
    spec = _call_json(
        SPEC_SYSTEM_PROMPT, context_prompt,
        {"title", "description", "entry_function", "params"},
    )
    params = spec.get("params") or []
    if not isinstance(params, list) or not params or not all(_valid_identifier(p) for p in params):
        raise RuntimeError("AI returned invalid parameter names.")
    if not _valid_identifier(spec.get("entry_function", "")):
        raise RuntimeError("AI returned an invalid entry_function name.")
    return spec


def _generate_solution(title: str, description: str, entry_function: str, params: list, concepts_taught: str) -> str:
    prompt = (
        f"Title: {title}\n"
        f"Description: {description}\n"
        f"entry_function: {entry_function}\n"
        f"params (in order): {', '.join(params)}\n"
        f"Concepts whitelist for the body (prefer these, but be correct above all): "
        f"{concepts_taught or '(none listed)'}\n"
    )
    data = _call_json(SOLUTION_SYSTEM_PROMPT, prompt, {"solution_code"})
    return data["solution_code"]


def _generate_test_args(title: str, description: str, entry_function: str, params: list) -> list:
    prompt = (
        f"Title: {title}\nDescription: {description}\n"
        f"entry_function: {entry_function}\nparams (in order): {', '.join(params)}\n"
    )
    data = _call_json(TESTGEN_SYSTEM_PROMPT, prompt, {"test_args"})
    test_args = data.get("test_args") or []
    if not isinstance(test_args, list) or len(test_args) < 4:
        raise RuntimeError("AI did not return enough test argument sets.")
    return test_args


def _build_test_cases(solution_code: str, entry_function: str, params: list, test_args: list) -> list:
    """Run the reference solution for real against each argument set.
    Expected value is whatever the solution actually returns - never
    guessed."""
    test_cases = []
    sample_seen = False
    for item in test_args:
        args = item.get("args") or {}
        if set(args.keys()) != set(params):
            raise RuntimeError(
                f"Generated test args {list(args.keys())} do not match "
                f"params {params}."
            )
        result = run_function(solution_code, entry_function, args)
        if result["error"] or result["stderr"].strip():
            raise RuntimeError(
                "Reference solution failed to run cleanly on a generated "
                f"argument set: {result['error'] or result['stderr'].strip()}"
            )
        try:
            json.loads(result["stdout"] or "null")
        except json.JSONDecodeError:
            raise RuntimeError("Reference solution's return value was not JSON-serializable.")
        is_sample = bool(item.get("is_sample")) and not sample_seen
        sample_seen = sample_seen or is_sample
        test_cases.append({
            "input_json": json.dumps(args),
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
        f"- Task {i+1}: {task['title']} "
        f"(~{len(_strip_html(task.get('description', '')).split())} words describing it): "
        f"{_strip_html(task.get('description', '')) or '(no description)'}"
        for i, task in enumerate(generated_task_history)
    ) or "(no task has previously been generated for this topic - this will be Task 1)"
    task_number = len(generated_task_history) + 1

    context_prompt = (
        f"Course: {course_name}\n"
        f"Course description: {_strip_html(course_description) or '(none)'}\n\n"
        f"Topics already completed earlier in this course, in order:\n{prior_summary}\n\n"
        f"Current topic: {topic_name}\n"
        f"Current topic description: {_strip_html(topic_description) or '(none)'}\n"
        f"Current topic goal: {stage_goal or '(none)'}\n\n"
        f"Current topic concepts taught (whitelist for the function body; use only these, "
        f"plus the small-stretch allowance described in your instructions): "
        f"{concepts_taught or '(none listed)'}\n\n"
        f"This will be task number {task_number} in this topic. "
        f"{'Make it a small, single-concept on-ramp task.' if task_number == 1 else 'It must be more difficult than every task listed below - do not repeat their difficulty level.'}\n\n"
        f"Existing task titles in this topic (do not repeat): {', '.join(existing_task_titles) or '(none)'}\n\n"
        f"Tasks previously generated for this topic, in order, including deleted ones "
        f"(do not repeat any of their ideas; task {task_number} must be harder than all of them):\n"
        f"{generated_history_summary}\n"
    )

    def _generate_full(prompt):
        spec = _generate_spec(prompt)
        solution_code = _generate_solution(
            spec["title"], spec["description"], spec["entry_function"], spec["params"], concepts_taught,
        )
        test_args = _generate_test_args(
            spec["title"], spec["description"], spec["entry_function"], spec["params"],
        )
        test_cases = _build_test_cases(solution_code, spec["entry_function"], spec["params"], test_args)
        return spec, test_cases

    spec, test_cases = _generate_full(context_prompt)

    if _description_leaks_answer(spec["description"], test_cases):
        # Only the spec step produces public-facing text, so only it can be
        # at fault; regenerate just that, once, before failing outright.
        retry_prompt = (
            context_prompt
            + "\nA previous attempt at this spec leaked a computed return "
              "value into the description. Rewrite the spec so it describes "
              "the parameters and required return value only, with no "
              "example arguments, no sample calculation, and no specific "
              "return value anywhere."
        )
        spec, test_cases = _generate_full(retry_prompt)
        if _description_leaks_answer(spec["description"], test_cases):
            raise RuntimeError(
                "Generated task leaked a return value twice in a row. "
                "The draft was blocked; try generating again."
            )

    return {
        "title": spec["title"],
        "description": spec["description"],
        "entry_function": spec["entry_function"],
        "params": spec["params"],
        "starter_code": _build_starter_code(spec["entry_function"], spec["params"]),
        "test_cases": test_cases,
    }


HINT_SYSTEM_PROMPT = """You are a patient coding tutor. Give clues, questions,
analogies, explanations, and small unrelated examples only. Never provide the
student's exact solution, completed code, a line-by-line patch, the exact
answer, or code that can be copied to solve the task. Never reveal hidden tests.
If asked for the answer, politely refuse and give the next smallest hint. You
may show generic pseudocode or a different example with different names and
values. Keep responses concise and encourage an attempt first.

Response format:
- Use short paragraphs or bullet points.
- Inline code such as `int()` is allowed.
- Never use fenced code blocks.
- Do not write a complete function, a replacement program, or a sequence of
  exact lines the student can copy."""


HINT_REWRITE_PROMPT = """Rewrite the tutor response below into a safe, useful
clue for the student.

Keep the explanation specific to the student's question, but do not provide
the exact solution, completed code, a line-by-line patch, the exact answer, or
any code that can be copied to solve the task. You may keep short inline
references such as `int()` or `type()`, but never use fenced code blocks.
Prefer a short explanation, one diagnostic question, and one next step.
Return only the rewritten tutor response.

Original response:
"""


def _hint_needs_rewrite(answer: str) -> bool:
    """Detect response shapes that are likely to leak a copyable solution."""
    if not answer or len(answer) > 3000 or "```" in answer:
        return True
    lower = answer.lower()
    solution_markers = (
        "here is the corrected code",
        "here's the corrected code",
        "complete solution",
        "replace your code with",
        "copy and paste",
        "def solution(",
    )
    return any(marker in lower for marker in solution_markers)


def _safe_hint_fallback(question: str) -> str:
    """Keep failures useful without exposing a generic or solution-shaped answer."""
    question = " ".join((question or "").split())
    if len(question) > 140:
        question = question[:137] + "..."
    return (
        f"Let’s focus on this part of your question: “{question}” "
        "First identify the value your code has at that point, then compare "
        "it with what the task requires. What does `type()` or a small "
        "temporary print tell you about that value?"
    )


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
    if _hint_needs_rewrite(answer):
        rewrite_messages = [
            {"role": "system", "content": HINT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    HINT_REWRITE_PROMPT
                    + answer[:6000]
                    + "\nStudent question for context:\n"
                    + question[:2000]
                ),
            },
        ]
        try:
            rewritten = _post(rewrite_messages, temperature=0.2).strip()
            if rewritten and not _hint_needs_rewrite(rewritten):
                return rewritten
        except RuntimeError:
            pass
        return _safe_hint_fallback(question)
    return answer.strip()
