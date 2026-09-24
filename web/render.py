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
track_file = ROOT / "docs" / "data" / "track.json"
track = track_file.read_text().replace("</", "<\\/") if track_file.exists() else "{}"
body = tpl.replace("__MODEL__", model).replace("__TRACK__", track).replace("__APP__", app)
import json as _json
_m = _json.loads((ROOT / "docs" / "data" / "model.json").read_text())
body = body.replace("1990–2026", f"{_m['meta']['sample'][0][:4]}–{_m['meta']['sample'][1][:4]}")

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
art.write_text(body.replace('href="arbeitspapier.pdf"',
                            'href="https://philip-kroos.github.io/strategische-allokation/arbeitspapier.pdf"'))
print(f"wrote {out} and {art}")
