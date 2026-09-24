"""Arbeitspapier als PDF neu setzen.

    python paper/make_pdf.py

Öffnet die fertige Seite (docs/index.html), liest die Quoten aus Tabelle 1,
schreibt paper/paper.html und druckt es nach docs/arbeitspapier.pdf.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright
from pypdf import PdfReader, PdfWriter

ROOT = Path(__file__).resolve().parents[1]
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]


def main() -> int:
    exe = os.environ.get("CHROMIUM_PATH")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto((ROOT / "docs" / "index.html").as_uri())
        page.wait_for_selector("#tbl-sig tbody tr")
        rows = page.evaluate(
            "() => [...document.querySelectorAll('#tbl-sig tbody tr')].map(r => [...r.cells].map(c => c.textContent.trim()))")
        if len(rows) != 7:
            print("Tabelle 1 unvollständig", rows)
            return 1
        (ROOT / "paper" / "positions.json").write_text(json.dumps({"rows": rows}, ensure_ascii=False))

        # live record: store today's position (automatic runs only), update the page
        weights = page.evaluate("() => window.SAA_MODEL")
        model = json.loads((ROOT / "docs" / "data" / "model.json").read_text())
        sys.path.insert(0, str(ROOT / "src"))
        from saa import track
        if track.record(weights, model["signals"]["as_of"]):
            print("Protokoll: neue Position gespeichert")
        track.performance(model)
        subprocess.run([sys.executable, str(ROOT / "web" / "render.py")], check=True)

        subprocess.run([sys.executable, str(ROOT / "paper" / "build_paper.py")], check=True)
        page.goto((ROOT / "paper" / "paper.html").as_uri())
        page.wait_for_timeout(800)
        raw = page.pdf(format="A4", prefer_css_page_size=True, print_background=True)
        browser.close()

    as_of = json.loads((ROOT / "docs" / "data" / "model.json").read_text())["meta"]["as_of"]
    reader, writer = PdfReader(io.BytesIO(raw)), PdfWriter()
    for pg in reader.pages:
        writer.add_page(pg)
    writer.add_metadata({"/Title": "Bewertung für die Strategie, Trend für die Taktik", "/Author": "Philip Kroos",
                         "/Subject": f"Asset-Allokation für den Euro-Anleger, Stand {MONTHS[int(as_of[5:7]) - 1]} {as_of[:4]}",
                         "/Creator": "", "/Producer": ""})
    with open(ROOT / "docs" / "arbeitspapier.pdf", "wb") as f:
        writer.write(f)
    print(f"docs/arbeitspapier.pdf, {len(reader.pages)} Seiten")
    if len(reader.pages) > 2:
        print("Hinweis: mehr als zwei Seiten")
    return 0


if __name__ == "__main__":
    sys.exit(main())
