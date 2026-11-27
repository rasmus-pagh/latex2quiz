"""Build QTI 2.1 assessment-item and package-manifest XML."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from decimal import Decimal
from typing import List, Optional, Sequence

from .alttext import latex_to_plain
from .model import Question, RenderedImage, WrittenSection

QTI_NS = "http://www.imsglobal.org/xsd/imsqti_v2p1"
IMSCP_NS = "http://www.imsglobal.org/xsd/imscp_v1p1"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
XML_NS = "http://www.w3.org/XML/1998/namespace"
LOM_NS = "http://ltsc.ieee.org/xsd/LOM"
QTI_SCHEMA = "http://www.imsglobal.org/xsd/qti/qtiv2p1/imsqti_v2p1p2.xsd"
PACKAGE_SCHEMA = (
    "http://www.imsglobal.org/xsd/qti/qtiv2p1/"
    "qtiv2p1_imscpv1p2_v1p0.xsd"
)

def _qti(tag: str) -> str:
    return f"{{{QTI_NS}}}{tag}"


def _imscp(tag: str) -> str:
    return f"{{{IMSCP_NS}}}{tag}"


def _number(value: float) -> str:
    return f"{value:.12g}"


def _split_mapping_total(total: float, count: int) -> List[str]:
    """Split a score into serialized values whose decimal sum is exact."""
    if count <= 0:
        return []
    decimal_total = Decimal(_number(total))
    share = Decimal(_number(total / count))
    values = [share] * (count - 1)
    values.append(decimal_total - sum(values, Decimal(0)))
    return [format(value, "f") for value in values]


def _effective_points(explicit: Optional[float], default: float) -> float:
    return explicit if explicit is not None else default


def _has_percentage(title: str) -> bool:
    return re.search(r"\(\s*[0-9.]+\s*\\?%\s*\)\s*$", title) is not None


def mc_title_latex(question: Question, default_points: float) -> str:
    r"""The printed title in LaTeX: ``\spoergsmaal`` appends ``(4\%)``."""
    if _has_percentage(question.title):
        return question.title
    points = _effective_points(question.points, default_points)
    return rf"{question.title} ({points:g}\%)"


def mc_title(question: Question, default_points: float) -> str:
    """The printed title as plain text, for item titles."""
    return latex_to_plain(mc_title_latex(question, default_points))


def _mc_instruction(question: Question, language: str) -> str:
    if language.startswith("da"):
        if question.kind == "single":
            return "Der er præcis ét korrekt svar, men du må vælge flere."
        return "Vælg ét eller flere korrekte svar."
    if question.kind == "single":
        return "Exactly one answer is correct, but you may select more than one if you are in doubt."
    return "Select one or more correct answers."


def _mc_stem_latex(
    question: Question, language: str, default_points: float = 4.0
) -> str:
    """The question text with its heading first and the instruction last."""
    return (
        heading_latex(mc_title_latex(question, default_points))
        + question.stem
        + r"\par\medskip\noindent "
        + _mc_instruction(question, language)
    )


def heading_latex(title: str) -> str:
    r"""A question heading: ``\section*`` is large and bold in the image and
    becomes an ``<h3>`` in HTML."""
    return rf"\section*{{{title}}}" + "\n\n"


def _add_image(parent: ET.Element, image: RenderedImage, relative_path: str) -> None:
    wrapper = ET.SubElement(parent, _qti("div"))
    ET.SubElement(
        wrapper,
        _qti("img"),
        {
            "src": relative_path,
            "alt": image.alt,
            "width": str(image.width),
            "height": str(image.height),
        },
    )


def build_item_xml(
    question: Question,
    rendered: dict[str, RenderedImage],
    default_points: float,
    language: str,
    shuffle: bool,
    include_feedback: bool,
) -> ET.ElementTree:
    qid = f"q{question.number:03d}"
    points = _effective_points(question.points, default_points)
    root = ET.Element(
        _qti("assessmentItem"),
        {
            "identifier": qid,
            "title": mc_title(question, default_points),
            "adaptive": "false",
            "timeDependent": "false",
            f"{{{XML_NS}}}lang": language,
            f"{{{XSI_NS}}}schemaLocation": f"{QTI_NS} {QTI_SCHEMA}",
        },
    )

    declaration = ET.SubElement(
        root,
        _qti("responseDeclaration"),
        {"identifier": "RESPONSE", "cardinality": "multiple", "baseType": "identifier"},
    )
    correct_response = ET.SubElement(declaration, _qti("correctResponse"))
    for answer_index, answer in enumerate(question.answers, start=1):
        if answer.correct:
            ET.SubElement(correct_response, _qti("value")).text = (
                f"{qid}_a{answer_index:03d}"
            )

    mapping_attributes = {
        "defaultValue": "0",
        "upperBound": _number(points),
        "lowerBound": _number(-points),
    }
    mapping = ET.SubElement(declaration, _qti("mapping"), mapping_attributes)
    correct_count = sum(answer.correct for answer in question.answers)
    incorrect_count = len(question.answers) - correct_count
    correct_values = iter(_split_mapping_total(points, correct_count))
    incorrect_values = iter(_split_mapping_total(-points, incorrect_count))
    for answer_index, answer in enumerate(question.answers, start=1):
        if answer.correct:
            mapped_value = next(correct_values)
        elif incorrect_count:
            mapped_value = next(incorrect_values)
        else:
            mapped_value = "0"
        ET.SubElement(
            mapping,
            _qti("mapEntry"),
            {
                "mapKey": f"{qid}_a{answer_index:03d}",
                "mappedValue": mapped_value,
            },
        )

    outcome = ET.SubElement(
        root,
        _qti("outcomeDeclaration"),
        {
            "identifier": "SCORE",
            "cardinality": "single",
            "baseType": "float",
            "normalMaximum": _number(points),
            "normalMinimum": _number(-points),
        },
    )
    default_value = ET.SubElement(outcome, _qti("defaultValue"))
    ET.SubElement(default_value, _qti("value")).text = "0"

    has_feedback = include_feedback and question.feedback is not None
    if has_feedback:
        ET.SubElement(
            root,
            _qti("outcomeDeclaration"),
            {"identifier": "FEEDBACK", "cardinality": "single", "baseType": "identifier"},
        )

    body = ET.SubElement(root, _qti("itemBody"))
    _add_image(body, rendered[f"{qid}-stem"], f"assets/{qid}-stem.png")
    interaction = ET.SubElement(
        body,
        _qti("choiceInteraction"),
        {
            "responseIdentifier": "RESPONSE",
            "shuffle": "true" if shuffle else "false",
            "maxChoices": str(len(question.answers)),
            "minChoices": "0",
        },
    )
    for answer_index, _answer in enumerate(question.answers, start=1):
        aid = f"{qid}_a{answer_index:03d}"
        choice = ET.SubElement(
            interaction,
            _qti("simpleChoice"),
            {"identifier": aid, "fixed": "false" if shuffle else "true"},
        )
        _add_image(choice, rendered[f"{qid}-answer-{answer_index:03d}"], f"assets/{qid}-answer-{answer_index:03d}.png")

    if has_feedback:
        processing = ET.SubElement(root, _qti("responseProcessing"))
        response_condition = ET.SubElement(processing, _qti("responseCondition"))
        response_if = ET.SubElement(response_condition, _qti("responseIf"))
        is_null = ET.SubElement(response_if, _qti("isNull"))
        ET.SubElement(is_null, _qti("variable"), {"identifier": "RESPONSE"})
        empty_score = ET.SubElement(
            response_if, _qti("setOutcomeValue"), {"identifier": "SCORE"}
        )
        empty_value = ET.SubElement(empty_score, _qti("baseValue"), {"baseType": "float"})
        empty_value.text = "0"
        response_else = ET.SubElement(response_condition, _qti("responseElse"))
        score_rule = ET.SubElement(
            response_else, _qti("setOutcomeValue"), {"identifier": "SCORE"}
        )
        ET.SubElement(score_rule, _qti("mapResponse"), {"identifier": "RESPONSE"})
        feedback_rule = ET.SubElement(
            processing, _qti("setOutcomeValue"), {"identifier": "FEEDBACK"}
        )
        base_value = ET.SubElement(
            feedback_rule, _qti("baseValue"), {"baseType": "identifier"}
        )
        base_value.text = "GENERAL_FEEDBACK"
        modal = ET.SubElement(
            root,
            _qti("modalFeedback"),
            {
                "outcomeIdentifier": "FEEDBACK",
                "identifier": "GENERAL_FEEDBACK",
                "showHide": "show",
                "title": "Forklaring" if language.startswith("da") else "Explanation",
            },
        )
        _add_image(
            modal,
            rendered[f"{qid}-feedback"],
            f"assets/{qid}-feedback.png",
        )
    else:
        ET.SubElement(
            root,
            _qti("responseProcessing"),
            {"template": "http://www.imsglobal.org/question/qti_v2p1/rptemplates/map_response"},
        )
    return ET.ElementTree(root)


def build_written_item_xml(
    section: WrittenSection,
    rendered: dict[str, RenderedImage],
    default_points: float,
    language: str,
    include_feedback: bool,
    expected_lines: int,
) -> ET.ElementTree:
    """Build one rich-text essay item containing an ordered written section.

    Canvas rejects QTI assessment items containing more than one extended-text
    interaction.  All subquestion prompts therefore remain together in the
    item body, followed by one response field for the complete section.
    """
    qid = f"w{section.number:03d}"
    root = ET.Element(
        _qti("assessmentItem"),
        {
            "identifier": qid,
            "title": latex_to_plain(section.title),
            "adaptive": "false",
            "timeDependent": "false",
            f"{{{XML_NS}}}lang": language,
            f"{{{XSI_NS}}}schemaLocation": f"{QTI_NS} {QTI_SCHEMA}",
        },
    )
    ET.SubElement(
        root,
        _qti("responseDeclaration"),
        {
            "identifier": "RESPONSE",
            "cardinality": "single",
            "baseType": "string",
        },
    )
    maximum = _effective_points(
        section.points,
        sum(
            _effective_points(subquestion.points, default_points)
            for subquestion in section.subquestions
        ),
    )
    outcome = ET.SubElement(
        root,
        _qti("outcomeDeclaration"),
        {
            "identifier": "SCORE",
            "cardinality": "single",
            "baseType": "float",
            "normalMaximum": _number(maximum),
            "normalMinimum": "0",
        },
    )
    default_value = ET.SubElement(outcome, _qti("defaultValue"))
    ET.SubElement(default_value, _qti("value")).text = "0"

    has_feedback = include_feedback and any(
        subquestion.feedback for subquestion in section.subquestions
    )
    if has_feedback:
        ET.SubElement(
            root,
            _qti("outcomeDeclaration"),
            {"identifier": "FEEDBACK", "cardinality": "single", "baseType": "identifier"},
        )

    body = ET.SubElement(root, _qti("itemBody"))
    for subquestion in section.subquestions:
        part_key = f"{qid}-part-{subquestion.number:03d}"
        _add_image(body, rendered[part_key], f"assets/{part_key}.png")
    ET.SubElement(
        body,
        _qti("extendedTextInteraction"),
        {
            "responseIdentifier": "RESPONSE",
            "expectedLines": str(expected_lines),
            "format": "xhtml",
        },
    )

    if has_feedback:
        processing = ET.SubElement(root, _qti("responseProcessing"))
        feedback_rule = ET.SubElement(
            processing, _qti("setOutcomeValue"), {"identifier": "FEEDBACK"}
        )
        base_value = ET.SubElement(
            feedback_rule, _qti("baseValue"), {"baseType": "identifier"}
        )
        base_value.text = "GENERAL_FEEDBACK"
        modal = ET.SubElement(
            root,
            _qti("modalFeedback"),
            {
                "outcomeIdentifier": "FEEDBACK",
                "identifier": "GENERAL_FEEDBACK",
                "showHide": "show",
                "title": "Forklaring" if language.startswith("da") else "Explanation",
            },
        )
        _add_image(
            modal,
            rendered[f"{qid}-feedback"],
            f"assets/{qid}-feedback.png",
        )
    return ET.ElementTree(root)


def build_manifest(
    package_identifier: str,
    questions: Sequence[Question],
    written_sections: Sequence[WrittenSection],
    include_feedback: bool,
    title: str = "LaTeX question bank",
    language: str = "en",
) -> ET.ElementTree:
    root = ET.Element(
        _imscp("manifest"),
        {
            "identifier": package_identifier,
            f"{{{XSI_NS}}}schemaLocation": f"{IMSCP_NS} {PACKAGE_SCHEMA}",
        },
    )
    metadata = ET.SubElement(root, _imscp("metadata"))
    ET.SubElement(metadata, _imscp("schema")).text = "QTIv2.1 Package"
    ET.SubElement(metadata, _imscp("schemaversion")).text = "1.0.0"
    lom = ET.SubElement(metadata, f"{{{LOM_NS}}}lom")
    general = ET.SubElement(lom, f"{{{LOM_NS}}}general")
    lom_title = ET.SubElement(general, f"{{{LOM_NS}}}title")
    title_string = ET.SubElement(lom_title, f"{{{LOM_NS}}}string")
    title_string.set("language", language)
    title_string.text = title
    ET.SubElement(root, _imscp("organizations"))
    resources = ET.SubElement(root, _imscp("resources"))
    for question in questions:
        qid = f"q{question.number:03d}"
        item_path = f"items/{qid}.xml"
        resource = ET.SubElement(
            resources,
            _imscp("resource"),
            {
                "identifier": f"resource_{qid}",
                "type": "imsqti_item_xmlv2p1",
                "href": item_path,
            },
        )
        ET.SubElement(resource, _imscp("file"), {"href": item_path})
        ET.SubElement(resource, _imscp("file"), {"href": f"items/assets/{qid}-stem.png"})
        for answer_index in range(1, len(question.answers) + 1):
            ET.SubElement(
                resource,
                _imscp("file"),
                {"href": f"items/assets/{qid}-answer-{answer_index:03d}.png"},
            )
        if include_feedback and question.feedback:
            ET.SubElement(
                resource,
                _imscp("file"),
                {"href": f"items/assets/{qid}-feedback.png"},
            )
    for section in written_sections:
        qid = f"w{section.number:03d}"
        item_path = f"items/{qid}.xml"
        resource = ET.SubElement(
            resources,
            _imscp("resource"),
            {
                "identifier": f"resource_{qid}",
                "type": "imsqti_item_xmlv2p1",
                "href": item_path,
            },
        )
        ET.SubElement(resource, _imscp("file"), {"href": item_path})
        for subquestion in section.subquestions:
            ET.SubElement(
                resource,
                _imscp("file"),
                {
                    "href": (
                        f"items/assets/{qid}-part-{subquestion.number:03d}.png"
                    )
                },
            )
        if include_feedback and any(
            subquestion.feedback for subquestion in section.subquestions
        ):
            ET.SubElement(
                resource,
                _imscp("file"),
                {"href": f"items/assets/{qid}-feedback.png"},
            )
    return ET.ElementTree(root)
ET.register_namespace("", QTI_NS)
ET.register_namespace("xsi", XSI_NS)

