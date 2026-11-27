"""Write printable PDFs of a problem set, one question per page.

Each multiple-choice question and each written problem starts on a new page.
The header shows the problem file's name and the page number.  The version
with answers marks the correct choices and prints the explanations.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Sequence, Tuple

from .model import ConversionError, Question, WrittenSection
from .qti import _mc_stem_latex
from .render import document_preamble, render_failure_message
from .source import parse_questions, parse_written_sections

PDF_LABELS = {
    "da": {"page": "Side", "answer": "Svar:", "with_answers": "Med svar"},
    "en": {"page": "Page", "answer": "Answer:", "with_answers": "With answers"},
}

_LATEX_SPECIALS = {
    "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "_": r"\_", "#": r"\#",
    "%": r"\%", "&": r"\&", "$": r"\$", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}


def _latex_escape(text: str) -> str:
    return "".join(_LATEX_SPECIALS.get(character, character) for character in text)


def _labels(language: str) -> dict:
    return PDF_LABELS["da" if language.startswith("da") else "en"]


def pdf_output_paths(input_path: Path, output_dir: Optional[Path] = None) -> Tuple[Path, Path]:
    """The PDFs without and with answers: ``<input>-without-answers.pdf`` and
    ``<input>-with-answers.pdf``, next to the input unless ``output_dir`` is given."""
    folder = output_dir if output_dir is not None else input_path.parent
    return (
        folder / f"{input_path.stem}-without-answers.pdf",
        folder / f"{input_path.stem}-with-answers.pdf",
    )


def _mc_page(
    question: Question, with_answers: bool, include_feedback: bool,
    language: str, default_points: float,
) -> str:
    labels = _labels(language)
    lines = [_mc_stem_latex(question, language, default_points), r"\begin{enumerate}"]
    for answer in question.answers:
        mark = r"\quad\ensuremath{\checkmark}" if with_answers and answer.correct else ""
        lines.append(rf"\item {answer.latex}{mark}")
    lines.append(r"\end{enumerate}")
    if with_answers and include_feedback and question.feedback:
        lines.append(rf"\par\medskip\noindent\textbf{{{labels['answer']}}} {question.feedback}")
    return "\n".join(lines)


def _written_page(
    section: WrittenSection, with_answers: bool, include_feedback: bool, language: str,
) -> str:
    labels = _labels(language)
    lines = [rf"\section*{{{section.title}}}"]
    for subquestion in section.subquestions:
        if subquestion.context:
            lines.append(subquestion.context)
        label = rf"\textbf{{{subquestion.label}}}\quad " if subquestion.label else ""
        lines.append(rf"\par\medskip\noindent {label}{subquestion.prompt}")
        if with_answers and include_feedback and subquestion.feedback:
            lines.append(
                rf"\par\smallskip\noindent\textbf{{{labels['answer']}}} {subquestion.feedback}"
            )
    return "\n\n".join(lines)


def pdf_document_source(
    source: str,
    filename: str,
    questions: Sequence[Question],
    written_sections: Sequence[WrittenSection],
    with_answers: bool,
    language: str = "da",
    default_points: float = 4.0,
    include_feedback: bool = True,
    extra_preamble: str = "",
) -> str:
    """The LaTeX document with one page per question and written problem."""
    labels = _labels(language)
    centre = labels["with_answers"] if with_answers else ""
    pieces = [
        r"\documentclass[12pt]{article}",
        document_preamble(source, extra_preamble),
        r"\makeatletter",
        r"\@ifpackageloaded{geometry}"
        r"{\geometry{a4paper,margin=25mm,headheight=15pt}}"
        r"{\usepackage[a4paper,margin=25mm,headheight=15pt]{geometry}}",
        r"\makeatother",
        r"\usepackage{amssymb}",
        r"\usepackage{fancyhdr}",
        r"\pagestyle{fancy}",
        r"\fancyhf{}",
        rf"\fancyhead[L]{{\texttt{{{_latex_escape(filename)}}}}}",
        rf"\fancyhead[C]{{{centre}}}",
        rf"\fancyhead[R]{{{labels['page']} \thepage}}",
        r"\begin{document}",
    ]
    pages = [
        (f"q{question.number:03d}",
         _mc_page(question, with_answers, include_feedback, language, default_points))
        for question in questions
    ] + [
        (f"w{section.number:03d}",
         _written_page(section, with_answers, include_feedback, language))
        for section in written_sections
    ]
    for index, (key, page) in enumerate(pages):
        if index:
            pieces.append(r"\clearpage")
        pieces.extend([f"% qti-render: {key}", page])
    pieces.append(r"\end{document}")
    return "\n".join(pieces) + "\n"


def compile_pdf(source_path: Path, document: str, output_path: Path) -> None:
    """Compile ``document`` with pdflatex, finding included files next to
    ``source_path``, and write the PDF to ``output_path``."""
    pdflatex = shutil.which("pdflatex")
    if not pdflatex:
        raise ConversionError("Missing required command: pdflatex. Install a TeX distribution.")
    with tempfile.TemporaryDirectory(prefix="latex2quiz-pdf-") as temporary:
        build_dir = Path(temporary)
        (build_dir / "render.tex").write_text(document, encoding="utf-8")
        environment = os.environ.copy()
        texinputs = str(source_path.parent.resolve()) + "//" + os.pathsep
        environment["TEXINPUTS"] = texinputs + environment.get("TEXINPUTS", "")
        result = subprocess.run(
            [pdflatex, "-halt-on-error", "-interaction=nonstopmode", "-file-line-error", "render.tex"],
            cwd=build_dir, env=environment, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, timeout=300,
        )
        pdf = build_dir / "render.pdf"
        if result.returncode != 0 or not pdf.exists():
            raise ConversionError(
                render_failure_message(document, result.stdout).replace(
                    "LaTeX rendering failed", "PDF compilation failed", 1
                )
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pdf, output_path)


def convert_pdf(
    input_path: Path,
    language: str = "da",
    points: float = 4.0,
    include_feedback: bool = True,
    extra_preamble: str = "",
    output_dir: Optional[Path] = None,
) -> Tuple[Path, Path, int, int]:
    """Write the PDFs without and with answers.

    Returns their paths and the numbers of multiple-choice questions and
    written problems.
    """
    try:
        source = input_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConversionError(f"Cannot read {input_path}: {error}") from error
    questions, _ = parse_questions(source)
    written_sections = parse_written_sections(source)
    paths = pdf_output_paths(input_path, output_dir)
    for path, with_answers in zip(paths, (False, True)):
        document = pdf_document_source(
            source, input_path.name, questions, written_sections, with_answers,
            language, points, include_feedback, extra_preamble,
        )
        compile_pdf(input_path, document, path)
    return paths[0], paths[1], len(questions), len(written_sections)
