import os
import json
import resource
import subprocess
import tempfile

from app.config import PYTHON_BIN, RUN_TIMEOUT_SECONDS, RUN_MEMORY_LIMIT_MB, SANDBOX_USER


def _limit_resources():
    """Runs in the child process before exec'ing python3. Lightweight
    sandbox: CPU/memory/process caps. Adequate for a small trusted group of
    students, not a hardened multi-tenant sandbox."""
    resource.setrlimit(resource.RLIMIT_CPU, (RUN_TIMEOUT_SECONDS, RUN_TIMEOUT_SECONDS))
    mem_bytes = RUN_MEMORY_LIMIT_MB * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
    try:
        resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
    except (ValueError, OSError):
        pass
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if SANDBOX_USER:
        import pwd
        pw = pwd.getpwnam(SANDBOX_USER)
        os.setgid(pw.pw_gid)
        os.setuid(pw.pw_uid)


def run_code(code: str, stdin: str) -> dict:
    """Run `code` once against `stdin` in a subprocess.
    Returns {"stdout": str, "stderr": str, "error": str|None}."""
    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = os.path.join(tmpdir, "main.py")
        with open(script_path, "w") as f:
            f.write(code)
        env = {"PATH": "/usr/bin:/bin", "HOME": tmpdir}
        try:
            proc = subprocess.run(
                [PYTHON_BIN, script_path],
                input=stdin, capture_output=True, text=True,
                timeout=RUN_TIMEOUT_SECONDS, cwd=tmpdir, env=env,
                preexec_fn=_limit_resources if hasattr(os, "fork") else None,
            )
            return {"stdout": proc.stdout, "stderr": proc.stderr, "error": None}
        except subprocess.TimeoutExpired:
            return {"stdout": "", "stderr": "", "error": "Execution timed out."}
        except MemoryError:
            return {"stdout": "", "stderr": "", "error": "Execution exceeded memory limit."}
        except Exception as exc:  # noqa: BLE001
            return {"stdout": "", "stderr": "", "error": f"Execution error: {exc}"}


def _build_call_harness(student_code: str, entry_type: str, entry_function: str,
                         class_name: str, args_json: str) -> str:
    """
    LeetCode-style harness: embeds the raw JSON args text safely (via repr,
    so we never worry about quote-escaping), parses it with json.loads
    inside the sandboxed process, calls the student's function/method, and
    prints the JSON-serialized return value for comparison.
    """
    args_literal = repr(args_json)
    if entry_type == "class":
        call = (
            f"__obj = {class_name}()\n"
            f"__result = __obj.{entry_function}(*__args)\n"
        )
    else:
        call = f"__result = {entry_function}(*__args)\n"

    return (
        f"{student_code}\n\n"
        f"import json\n"
        f"__args = json.loads({args_literal})\n"
        f"{call}"
        f"print(json.dumps(__result))\n"
    )


def judge_submission(code: str, test_cases: list, entry_type: str = "stdin",
                      entry_function: str = "", class_name: str = "") -> dict:
    """
    Runs code against every test case. Never leaks which specific case
    failed or what its hidden input/expected value was - only a pass count
    and (if the student's own code errored) that error's stderr.
    """
    total = len(test_cases)
    passed_count = 0
    first_error_output = ""
    test_results = []

    for index, tc in enumerate(test_cases, start=1):
        if entry_type in ("function", "class"):
            harness = _build_call_harness(code, entry_type, entry_function, class_name, tc.input_json)
            result = run_code(harness, "")
        else:
            harness = code
            result = run_code(harness, tc.input_json)

        if result["error"]:
            test_results.append({
                "number": index,
                "is_sample": bool(tc.is_sample),
                "input": tc.input_json if tc.is_sample else "",
                "actual": "",
                "passed": False,
                "error": result["error"],
            })
            return {
                "passed": False, "tests_passed": passed_count, "tests_total": total,
                "error_output": result["error"], "test_results": test_results,
            }

        actual_output = (result["stdout"] or "").strip()
        if entry_type in ("function", "class"):
            try:
                actual_value = json.loads(actual_output) if actual_output else None
                expected_value = json.loads(tc.expected_json.strip()) if tc.expected_json.strip() else None
                is_match = actual_value == expected_value
            except (json.JSONDecodeError, ValueError):
                is_match = False
        else:
            is_match = actual_output == (tc.expected_json or "").strip()

        test_results.append({
            "number": index,
            "is_sample": bool(tc.is_sample),
            "input": tc.input_json if tc.is_sample else "",
            "actual": actual_output,
            "passed": is_match,
            "error": result["stderr"].strip() if result["stderr"].strip() else "",
        })

        if is_match:
            passed_count += 1
        elif not first_error_output:
            first_error_output = result["stderr"].strip()

    all_passed = total > 0 and passed_count == total
    return {
        "passed": all_passed, "tests_passed": passed_count, "tests_total": total,
        "error_output": "" if all_passed else first_error_output,
        "test_results": test_results,
    }
