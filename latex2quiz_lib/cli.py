"""Command-line interface for the LaTeX-to-QTI converter."""
from __future__ import annotations

import argparse
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Optional, Sequence

from .model import ConversionError
from .package import convert
from .source import parse_questions, parse_written_sections

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Convert exam LaTeX multiple-choice and written questions to a "
            "QTI ZIP for Canvas, or to WISEflow's native "
            "Learnosity item JSON."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            r"""
            The recognized source commands are:
              \multiplechoicestart ... \multiplechoiceslut
              \spoergsmaal{title}
              \etsvar or \fleresvar
              \mulighederstart
              \svar answer [\korrekt]
              \mulighederslut
              \forklaring{optional feedback}
              \qtipoints{optional points override}

              \section{written problem title}
              \qtipoints{optional written-section total}
              shared written-problem context
              \punkt{a)}{written prompt}
              \punkt{b)}{\qtipoints{2}prompt worth two points}
              \forklaring{optional feedback}

            English names work as well: \multiplechoiceend, \question,
            \oneanswer, \multipleanswers, \optionsstart, \answer, \correct,
            \optionsend, \explanation, \itxanswer and \subquestion.
            """
        ),
    )
    parser.add_argument("input", type=Path, help="input .tex file")
    parser.add_argument(
        "--format",
        choices=("qti", "learnosity", "both"),
        default="qti",
        help=(
            "qti writes a QTI 2.1 package; learnosity writes WISEflow's "
            "Learnosity item JSON; both writes both (default: qti)"
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help=(
            "output file: the QTI .zip, or the .json file with --format "
            "learnosity (defaults: <input>-qti.zip and <input>-learnosity.json)"
        ),
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help="Learnosity .json file when --format both is used",
    )
    parser.add_argument(
        "--essay-template",
        type=Path,
        help=(
            "a WISEflow item export (.json) whose essay question definition "
            "is copied for written sections instead of Learnosity's longtextV2"
        ),
    )
    parser.add_argument(
        "--essay-images",
        action="store_true",
        help=(
            "in Learnosity output, render each written question as an image "
            "instead of HTML with MathJax"
        ),
    )
    parser.add_argument(
        "--essay-single",
        action="store_true",
        help=(
            "in Learnosity output, give each written section one essay "
            "question and one response field instead of one per \\punkt"
        ),
    )
    parser.add_argument("--title", help="bank title (defaults to the input filename)")
    parser.add_argument("--language", default="da", help="BCP 47 language tag (default: da)")
    parser.add_argument(
        "--points",
        type=float,
        default=4.0,
        help=(
            "default points per MC question or unweighted written subquestion; "
            "overridden by \\qtipoints{...} (default: 4)"
        ),
    )
    parser.add_argument("--dpi", type=int, default=192, help="PNG render resolution for the QTI package (default: 192)")
    parser.add_argument(
        "--html-dpi",
        type=int,
        default=384,
        help=(
            "PNG render resolution for images embedded in Learnosity HTML; the "
            "displayed size is unchanged, only the pixel density (default: 384)"
        ),
    )
    parser.add_argument("--shuffle", action="store_true", help="allow importers to shuffle answers")
    parser.add_argument(
        "--written-lines",
        type=int,
        default=12,
        help="suggested height of written-response fields (default: 12 lines)",
    )
    parser.add_argument("--no-feedback", action="store_true", help="omit \\forklaring feedback")
    parser.add_argument(
        "--preamble",
        type=Path,
        help="append packages or macro definitions from this file while rendering",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate and summarize the source without rendering or writing a package",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.points <= 0:
        parser.error("--points must be greater than zero")
    if not 72 <= args.dpi <= 600:
        parser.error("--dpi must be between 72 and 600")
    if not 72 <= args.html_dpi <= 1200:
        parser.error("--html-dpi must be between 72 and 1200")
    if not 1 <= args.written_lines <= 100:
        parser.error("--written-lines must be between 1 and 100")
    input_path: Path = args.input
    if not input_path.is_file():
        parser.error(f"input file does not exist: {input_path}")

    try:
        source = input_path.read_text(encoding="utf-8")
        questions, warnings = parse_questions(source)
        written_sections = parse_written_sections(source)
        if args.check:
            singles = sum(question.kind == "single" for question in questions)
            multiples = len(questions) - singles
            answers = sum(len(question.answers) for question in questions)
            subquestion_count = sum(
                len(section.subquestions) for section in written_sections
            )
            print(
                f"OK: {len(questions)} multiple-choice questions "
                f"({singles} exactly-one-correct, {multiples} multiple-correct), "
                f"{answers} choices; {len(written_sections)} written sections "
                f"with {subquestion_count} ordered subquestions"
            )
            for warning in warnings:
                print(f"warning: {warning}", file=sys.stderr)
            return 0

        default_zip = input_path.with_name(input_path.stem + "-qti.zip")
        default_json = input_path.with_name(input_path.stem + "-learnosity.json")
        output_path: Optional[Path] = None
        learnosity_path: Optional[Path] = None
        if args.format == "learnosity":
            if args.json_output:
                parser.error("--json-output is only used with --format both")
            learnosity_path = args.output or default_json
        elif args.format == "both":
            output_path = args.output or default_zip
            learnosity_path = args.json_output or default_json
        else:
            if args.json_output:
                parser.error("--json-output is only used with --format both")
            output_path = args.output or default_zip
        if output_path is not None and output_path.suffix.lower() != ".zip":
            parser.error("QTI output filename must end in .zip")
        if learnosity_path is not None and learnosity_path.suffix.lower() != ".json":
            parser.error("Learnosity output filename must end in .json")
        if args.essay_template and learnosity_path is None:
            parser.error("--essay-template requires --format learnosity or both")
        if args.essay_template and not args.essay_template.is_file():
            parser.error(f"essay template does not exist: {args.essay_template}")
        extra_preamble = ""
        if args.preamble:
            extra_preamble = args.preamble.read_text(encoding="utf-8")
        (
            mc_count,
            written_section_count,
            written_subquestion_count,
            image_count,
            warnings,
        ) = convert(
            input_path=input_path,
            output_path=output_path,
            title=args.title or input_path.stem,
            language=args.language,
            points=args.points,
            dpi=args.dpi,
            shuffle=args.shuffle,
            include_feedback=not args.no_feedback,
            extra_preamble=extra_preamble,
            written_lines=args.written_lines,
            learnosity_path=learnosity_path,
            essay_template_path=args.essay_template,
            essay_images=args.essay_images,
            html_dpi=args.html_dpi,
            essay_parts=not args.essay_single,
        )
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
        summary = (
            f"{mc_count} multiple-choice and {written_section_count} written "
            f"items ({written_subquestion_count} ordered subquestions, "
            f"{image_count} images)"
        )
        if output_path is not None:
            print(f"Wrote QTI 2.1 package {output_path} with {summary}")
        if learnosity_path is not None:
            print(f"Wrote Learnosity JSON {learnosity_path} with {summary}")
        return 0
    except (ConversionError, OSError, UnicodeError, subprocess.TimeoutExpired) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

