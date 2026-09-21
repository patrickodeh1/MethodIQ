from fastapi.templating import Jinja2Templates
import json
import re
from html import escape
from markupsafe import Markup
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["loads"] = json.loads


def format_ai_response(value):
    """Render the small Markdown subset commonly returned by the tutor."""
    text = escape(str(value or ""))
    rendered = []
    in_list = False

    def inline_format(line):
        line = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", line)
        return re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", line)

    for raw_line in text.splitlines():
        line = raw_line.strip()
        bullet = re.match(r"^[-*]\s+(.+)$", line)
        if bullet:
            if not in_list:
                rendered.append("<ul>")
                in_list = True
            rendered.append(f"<li>{inline_format(bullet.group(1))}</li>")
            continue
        if in_list:
            rendered.append("</ul>")
            in_list = False
        if line:
            rendered.append(f"<p>{inline_format(line)}</p>")

    if in_list:
        rendered.append("</ul>")
    return Markup("".join(rendered))


templates.env.filters["ai_response"] = format_ai_response
