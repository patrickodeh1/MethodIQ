# MethodIQ

Admins create courses -> topics -> tasks -> hidden test cases. Students
(added manually by admin, phone-number-only login, course assigned
separately after registration) work through tasks in order, submit code,
and get pass/fail feedback without the hidden test values ever being shown.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

`/admin/login` - admin panel. `/login` - student login (phone number only).

Set `GROQ_API_KEY` in `.env` to enable the **Generate task with AI** button. On
a course page, give a topic a learning goal and use that button to create a
draft task and test cases. Review the draft before saving it; the AI does not
publish anything automatically.

Students can use **Ask a fellow student or AI** from a task. The AI tutor is
configured to provide clues, questions, explanations, and unrelated examples,
not completed solutions or hidden test values. Students are encouraged to make
an attempt and can ask follow-up questions after trying the hint.

Course, topic, and task descriptions use the rich Quill editor. Tasks support
two to five research resources; each resource has a URL and a short guide
explaining what the student should research.

The built-in admin account has complete access. Admins can create staff
accounts from the dashboard and select dashboard, course, task, and student
permissions for each staff member.

The admin dashboard also includes an audit log of platform requests by students
and staff, plus a per-student prompt history view for AI help conversations.

Staff sign in at `/admin/login` using the username and temporary password created
by an administrator, then use the separate `/staff` dashboard. Staff access is
fixed in code: they can create students, read courses and tasks, and publish
tasks. They cannot edit or delete curriculum, delete students, or publish or
unpublish courses. Administrators retain complete access, including publishing
and unpublishing courses and tasks.

Administrators manage staff accounts from `/admin/staff`, which is separate from
the main course dashboard.

Students can be enrolled in multiple courses. Administrators select one or more
courses for each student from the student management page. The student dashboard
shows all enrolled published courses with their descriptions, and progress is
combined across the published tasks in those courses.

Nigerian phone numbers are stored and matched canonically. For example,
`09157250018`, `2349157250018`, and `+2349157250018` identify the same student.

## Test case modes (per task)

Each Task has an `entry_type`: `stdin`, `function`, or `class`.

- **stdin** (legacy/simple): the student's whole file runs as a program.
  TestCase.input_json is raw text piped to stdin; TestCase.expected_json is
  the raw text expected on stdout (compared after stripping whitespace).
  Good for tasks like "read a number, print FizzBuzz output".

- **function** (LeetCode-style): student defines a plain function, e.g.
  `def is_even(n): ...`. Task.entry_function = "is_even". TestCase.input_json
  is a JSON array of positional arguments, e.g. `[2]` or `[2, 3]` or
  `[[1,2,3]]` (a single list argument). TestCase.expected_json is the
  expected return value as JSON, e.g. `true`, `5`, `[1,2,3]`. The judge
  calls `is_even(*args)`, JSON-serializes the return value, and compares.

- **class** (LeetCode-style OOP): student defines a class, e.g.
  `class Solution: def twoSum(self, nums, target): ...`. Task.class_name =
  "Solution", Task.entry_function = "twoSum". The judge instantiates the
  class with no constructor args, then calls the method the same way as
  function mode.

Only JSON-representable values work for function/class mode (numbers,
strings, booleans, null, lists, dicts) - matches how LeetCode itself
represents test cases, and avoids eval() on admin input.

## Ask for help

On a locked-in-progress task, students can open "Ask for help" to see other
students (in the same course) who have already passed that task, with a
WhatsApp link (built from their registered phone number) and a template
message reminding them to ask politely and describe their specific issue.
No other student data is exposed.

## Code execution sandbox

`app/judge.py` runs student code via `subprocess`, not Docker/Piston -
lighter on a small/low-RAM server. It caps CPU time, memory (RLIMIT_AS),
and process count, and runs with a timeout. This is adequate isolation for
a small trusted group of your own students, not a hardened multi-tenant
sandbox. See SANDBOX_USER in .env for an extra (optional) isolation step.
