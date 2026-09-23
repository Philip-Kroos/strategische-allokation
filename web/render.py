"""Inline model.json and app.js into the page template.

docs/index.html      full HTML document for GitHub Pages
build/artifact.html  body-only variant for hosts that supply their own skeleton
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
tpl = (ROOT / "web" / "template.html").read_text()
model = (ROOT / "docs" / "data" / "model.json").read_text().replace("</", "<\\/")
app = (ROOT / "web" / "app.js").read_text()
check = (ROOT / "web" / "check.js").read_text()
marker = "  // portfolio check and tactical signals (web/check.js is inserted here)"
app = app.replace(marker, marker + "\n" + check)
body = tpl.replace("__MODEL__", model).replace("__APP__", app)

head_end = body.index("</style>") + len("</style>")
page = (
    '<!doctype html>\n<html lang="de">\n<head>\n<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
    + body[:head_end] + "\n</head>\n<body>\n" + body[head_end:] + "\n</body>\n</html>\n"
)
out = ROOT / "docs" / "index.html"
out.write_text(page)
art = ROOT / "build" / "artifact.html"
art.parent.mkdir(exist_ok=True)
art.write_text(body)
print(f"wrote {out} and {art}")
