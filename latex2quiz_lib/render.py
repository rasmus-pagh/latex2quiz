"""Render LaTeX fragments as portable PNG question resources."""
from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .model import ConversionError, RenderedImage, RenderRequest
from .source import _extract_body_command_definitions, _extract_preamble

def _render_document(preamble: str, requests: Sequence[RenderRequest]) -> str:
    pieces = [
        r"\documentclass[12pt]{article}",
        preamble,
        r"\usepackage[active,tightpage]{preview}",
        r"\newenvironment{qtiimage}{\noindent\begin{minipage}{160mm}}{\end{minipage}}",
        r"\PreviewEnvironment{qtiimage}",
        # Figures embedded in HTML keep their natural width when varwidth is
        # available; otherwise they are centred in a full-width block.
        r"\IfFileExists{varwidth.sty}"
        r"{\usepackage{varwidth}"
        r"\newenvironment{qtifigure}{\noindent\begin{varwidth}{160mm}}{\end{varwidth}}}"
        r"{\newenvironment{qtifigure}{\noindent\begin{minipage}{160mm}\centering}{\end{minipage}}}",
        r"\PreviewEnvironment{qtifigure}",
        r"\newenvironment{latexqtiimage}{}{}",
        r"\setlength\PreviewBorder{4pt}",
        r"\pagestyle{empty}",
        r"\begin{document}",
    ]
    for request in requests:
        environment = "qtifigure" if request.figure else "qtiimage"
        pieces.extend(
            [
                f"% qti-render: {request.key}",
                rf"\begin{{{environment}}}",
                request.latex,
                rf"\end{{{environment}}}",
            ]
        )
    pieces.append(r"\end{document}")
    return "\n".join(pieces) + "\n"


def _png_dimensions(path: Path) -> Tuple[int, int]:
    data = path.read_bytes()[:24]
    if len(data) != 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ConversionError(f"Renderer produced an invalid PNG: {path}")
    return struct.unpack(">II", data[16:24])


def document_preamble(source: str, extra_preamble: str = "") -> str:
    """The preamble for a document built from ``source``: the source's own (or
    the default one for a fragment), followed by command definitions made in
    the body and ``extra_preamble``."""
    preamble = _extract_preamble(source)
    body_definitions = _extract_body_command_definitions(source)
    if body_definitions:
        preamble += "\n" + body_definitions
    if extra_preamble:
        preamble += "\n" + extra_preamble
    return preamble


def render_document_source(
    source: str, requests: Sequence[RenderRequest], extra_preamble: str = ""
) -> str:
    """The LaTeX document that renders ``requests`` with one page per request."""
    return _render_document(document_preamble(source, extra_preamble), requests)


def render_resolutions(
    requests: Sequence[RenderRequest], dpi: int, figure_dpi: int
) -> List[int]:
    """The resolutions at which the rendered PDF must be rasterized."""
    return sorted({dpi} | {figure_dpi for request in requests if request.figure})


def store_rendered_pages(
    requests: Sequence[RenderRequest],
    pages_at: Mapping[int, Sequence[bytes]],
    output_dir: Path,
    dpi: int,
    figure_dpi: int,
) -> Dict[str, RenderedImage]:
    """Write one PNG per request from the rasterized pages, by resolution.

    ``pages_at[resolution]`` holds the PNG data of every page, in request
    order.  The CSS size of every image is its size at 96 dpi.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    for resolution, pages in pages_at.items():
        if len(pages) != len(requests):
            raise ConversionError(
                f"Expected {len(requests)} rendered pages, but the PDF "
                f"rasterizer produced {len(pages)} at {resolution} dpi"
            )
    rendered: Dict[str, RenderedImage] = {}
    for index, request in enumerate(requests):
        resolution = figure_dpi if request.figure else dpi
        destination = output_dir / f"{request.key}.png"
        destination.write_bytes(pages_at[resolution][index])
        pixel_width, pixel_height = _png_dimensions(destination)
        css_width = max(1, round(pixel_width * 96 / resolution))
        css_height = max(1, round(pixel_height * 96 / resolution))
        rendered[request.key] = RenderedImage(
            destination, request.alt, css_width, css_height
        )
    return rendered


def render_latex(
    source_path: Path,
    source: str,
    requests: Sequence[RenderRequest],
    output_dir: Path,
    dpi: int,
    extra_preamble: str = "",
    figure_dpi: Optional[int] = None,
) -> dict[str, RenderedImage]:
    """Render every request to a PNG and return the images by key.

    Full-width QTI images use ``dpi``; requests flagged as figures (the ones
    embedded in HTML) use ``figure_dpi`` when it is given.  The CSS size of
    every image is its size at 96 dpi, so a higher resolution only raises the
    pixel density.
    """
    if figure_dpi is None:
        figure_dpi = dpi
    pdflatex = shutil.which("pdflatex")
    pdftoppm = shutil.which("pdftoppm")
    if not pdflatex or not pdftoppm:
        missing = ", ".join(
            name
            for name, command in (("pdflatex", pdflatex), ("pdftoppm", pdftoppm))
            if not command
        )
        raise ConversionError(
            f"Missing required rendering command(s): {missing}. "
            "Install a TeX distribution and Poppler."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="latex2quiz-") as temporary:
        build_dir = Path(temporary)
        render_tex = build_dir / "render.tex"
        render_source = render_document_source(source, requests, extra_preamble)
        render_tex.write_text(render_source, encoding="utf-8")

        environment = os.environ.copy()
        texinputs = str(source_path.parent.resolve()) + "//" + os.pathsep
        environment["TEXINPUTS"] = texinputs + environment.get("TEXINPUTS", "")
        command = [
            pdflatex,
            "-halt-on-error",
            "-interaction=nonstopmode",
            "-file-line-error",
            f"-output-directory={build_dir}",
            str(render_tex),
        ]
        result = subprocess.run(
            command,
            cwd=build_dir,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            raise ConversionError(render_failure_message(render_source, result.stdout))

        pdf_path = build_dir / "render.pdf"
        if not pdf_path.exists():
            raise ConversionError("LaTeX completed without producing render.pdf")
        pages_at: Dict[int, List[bytes]] = {}
        for resolution in render_resolutions(requests, dpi, figure_dpi):
            prefix = build_dir / f"page{resolution}"
            raster = subprocess.run(
                [pdftoppm, "-png", "-r", str(resolution), str(pdf_path), str(prefix)],
                cwd=build_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=300,
            )
            if raster.returncode != 0:
                raise ConversionError("PNG rendering failed:\n\n" + raster.stdout.strip())
            pages = sorted(
                build_dir.glob(f"page{resolution}-*.png"),
                key=lambda path: int(re.search(r"(\d+)$", path.stem).group(1)),  # type: ignore[union-attr]
            )
            pages_at[resolution] = [page.read_bytes() for page in pages]
        return store_rendered_pages(requests, pages_at, output_dir, dpi, figure_dpi)


def render_failure_message(render_source: str, compiler_output: str) -> str:
    """Explain a failed LaTeX run, naming the fragment where it stopped."""
    tail = "\n".join(compiler_output.splitlines()[-70:])
    context = ""
    error_lines = re.findall(r"render\.tex:(\d+):", compiler_output)
    if not error_lines:
        error_lines = re.findall(r"^l\.(\d+) ", compiler_output, re.MULTILINE)
    if error_lines:
        error_line = int(error_lines[-1])
        generated_lines = render_source.splitlines()
        for line in reversed(generated_lines[:error_line]):
            if line.startswith("% qti-render: "):
                context = f" while rendering {line[len('% qti-render: '):]}"
                break
    return (
        f"LaTeX rendering failed{context}. "
        "The final compiler output was:\n\n" + tail
    )
