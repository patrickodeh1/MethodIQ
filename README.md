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
a course page, give a topic a learning goal and define its comma-separated
**Concepts taught** whitelist. The whitelist is a hard boundary for generated
tasks: the AI must not use Python keywords, built-ins, data structures, or
constructs outside it. Use the Generate task with AI button to create a draft
task and test cases. Review the draft before saving it; the AI does not publish
anything automatically.

AI-generated task history is retained separately for each topic. If an
administrator later deletes a generated task, future generations still know
what was created and can produce a different or slightly more advanced
exercise instead of repeating it.

The new `topics.concepts_taught` field requires an existing SQLite database to
be recreated or altered manually because the project has no migration tooling.
Either delete `learnplatform.db` before restarting, or run:

```sql
ALTER TABLE topics ADD COLUMN concepts_taught TEXT DEFAULT '';
```

Students can use **Ask a fellow student or AI** from a task. The AI tutor is
configured to provide clues, questions, explanations, and unrelated examples,
not completed solutions or hidden test values. Students are encouraged to make
an attempt and can ask follow-up questions after trying the hint.

Course, topic, and task descriptions use the rich Quill editor.

AI-generated tasks always start with a neutral scaffold:
`# Write your solution here.` The AI is not allowed to provide task-specific
variable names, values, print statements, algorithm steps, or expected output
in starter code. Every task is a complete Python program: test cases provide raw
stdin text and compare the exact stdout text. Students can use **Run code** to
execute the complete Python program in the editor and see its actual output
without creating a submission. **Verify & submit** runs the configured test
cases and records the submission only after verification.

Test cases and expected outputs remain private grading data. Students may see
an example input, but the expected output is never shown on the task page.
After running or verifying, they see the output produced by their own code.
AI-generated tasks are designed around private input values rather than
hard-coded answers. For example, an assignment or conversion task should read
values through `input()`, process them, and print the result; hidden test cases
can then supply different values without exposing the solution in the
description.

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

## Test cases

Every task runs as a normal Python program. Test case input is raw text piped
to standard input, and expected output is the exact text printed to standard
output, compared after surrounding whitespace is stripped.

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
