"""
Seed the Python Programming for Data Science course and its full topic
roadmap. Run from the repo root:

    python -m scripts.seed_python_topics

Idempotent: safe to rerun. Updates existing rows if the seed data below
changes, rather than duplicating them.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, ensure_schema
from app.models import Course, Topic

COURSE = {
    "name": "Python Programming for Data Science",
    "description": (
        "A self-paced, task-based path to the Python foundation needed for "
        "data science. No lectures - a roadmap, curated resources, and "
        "hands-on tasks for every topic, building up to real data cleaning "
        "and analysis work."
    ),
}

# entry_mode: "function" -> student fills a provided `def entry_function(...):`
# stub; hidden tests call it with varied args and check the return value.
# "class" -> student fills a provided class skeleton; hidden tests
# instantiate it and call a method, checking the return value/attribute.
#
# concepts_taught is CUMULATIVE - each topic's list is everything a student
# has been taught by the end of that topic, not just what's new in it.

PYTHON_TOPICS = [
    {
        "order": 0,
        "name": "Variables and Data Types",
        "description": (
            "Every piece of data you'll ever work with in Python has to live "
            "somewhere, and that's what variables are for. You'll create "
            "variables and get familiar with the four core data types you'll "
            "use constantly: integers, floats, strings, and booleans, and "
            "learn how to check and convert between them."
        ),
        "goal": "Create variables of each core type, inspect a value's type with type(), and convert between types with int(), float(), str(), bool().",
        "concepts_taught": "def, return, variables, assignment (=), int, float, str, bool, type(), comments (#)",
        "entry_mode": "function",
        "resources": [
            {"title": "W3Schools - Python Variables", "url": "https://www.w3schools.com/python/python_variables.asp", "note": "How to create and name variables."},
            {"title": "W3Schools - Python Data Types", "url": "https://www.w3schools.com/python/python_datatypes.asp", "note": "Overview of int, float, str, bool and others."},
            {"title": "Real Python - Variables in Python", "url": "https://realpython.com/python-variables/", "note": "Deeper dive into how variables actually work."},
        ],
    },
    {
        "order": 1,
        "name": "Operators",
        "description": (
            "Now that you can store data, you need ways to act on it: "
            "arithmetic to calculate, comparisons to check relationships, "
            "and logical operators to combine conditions."
        ),
        "goal": "Use arithmetic, comparison, and logical operators correctly, and predict the type and value of an expression before running it.",
        "concepts_taught": "def, return, variables, assignment, int, float, str, bool, type(), arithmetic operators (+ - * / // % **), comparison operators (== != > < >= <=), logical operators (and or not), comments",
        "entry_mode": "function",
        "resources": [
            {"title": "W3Schools - Python Operators", "url": "https://www.w3schools.com/python/python_operators.asp", "note": "Full operator reference with examples."},
            {"title": "Real Python - Operators and Expressions", "url": "https://realpython.com/python-operators-expressions/", "note": "Why // and % behave the way they do."},
        ],
    },
    {
        "order": 2,
        "name": "Strings in Depth",
        "description": (
            "Strings are everywhere in data work - names, labels, messy text "
            "you'll later need to clean. Here you'll go beyond just storing "
            "text and learn to slice it, format it, and manipulate it directly."
        ),
        "goal": "Slice, index, format (f-strings), and use core string methods (upper, lower, strip, split, replace, join) confidently.",
        "concepts_taught": "def, return, variables, assignment, int, float, str, bool, type(), operators, string indexing and slicing, f-strings, str methods (upper, lower, strip, split, replace, join, find), comments",
        "entry_mode": "function",
        "resources": [
            {"title": "W3Schools - Python Strings", "url": "https://www.w3schools.com/python/python_strings.asp", "note": "Slicing and basic string operations."},
            {"title": "Real Python - Strings and Character Data", "url": "https://realpython.com/python-strings/", "note": "String methods you'll use constantly for data cleaning later."},
        ],
    },
    {
        "order": 3,
        "name": "Conditional Statements",
        "description": "Programs need to make decisions. You'll learn how to branch your code's behavior based on conditions using if, elif, and else.",
        "goal": "Write correct if/elif/else logic, including nested and chained conditions, to branch behavior based on input values.",
        "concepts_taught": "def, return, variables, assignment, int, float, str, bool, type(), operators, string methods, if/elif/else, indentation blocks, comments",
        "entry_mode": "function",
        "resources": [
            {"title": "W3Schools - Python Conditions", "url": "https://www.w3schools.com/python/python_conditions.asp", "note": "if/elif/else syntax and short-hand forms."},
            {"title": "Real Python - Conditional Statements", "url": "https://realpython.com/python-conditional-statements/", "note": "Truthiness and how Python evaluates conditions."},
        ],
    },
    {
        "order": 4,
        "name": "Loops",
        "description": "Repetition is one of the most powerful things a computer can do that a human can't do efficiently. You'll learn for loops, while loops, and how to control them precisely.",
        "goal": "Write for and while loops, use range(), and control loop execution with break, continue, and pass.",
        "concepts_taught": "def, return, variables, assignment, int, float, str, bool, type(), operators, string methods, if/elif/else, for loops, while loops, range(), break, continue, pass, comments",
        "entry_mode": "function",
        "resources": [
            {"title": "W3Schools - Python For Loops", "url": "https://www.w3schools.com/python/python_for_loops.asp", "note": "for loops and range()."},
            {"title": "W3Schools - Python While Loops", "url": "https://www.w3schools.com/python/python_while_loops.asp", "note": "while loops and loop control."},
        ],
    },
    {
        "order": 5,
        "name": "Lists and Tuples",
        "description": "Real data rarely comes as a single value - it comes as a collection. Lists and tuples are your first structured, ordered containers for data.",
        "goal": "Create, index, slice, and modify lists; use core list methods; understand when to use an immutable tuple instead.",
        "concepts_taught": "def, return, variables, assignment, int, float, str, bool, type(), operators, string methods, conditionals, loops, lists (indexing, slicing, append, remove, sort, len), tuples, comments",
        "entry_mode": "function",
        "resources": [
            {"title": "W3Schools - Python Lists", "url": "https://www.w3schools.com/python/python_lists.asp", "note": "List creation and common methods."},
            {"title": "W3Schools - Python Tuples", "url": "https://www.w3schools.com/python/python_tuples.asp", "note": "Why tuples are immutable and when to use them."},
        ],
    },
    {
        "order": 6,
        "name": "Dictionaries and Sets",
        "description": "Dictionaries let you store data as key-value pairs - exactly how you'll later think about rows, records, and JSON data from APIs. Sets handle unique collections.",
        "goal": "Create and manipulate dictionaries (keys, values, items, get, update) and use sets for uniqueness and membership checks.",
        "concepts_taught": "def, return, variables, assignment, int, float, str, bool, type(), operators, string methods, conditionals, loops, lists, tuples, dictionaries (keys, values, items, get, update, in), sets, comments",
        "entry_mode": "function",
        "resources": [
            {"title": "W3Schools - Python Dictionaries", "url": "https://www.w3schools.com/python/python_dictionaries.asp", "note": "Core dict operations."},
            {"title": "W3Schools - Python Sets", "url": "https://www.w3schools.com/python/python_sets.asp", "note": "Set operations: union, intersection, difference."},
        ],
    },
    {
        "order": 7,
        "name": "Functions in Depth",
        "description": "You've been writing inside function stubs from day one - now you'll learn what's actually happening: how to define your own functions, pass arguments, use defaults, and understand scope.",
        "goal": "Define functions with positional, keyword, and default arguments; understand local vs global scope; use lambda for simple one-line functions.",
        "concepts_taught": "def, return, variables, assignment, all core types, operators, strings, conditionals, loops, lists, tuples, dicts, sets, function definitions with default/keyword args, local/global scope, lambda, comments",
        "entry_mode": "function",
        "resources": [
            {"title": "W3Schools - Python Functions", "url": "https://www.w3schools.com/python/python_functions.asp", "note": "Default and keyword arguments."},
            {"title": "Real Python - Defining Your Own Python Function", "url": "https://realpython.com/defining-your-own-python-function/", "note": "Scope explained clearly."},
        ],
    },
    {
        "order": 8,
        "name": "File Handling",
        "description": "Data has to come from somewhere and go somewhere. You'll learn to read and write text, CSV, and JSON files - the exact formats you'll be loading into pandas soon.",
        "goal": "Read from and write to text, CSV, and JSON files using Python's built-in file handling and the csv/json modules.",
        "concepts_taught": "everything above + open()/with statement, file read/write modes, csv module basics, json module basics (load/dump)",
        "entry_mode": "function",
        "resources": [
            {"title": "W3Schools - Python File Handling", "url": "https://www.w3schools.com/python/python_file_handling.asp", "note": "open(), read(), write(), the with statement."},
            {"title": "Python.org - csv module", "url": "https://docs.python.org/3/library/csv.html", "note": "Reading/writing CSV files without pandas yet."},
            {"title": "Python.org - json module", "url": "https://docs.python.org/3/library/json.html", "note": "Parsing and writing JSON."},
        ],
    },
    {
        "order": 9,
        "name": "Error Handling",
        "description": "Things go wrong - bad input, missing files, unexpected data. You'll learn to anticipate and handle errors gracefully instead of letting your program crash.",
        "goal": "Use try/except/finally to handle common exceptions, and raise custom exceptions when appropriate.",
        "concepts_taught": "everything above + try/except/finally, common exception types (ValueError, TypeError, KeyError, FileNotFoundError), raise",
        "entry_mode": "function",
        "resources": [
            {"title": "W3Schools - Python Try Except", "url": "https://www.w3schools.com/python/python_try_except.asp", "note": "try/except/finally syntax."},
            {"title": "Real Python - Python Exceptions: An Introduction", "url": "https://realpython.com/python-exceptions/", "note": "Common exception types you'll actually hit."},
        ],
    },
    {
        "order": 10,
        "name": "Object-Oriented Programming Basics",
        "description": "Most of the libraries you'll use for data science (pandas DataFrames, scikit-learn models) are built on classes and objects. You'll learn to define your own so you understand what's happening under the hood.",
        "goal": "Define a class with an __init__ method, attributes, and methods; create and use instances.",
        "concepts_taught": "everything above + class, __init__, self, instance attributes, instance methods",
        "entry_mode": "class",
        "resources": [
            {"title": "W3Schools - Python Classes/Objects", "url": "https://www.w3schools.com/python/python_classes.asp", "note": "class, __init__, and self explained simply."},
            {"title": "Real Python - Object-Oriented Programming in Python 3", "url": "https://realpython.com/python3-object-oriented-programming/", "note": "Why OOP matters, with practical examples."},
        ],
    },
    {
        "order": 11,
        "name": "Modules, Packages & Virtual Environments",
        "description": "You're about to start using external libraries like pandas and matplotlib. Before that, you need to understand how Python code is organized into modules and packages, and how to keep project dependencies isolated with virtual environments.",
        "goal": "Import from the standard library, install packages with pip, and create/activate a virtual environment.",
        "concepts_taught": "everything above + import statements, pip install, virtual environments (venv)",
        "entry_mode": "function",
        "resources": [
            {"title": "Real Python - Python Modules and Packages", "url": "https://realpython.com/python-modules-packages/", "note": "The difference between a module and a package."},
            {"title": "Python.org - venv", "url": "https://docs.python.org/3/library/venv.html", "note": "Creating and activating a virtual environment."},
        ],
    },
    {
        "order": 12,
        "name": "Capstone: Python Data Cleaning Script",
        "description": "Before moving into pandas, you'll pull everything together: read a messy raw file, clean and validate it using only core Python, handle errors gracefully, and write the cleaned result back out.",
        "goal": "Combine file I/O, error handling, data structures, and functions to clean a real messy dataset using only core Python.",
        "concepts_taught": "everything above (full Python whitelist)",
        "entry_mode": "function",
        "resources": [
            {"title": "Real Python - Reading and Writing CSV Files in Python", "url": "https://realpython.com/python-csv/", "note": "Refresher before combining everything."},
        ],
    },
]


def run():
    ensure_schema()
    db = SessionLocal()
    try:
        course = db.query(Course).filter(Course.name == COURSE["name"]).first()
        if not course:
            course = Course(name=COURSE["name"], description=COURSE["description"], published=True)
            db.add(course)
            db.flush()
            print(f"Created course: {course.name}")
        elif course.description != COURSE["description"]:
            course.description = COURSE["description"]
            print(f"Updated course description: {course.name}")

        created_count = 0
        updated_count = 0

        for data in PYTHON_TOPICS:
            resources_json = json.dumps(data["resources"])
            topic = (
                db.query(Topic)
                .filter(Topic.course_id == course.id, Topic.order == data["order"])
                .first()
            )
            if not topic:
                topic = Topic(
                    course_id=course.id,
                    order=data["order"],
                    name=data["name"],
                    description=data["description"],
                    goal=data["goal"],
                    concepts_taught=data["concepts_taught"],
                    entry_mode=data["entry_mode"],
                    resources_json=resources_json,
                )
                db.add(topic)
                created_count += 1
                print(f"  Created: Topic {topic.order} - {topic.name}")
                continue

            changed = False
            for field, value in (
                ("name", data["name"]),
                ("description", data["description"]),
                ("goal", data["goal"]),
                ("concepts_taught", data["concepts_taught"]),
                ("entry_mode", data["entry_mode"]),
                ("resources_json", resources_json),
            ):
                if getattr(topic, field) != value:
                    setattr(topic, field, value)
                    changed = True
            if changed:
                updated_count += 1
                print(f"  Updated: Topic {topic.order} - {topic.name}")
            else:
                print(f"  Unchanged: Topic {topic.order} - {topic.name}")

        db.commit()
        print(
            f"\nDone. {created_count} created, {updated_count} updated, "
            f"{len(PYTHON_TOPICS) - created_count - updated_count} unchanged."
        )
    finally:
        db.close()


if __name__ == "__main__":
    run()
