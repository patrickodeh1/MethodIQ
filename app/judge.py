import json
import os
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
    Returns {"stdout": str, "stderr": str, "error": str|None}.
    Used for legacy stdin/stdout tasks and the interactive "Run" button."""
    return _execute_script(code, stdin)


def run_function(code: str, entry_function: str, args: dict) -> dict:
    """Run a student's function definition once, calling
    `entry_function(**args)` and capturing its return value as JSON.
    Args are passed via a temp file, never string-embedded, so no value can
    break out of the harness regardless of its content.
    Returns {"stdout": str, "stderr": str, "error": str|None} where stdout,
    if present, is a single line of JSON: the function's return value."""
    with tempfile.TemporaryDirectory() as tmpdir:
        args_path = os.path.join(tmpdir, "args.json")
        with open(args_path, "w") as f:
            json.dump(args, f)
        harness = (
            code.rstrip()
            + "\n\n"
            + "if __name__ == \"__main__\":\n"
            + "    import json as __json\n"
            + f"    with open({args_path!r}) as __f:\n"
            + "        __args = __json.load(__f)\n"
            + f"    if {entry_function!r} not in globals():\n"
            + f"        raise NameError('Function {entry_function} is not defined.')\n"
            + f"    __result = {entry_function}(**__args)\n"
            + "    print(__json.dumps(__result))\n"
        )
        return _execute_script(harness, "", tmpdir=tmpdir)


def _execute_script(code: str, stdin: str, tmpdir: str = None) -> dict:
    def _run(directory):
        script_path = os.path.join(directory, "main.py")
        with open(script_path, "w") as f:
            f.write(code)
        env = {"PATH": "/usr/bin:/bin", "HOME": directory}
        try:
            proc = subprocess.run(
                [PYTHON_BIN, script_path],
                input=stdin, capture_output=True, text=True,
                timeout=RUN_TIMEOUT_SECONDS, cwd=directory, env=env,
                preexec_fn=_limit_resources if hasattr(os, "fork") else None,
            )
            return {"stdout": proc.stdout, "stderr": proc.stderr, "error": None}
        except subprocess.TimeoutExpired:
            return {"stdout": "", "stderr": "", "error": "Execution timed out."}
        except MemoryError:
            return {"stdout": "", "stderr": "", "error": "Execution exceeded memory limit."}
        except Exception as exc:  # noqa: BLE001
            return {"stdout": "", "stderr": "", "error": f"Execution error: {exc}"}

    if tmpdir is not None:
        return _run(tmpdir)
    with tempfile.TemporaryDirectory() as directory:
        return _run(directory)


def judge_submission(code: str, test_cases: list, entry_function: str = "") -> dict:
    """
    Runs code against every test case. Never leaks which specific case
    failed or what its hidden input/expected value was - only a pass count
    and (if the student's own code errored) that error's stderr.

    If `entry_function` is set, this is a function-mode task: test cases'
    input_json is a JSON object of keyword arguments, and expected_json is
    the JSON-encoded expected return value, compared by parsed equality
    (not raw string diff, so e.g. 1.0 vs 1 or key order don't cause false
    failures). If blank, falls back to legacy stdin/stdout mode.
    """
    total = len(test_cases)
    passed_count = 0
    first_error_output = ""
    test_results = []

    for index, tc in enumerate(test_cases, start=1):
        if entry_function:
            try:
                args = json.loads(tc.input_json or "{}")
            except json.JSONDecodeError:
                args = {}
            result = run_function(code, entry_function, args)
        else:
            result = run_code(code, tc.input_json)

        if result["error"]:
            test_results.append({
                "number": index,
                "is_sample": bool(tc.is_sample),
                "input": tc.input_json if tc.is_sample else "",
                "actual": "",
                "expected": tc.expected_json or "",
                "passed": False,
                "error": result["error"],
            })
            return {
                "passed": False, "tests_passed": passed_count, "tests_total": total,
                "error_output": result["error"], "test_results": test_results,
            }

        stderr_text = result["stderr"].strip()
        actual_output = (result["stdout"] or "").strip()

        if entry_function:
            if stderr_text:
                is_match = False
            else:
                try:
                    is_match = json.loads(actual_output) == json.loads(tc.expected_json or "null")
                except json.JSONDecodeError:
                    is_match = False
        else:
            is_match = actual_output == (tc.expected_json or "").strip()

        test_results.append({
            "number": index,
            "is_sample": bool(tc.is_sample),
            "input": tc.input_json if tc.is_sample else "",
            "actual": actual_output,
            "expected": tc.expected_json or "",
            "passed": is_match,
            "error": stderr_text,
        })

        if is_match:
            passed_count += 1
        elif not first_error_output:
            first_error_output = stderr_text

    all_passed = total > 0 and passed_count == total
    return {
        "passed": all_passed, "tests_passed": passed_count, "tests_total": total,
        "error_output": "" if all_passed else first_error_output,
        "test_results": test_results,
    }
