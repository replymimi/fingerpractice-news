"""Render templates/index_template.html with data/processed/summary.json
into docs/index.html (GitHub Pages serves the repo's /docs folder)."""
import os
import sys
from datetime import datetime

from jinja2 import Environment, FileSystemLoader

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, DATA_DIR, TAIPEI, log, load_json

DOCS_DIR = os.path.join(ROOT, "docs")
TEMPLATE_DIR = os.path.join(ROOT, "templates")


def time_label(iso):
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TAIPEI)
        return dt.strftime("%H:%M")
    except Exception:
        return "—"


def annotate_time_labels(items):
    for it in items:
        it["time_label"] = time_label(it.get("published_iso"))
    return items


def main():
    summary = load_json(os.path.join(DATA_DIR, "processed", "summary.json"))
    if not summary:
        raise SystemExit("summary.json missing — run summarize.py first")

    for col in ("stocks", "crypto"):
        annotate_time_labels(summary["news"].get(col, []))
        annotate_time_labels(summary["youtube"].get(col, []))
        for it in summary["youtube"].get(col, []):
            if it["source"] == "游庭皓的財經號角":
                it["supplemental_note"] = "10:00 補充"

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    template = env.get_template("index_template.html")
    html_out = template.render(**summary)

    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(os.path.join(DOCS_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html_out)
    log(f"docs/index.html written ({len(html_out)} bytes)")


if __name__ == "__main__":
    main()
