from fastapi.templating import Jinja2Templates
import json
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["loads"] = json.loads
