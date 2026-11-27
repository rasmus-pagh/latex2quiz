"""Orchestrate rendering, XML generation, validation, and ZIP packaging."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .alttext import latex_to_plain
from .htmltext import (
    IMAGE_ENVIRONMENT, HtmlConverter, expand_macros, extract_macros,
    figure_latex, section_labels, unwrap_paragraph,
)
from .learnosity import (
    build_bank, build_mc_item, build_written_item, build_written_parts_item,
    load_essay_template,
)
from .model import (
    ConversionError, Question, RenderedImage, RenderRequest, WrittenSection,
)
from .qti import (
    LOM_NS, XSI_NS, _mc_stem_latex, build_item_xml, build_manifest,
    build_written_item_xml,
)
from .render import render_latex
from .source import DEFAULT_PREAMBLE, parse_questions, parse_written_sections

def _write_xml(tree: ET.ElementTree, path: Path) -> None:
    root_tag = tree.getroot().tag
    if root_tag.startswith("{"):
        ET.register_namespace("", root_tag[1:].split("}", 1)[0])
    ET.register_namespace("xsi", XSI_NS)
    ET.register_namespace("lom", LOM_NS)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True, short_empty_elements=True)


def _zip_tree(root: Path, destination: Path) -> None:
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(item for item in root.rglob("*") if item.is_file()):
                relative = path.relative_to(root).as_posix()
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, path.read_bytes())
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def _verify_package_tree(root: Path, expected_items: int) -> None:
    """Check manifest references and XML well-formedness before creating the ZIP."""
    manifest_path = root / "imsmanifest.xml"
    try:
        manifest = ET.parse(manifest_path)
    except (OSError, ET.ParseError) as error:
        raise ConversionError(f"Generated manifest is invalid: {error}") from error
    manifest_namespace = manifest.getroot().tag[1:].split("}", 1)[0]
    resources = manifest.findall(f".//{{{manifest_namespace}}}resource")
    if len(resources) != expected_items:
        raise ConversionError(
            f"Generated manifest contains {len(resources)} item resources; "
            f"expected {expected_items}"
        )
    referenced = {"imsmanifest.xml"}
    for file_element in manifest.findall(f".//{{{manifest_namespace}}}file"):
        href = file_element.get("href", "")
        relative = PurePosixPath(href)
        if not href or relative.is_absolute() or ".." in relative.parts:
            raise ConversionError(f"Generated manifest contains an unsafe href: {href!r}")
        path = root.joinpath(*relative.parts)
        if not path.is_file():
            raise ConversionError(f"Generated manifest references a missing file: {href}")
        referenced.add(relative.as_posix())
        if path.suffix == ".xml":
            try:
                ET.parse(path)
            except ET.ParseError as error:
                raise ConversionError(f"Generated item XML is invalid ({href}): {error}") from error
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    if actual != referenced:
        unreferenced = ", ".join(sorted(actual - referenced))
        raise ConversionError(f"Generated package contains unreferenced files: {unreferenced}")


def _package_identifier(path: Path, source: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", path.stem).strip("-.") or "exam"
    if not slug[0].isalpha():
        slug = "exam-" + slug
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]
    return f"latex2quiz-{slug}-{digest}"


def _written_feedback_latex(section: WrittenSection) -> str:
    parts = [rf"\textbf{{{section.title}}}\par\medskip"]
    for subquestion in section.subquestions:
        if not subquestion.feedback:
            continue
        if subquestion.label:
            parts.append(
                rf"\textbf{{{subquestion.label}}}\quad {subquestion.feedback}"
            )
        else:
            parts.append(subquestion.feedback)
    return "\n\n".join(parts)


def _render_requests(
    questions: Sequence[Question],
    written_sections: Sequence[WrittenSection],
    include_feedback: bool,
    language: str = "da",
    default_points: float = 4.0,
) -> List[RenderRequest]:
    requests: List[RenderRequest] = []
    for question in questions:
        qid = f"q{question.number:03d}"
        stem = _mc_stem_latex(question, language, default_points)
        requests.append(
            RenderRequest(f"{qid}-stem", stem, latex_to_plain(stem))
        )
        for answer_index, answer in enumerate(question.answers, start=1):
            requests.append(
                RenderRequest(
                    f"{qid}-answer-{answer_index:03d}",
                    answer.latex,
                    latex_to_plain(answer.latex),
                )
            )
        if include_feedback and question.feedback:
            requests.append(
                RenderRequest(
                    f"{qid}-feedback",
                    question.feedback,
                    latex_to_plain(question.feedback),
                )
            )
    for section in written_sections:
        qid = f"w{section.number:03d}"
        for subquestion in section.subquestions:
            key = f"{qid}-part-{subquestion.number:03d}"
            stem = subquestion.stem
            requests.append(
                RenderRequest(
                    key,
                    stem,
                    latex_to_plain(stem),
                )
            )
        if include_feedback and any(
            subquestion.feedback for subquestion in section.subquestions
        ):
            feedback = _written_feedback_latex(section)
            requests.append(
                RenderRequest(
                    f"{qid}-feedback", feedback, latex_to_plain(feedback)
                )
            )
    return requests


def _html_fragments(
    source: str,
    questions: Sequence[Question],
    written_sections: Sequence[WrittenSection],
    include_feedback: bool,
    language: str,
    essay_images: bool = False,
    essay_parts: bool = True,
    default_points: float = 4.0,
) -> Dict[str, str]:
    """Macro-expanded LaTeX for every fragment the HTML export converts.

    With ``essay_images`` every written stem is wrapped so that it is
    rendered as one image instead of converted to HTML.  With
    ``essay_parts`` each part's feedback is a fragment of its own instead of
    the combined section feedback.
    """
    # The default preamble's \providecommand macros, overridden by the source's own.
    macros = {**extract_macros(DEFAULT_PREAMBLE), **extract_macros(source)}
    fragments: Dict[str, str] = {}
    for question in questions:
        qid = f"q{question.number:03d}"
        fragments[f"{qid}-stem"] = _mc_stem_latex(question, language, default_points)
        for answer_index, answer in enumerate(question.answers, start=1):
            fragments[f"{qid}-answer-{answer_index:03d}"] = answer.latex
        if include_feedback and question.feedback:
            fragments[f"{qid}-feedback"] = question.feedback
    for section in written_sections:
        qid = f"w{section.number:03d}"
        for subquestion in section.subquestions:
            stem = subquestion.stem
            if essay_images:
                stem = (
                    rf"\begin{{{IMAGE_ENVIRONMENT}}}" + "\n" + stem + "\n"
                    + rf"\end{{{IMAGE_ENVIRONMENT}}}"
                )
            fragments[f"{qid}-part-{subquestion.number:03d}"] = stem
            if include_feedback and essay_parts and subquestion.feedback:
                fragments[f"{qid}-part-{subquestion.number:03d}-feedback"] = (
                    subquestion.feedback
                )
        if include_feedback and not essay_parts and any(
            subquestion.feedback for subquestion in section.subquestions
        ):
            fragments[f"{qid}-feedback"] = _written_feedback_latex(section)
    return {key: expand_macros(latex, macros) for key, latex in fragments.items()}


def _figure_key(key: str, index: int) -> str:
    return f"{key}-figure-{index:03d}"


def _figure_requests(fragments: Dict[str, str]) -> List[RenderRequest]:
    """Render requests for the constructs HTML cannot express."""
    requests: List[RenderRequest] = []
    for key, latex in fragments.items():
        for index, figure in enumerate(figure_latex(latex), start=1):
            requests.append(
                RenderRequest(
                    _figure_key(key, index),
                    figure,
                    latex_to_plain(figure),
                    figure=True,
                )
            )
    return requests


def _fragment_html(
    key: str,
    fragments: Dict[str, str],
    rendered: Dict[str, RenderedImage],
    unknown: Set[str],
    labels: Optional[Dict[str, str]] = None,
) -> str:
    images: List[RenderedImage] = []
    index = 1
    while _figure_key(key, index) in rendered:
        images.append(rendered[_figure_key(key, index)])
        index += 1
    converter = HtmlConverter(images, labels)
    markup = converter.convert(fragments[key])
    unknown.update(converter.unknown)
    return markup


def build_learnosity_bank(
    questions: Sequence[Question],
    written_sections: Sequence[WrittenSection],
    fragments: Dict[str, str],
    rendered: Dict[str, RenderedImage],
    default_points: float,
    shuffle: bool,
    digest: str,
    essay_template: Optional[Dict[str, object]] = None,
    labels: Optional[Dict[str, str]] = None,
    essay_parts: bool = True,
) -> Tuple[Dict[str, object], Set[str]]:
    unknown: Set[str] = set()
    items: List[Dict[str, object]] = []

    def html_of(key: str) -> str:
        return _fragment_html(key, fragments, rendered, unknown, labels)
    for question in questions:
        qid = f"q{question.number:03d}"
        options = [
            unwrap_paragraph(
                html_of(f"{qid}-answer-{index:03d}")
            )
            for index in range(1, len(question.answers) + 1)
        ]
        feedback_key = f"{qid}-feedback"
        items.append(
            build_mc_item(
                question,
                html_of(f"{qid}-stem"),
                options,
                html_of(feedback_key)
                if feedback_key in fragments
                else None,
                default_points,
                shuffle,
                digest,
            )
        )
    for section in written_sections:
        qid = f"w{section.number:03d}"
        if essay_parts:
            part_keys = [
                f"{qid}-part-{subquestion.number:03d}"
                for subquestion in section.subquestions
            ]
            items.append(
                build_written_parts_item(
                    section,
                    [html_of(key) for key in part_keys],
                    [
                        html_of(f"{key}-feedback") if f"{key}-feedback" in fragments else None
                        for key in part_keys
                    ],
                    default_points,
                    digest,
                    essay_template,
                )
            )
            continue
        stimulus = "".join(
            html_of(f"{qid}-part-{subquestion.number:03d}")
            for subquestion in section.subquestions
        )
        feedback_key = f"{qid}-feedback"
        items.append(
            build_written_item(
                section,
                stimulus,
                html_of(feedback_key)
                if feedback_key in fragments
                else None,
                default_points,
                digest,
                essay_template,
            )
        )
    return build_bank(items), unknown


def _write_json(bank: Dict[str, object], path: Path) -> None:
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(
            json.dumps(bank, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def convert(
    input_path: Path,
    output_path: Optional[Path],
    title: str,
    language: str,
    points: float,
    dpi: int,
    shuffle: bool,
    include_feedback: bool,
    extra_preamble: str,
    written_lines: int = 12,
    learnosity_path: Optional[Path] = None,
    essay_template_path: Optional[Path] = None,
    essay_images: bool = False,
    html_dpi: Optional[int] = None,
    essay_parts: bool = True,
) -> Tuple[int, int, int, int, List[str]]:
    """Write a QTI package to ``output_path`` and/or Learnosity JSON.

    Either destination may be ``None`` to skip that format.  The returned
    image count covers both formats.
    """
    if output_path is None and learnosity_path is None:
        raise ConversionError("No output format selected")
    essay_template: Optional[Dict[str, object]] = None
    if learnosity_path is not None and essay_template_path is not None:
        essay_template = load_essay_template(essay_template_path)
    try:
        source = input_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConversionError(f"Cannot read {input_path}: {error}") from error
    questions, warnings = parse_questions(source)
    written_sections = parse_written_sections(source)
    requests: List[RenderRequest] = []
    if output_path is not None:
        requests.extend(
            _render_requests(
                questions, written_sections, include_feedback, language, points
            )
        )
    fragments: Dict[str, str] = {}
    if learnosity_path is not None:
        fragments = _html_fragments(
            source, questions, written_sections, include_feedback, language,
            essay_images, essay_parts, points,
        )
        requests.extend(_figure_requests(fragments))

    for destination in (output_path, learnosity_path):
        if destination is not None:
            destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="latex2quiz-package-") as temporary:
        package_dir = Path(temporary)
        items_dir = package_dir / "items"
        assets_dir = items_dir / "assets"
        assets_dir.parent.mkdir(parents=True, exist_ok=True)
        rendered: Dict[str, RenderedImage] = {}
        if requests:
            rendered = render_latex(
                input_path, source, requests, assets_dir, dpi, extra_preamble,
                figure_dpi=html_dpi,
            )
        identifier = _package_identifier(input_path, source + "\n" + title)
        if learnosity_path is not None:
            bank, unknown = build_learnosity_bank(
                questions,
                written_sections,
                fragments,
                rendered,
                points,
                shuffle,
                identifier.rsplit("-", 1)[-1],
                essay_template,
                section_labels(source),
                essay_parts,
            )
            if unknown:
                names = ", ".join("\\" + name for name in sorted(unknown))
                warnings.append(
                    "Learnosity HTML: unrecognized LaTeX command(s) dropped, "
                    f"keeping any braced argument as text: {names}"
                )
            _write_json(bank, learnosity_path)
        if output_path is None:
            subquestion_count = sum(
                len(section.subquestions) for section in written_sections
            )
            return (
                len(questions),
                len(written_sections),
                subquestion_count,
                len(requests),
                warnings,
            )
        items_dir.mkdir(parents=True, exist_ok=True)
        for question in questions:
            qid = f"q{question.number:03d}"
            tree = build_item_xml(
                question,
                rendered,
                points,
                language,
                shuffle,
                include_feedback,
            )
            _write_xml(tree, items_dir / f"{qid}.xml")
        for section in written_sections:
            qid = f"w{section.number:03d}"
            tree = build_written_item_xml(
                section,
                rendered,
                points,
                language,
                include_feedback,
                written_lines,
            )
            _write_xml(tree, items_dir / f"{qid}.xml")
        manifest = build_manifest(
            identifier,
            questions,
            written_sections,
            include_feedback,
            title=title,
            language=language,
        )
        expected_resources = len(questions) + len(written_sections)
        _write_xml(manifest, package_dir / "imsmanifest.xml")
        for request in requests:
            if request.figure:
                (assets_dir / f"{request.key}.png").unlink()
        _verify_package_tree(package_dir, expected_resources)
        _zip_tree(package_dir, output_path)
    subquestion_count = sum(
        len(section.subquestions) for section in written_sections
    )
    return (
        len(questions),
        len(written_sections),
        subquestion_count,
        len(requests),
        warnings,
    )

