"""Run the latex2quiz command line in the browser (Pyodide).

Everything except LaTeX rendering is the unchanged Python implementation.
Rendering is done by the page (TeX compiled to WebAssembly, then pdf.js), so
the renderer below cannot compile anything itself: when a conversion needs a
document rendered, it stops with ``NeedsRendering``.  The page renders that
document, hands the PNG pages back with ``provide_pages``, and runs the same
command again; the renderer then finds the pages and the conversion finishes.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from latex2quiz_lib import cli, package, pdf, render
from latex2quiz_lib.model import ConversionError, RenderedImage, RenderRequest
from latex2quiz_lib.source import parse_questions, parse_written_sections

# The resolution of the images shown in the page.  It is the command line's
# default for QTI, so a QTI conversion after a preview reuses the same images.
PREVIEW_DPI = 192

# Rasterized pages by document hash, then by resolution, in request order.
_pages: Dict[str, Dict[int, List[bytes]]] = {}


class NeedsRendering(Exception):
    """The conversion needs ``document`` rendered at ``resolutions``."""

    def __init__(self, key: str, document: str, resolutions: List[int], page_count: int):
        super().__init__(f"document {key[:12]} must be rendered")
        self.key = key
        self.document = document
        self.resolutions = resolutions
        self.page_count = page_count


def browser_render_latex(
    source_path: Path,
    source: str,
    requests: Sequence[RenderRequest],
    output_dir: Path,
    dpi: int,
    extra_preamble: str = "",
    figure_dpi: Optional[int] = None,
) -> Dict[str, RenderedImage]:
    """Drop-in replacement for ``render.render_latex`` (same signature)."""
    if figure_dpi is None:
        figure_dpi = dpi
    document = render.render_document_source(source, requests, extra_preamble)
    resolutions = render.render_resolutions(requests, dpi, figure_dpi)
    key = hashlib.sha256(document.encode("utf-8")).hexdigest()
    pages = _pages.get(key, {})
    if any(resolution not in pages for resolution in resolutions):
        raise NeedsRendering(key, document, resolutions, len(requests))
    return render.store_rendered_pages(
        requests, {resolution: pages[resolution] for resolution in resolutions},
        output_dir, dpi, figure_dpi,
    )


package.render_latex = browser_render_latex


def run(argv: Sequence[str]) -> dict:
    """Run the command line; return its output, or the document to render."""
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main([str(arg) for arg in argv])
    except NeedsRendering as request:
        return _render_request(request)
    except SystemExit as error:  # argparse reports usage errors this way
        code = error.code if isinstance(error.code, int) else 2
    return {"status": "done", "code": code, "stdout": out.getvalue(), "stderr": err.getvalue()}


def _render_request(request: NeedsRendering) -> dict:
    return {
        "status": "render",
        "key": request.key,
        "document": request.document,
        "resolutions": request.resolutions,
        "pages": request.page_count,
    }


def preview(path, language: str = "da", points: float = 4.0, output_dir=None) -> dict:
    """The problems of a problem set as images, for showing them in the page.

    Returns the document to render, like ``run``, until the page has supplied
    its pages.  Then ``problems`` lists every multiple-choice question (its
    stem, its choices with the correct ones marked, and its explanation) and
    every written problem (its parts and its explanation).  Each image is a
    PNG file in ``output_dir`` with its alternative text and CSS size.
    """
    input_path = Path(str(path))
    folder = Path(str(output_dir)) if output_dir else Path(tempfile.gettempdir()) / "latex2quiz-preview"
    try:
        source = input_path.read_text(encoding="utf-8")
        questions, warnings = parse_questions(source)
        sections = parse_written_sections(source)
        requests = package._render_requests(questions, sections, True, language, points)
        shutil.rmtree(folder, ignore_errors=True)
        images = browser_render_latex(input_path, source, requests, folder, PREVIEW_DPI)
    except NeedsRendering as request:
        return _render_request(request)
    except (ConversionError, OSError, UnicodeError) as error:
        return {"status": "done", "code": 1, "stdout": "", "stderr": f"error: {error}"}

    def image(key: str) -> Optional[dict]:
        rendered = images.get(key)
        if rendered is None:
            return None
        return {
            "path": str(rendered.path), "alt": rendered.alt,
            "width": rendered.width, "height": rendered.height,
        }

    problems: List[dict] = []
    for question in questions:
        qid = f"q{question.number:03d}"
        problems.append({
            "kind": question.kind,
            "parts": [image(f"{qid}-stem")],
            "choices": [
                {"image": image(f"{qid}-answer-{index:03d}"), "correct": answer.correct}
                for index, answer in enumerate(question.answers, start=1)
            ],
            "feedback": image(f"{qid}-feedback"),
        })
    for section in sections:
        qid = f"w{section.number:03d}"
        problems.append({
            "kind": "written",
            "parts": [
                image(f"{qid}-part-{subquestion.number:03d}")
                for subquestion in section.subquestions
            ],
            "choices": [],
            "feedback": image(f"{qid}-feedback"),
        })
    return {
        "status": "done",
        "code": 0,
        "stdout": (
            f"Showing {len(questions)} multiple-choice questions and "
            f"{len(sections)} written problems"
        ),
        "stderr": "".join(f"warning: {warning}\n" for warning in warnings),
        "problems": problems,
        "answer_label": pdf._labels(language)["answer"],
    }


def provide_pages(key: str, resolution: int, pngs) -> None:
    """Store the PNG data of every page of a rendered document."""
    _pages.setdefault(key, {})[int(resolution)] = [
        bytes(png.to_py()) if hasattr(png, "to_py") else bytes(png) for png in pngs
    ]


def failure_message(document: str, log: str) -> str:
    """The command line's error message for a failed LaTeX run."""
    return render.render_failure_message(document, log)
