"""Build WISEflow's native item format (Learnosity item JSON).

The structure mirrors an item export from WISEflow's content bank.  A
multiple-choice question becomes a multiple-response ``mcq`` scored with
``partialMatch`` ("partial match per response"): every selected correct
choice earns ``score`` and every selected incorrect choice costs ``penalty``,
and ``minScore`` clamps the question at zero.  A written section becomes an
essay question: Learnosity's built-in ``longtextV2`` by default, or
WISEflow's custom essay type when its definition is copied from an export.
"""
from __future__ import annotations

import copy
import json
import time
import uuid
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union

from .alttext import latex_to_plain
from .model import ConversionError, Question, WrittenSection
from .qti import _effective_points, mc_title

AUTHOR_VERSION = "4.8.1"
CREATED_BY = "latex2quiz"
ESSAY_MAX_LENGTH = 100000
MC_QUESTION_NAME = "Multiple-choice (blok layout)"
ESSAY_QUESTION_NAME = "Essay with rich text"

Number = Union[int, float]
JsonObject = Dict[str, object]


SCORE_DECIMALS = 3


def _score(value: float) -> Number:
    """Round an emitted score once, to the precision WISEflow itself stores."""
    rounded = round(value, SCORE_DECIMALS)
    return int(rounded) if rounded == int(rounded) else rounded


def _reference(digest: str, name: str) -> str:
    """A fresh UUID4 for an item or widget.

    WISEflow assigns random references on export and treats a reference as
    the identity of an item, so every run creates new ones.  ``digest`` and
    ``name`` are accepted for call-site symmetry and reporting but do not
    influence the value.
    """
    del digest, name
    return str(uuid.uuid4())


def _item(title: str, reference: str, *questions: JsonObject) -> JsonObject:
    """An item whose questions are shown in order, each with its response."""
    return {
        "reference": reference,
        "title": title,
        "description": "",
        "stimulus": " ",
        "workflow": [],
        "metadata": [],
        "note": "",
        "source": "",
        "definition": {
            "widgets": [
                {"reference": question["reference"], "widget_type": "response"}
                for question in questions
            ]
        },
        "status": "published",
        "questions": list(questions),
        "features": [],
        "tags": [],
        "labels": [],
    }


def build_mc_item(
    question: Question,
    stimulus_html: str,
    option_html: Sequence[str],
    feedback_html: Optional[str],
    default_points: float,
    shuffle: bool,
    digest: str,
) -> JsonObject:
    """Build a multiple-response ``mcq`` item with per-choice scoring.

    The totals match the QTI mapping: all correct choices sum to the question
    value and all incorrect choices sum to its negative, with the question
    clamped at zero by ``minScore``.
    """
    qid = f"q{question.number:03d}"
    title = mc_title(question, default_points)
    points = _effective_points(question.points, default_points)
    correct_count = sum(answer.correct for answer in question.answers)
    incorrect_count = len(question.answers) - correct_count
    score = _score(points / correct_count)
    penalty = _score(points / incorrect_count) if incorrect_count else 0
    options = [
        {"label": label, "value": str(index)}
        for index, label in enumerate(option_html)
    ]
    correct_values = [
        str(index) for index, answer in enumerate(question.answers) if answer.correct
    ]
    data: JsonObject = {
        "minScore": 0,
        "multiple_responses": True,
        "options": options,
        "shuffle_options": shuffle,
        "stimulus": stimulus_html,
        "title": title,
        "type": "mcq",
        "ui_style": {"type": "horizontal", "choice_label": "upper-alpha"},
        "validation": {
            "allow_negative_scores": True,
            "scoring_type": "partialMatch",
            "valid_response": {"score": score, "value": correct_values},
            "penalty": penalty,
        },
        "is_math": True,
    }
    if feedback_html:
        data["metadata"] = {"distractor_rationale": feedback_html}
    widget: JsonObject = {
        "type": "mcq",
        "widget_type": "response",
        "reference": _reference(digest, f"{qid}-widget"),
        "data": data,
        "metadata": {"name": MC_QUESTION_NAME},
    }
    return _item(title, _reference(digest, qid), widget)


def load_essay_template(path: Path) -> JsonObject:
    """Copy the essay question definition from a WISEflow item export.

    WISEflow's own essay type is a Learnosity custom question whose script
    locations differ between environments, so they are taken from an export
    made in the target environment rather than hard-coded.
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ConversionError(f"Cannot read essay template {path}: {error}") from error
    items = document.get("data", []) if isinstance(document, dict) else []
    for item in items:
        for question in item.get("questions", []):
            data = question.get("data", {})
            kind = data.get("type")
            if kind == "longtextV2" or (
                kind == "custom" and "essay" in str(data.get("custom_type", "")).lower()
            ):
                template = {
                    "data": copy.deepcopy(data),
                    "metadata": copy.deepcopy(question.get("metadata")),
                }
                for key in ("stimulus", "validation", "metadata"):
                    template["data"].pop(key, None)
                return template
    raise ConversionError(f"No essay question found in {path}")


def _essay_question(
    reference: str,
    stimulus_html: str,
    feedback_html: Optional[str],
    maximum: float,
    essay_template: Optional[JsonObject],
) -> JsonObject:
    if essay_template is None:
        data: JsonObject = {
            "type": "longtextV2",
            "is_math": True,
            "max_length": ESSAY_MAX_LENGTH,
        }
        name: object = {"name": ESSAY_QUESTION_NAME}
    else:
        data = copy.deepcopy(essay_template["data"])  # type: ignore[arg-type]
        name = copy.deepcopy(essay_template.get("metadata")) or {
            "name": ESSAY_QUESTION_NAME
        }
    data["stimulus"] = stimulus_html
    data["is_math"] = True
    data["validation"] = {"max_score": _score(maximum)}
    if feedback_html:
        data["metadata"] = {"sample_answer": feedback_html}
    return {
        "type": data["type"],
        "widget_type": "response",
        "reference": reference,
        "data": data,
        "metadata": name,
    }


def section_points(section: WrittenSection, default_points: float) -> float:
    """The section total: explicit, or the sum of its parts."""
    return _effective_points(
        section.points,
        sum(
            _effective_points(subquestion.points, default_points)
            for subquestion in section.subquestions
        ),
    )


def part_points(section: WrittenSection, default_points: float) -> List[Number]:
    r"""Points per ``\\punkt`` that sum exactly to the section total.

    Parts with their own ``\\qtipoints`` keep that value.  When the section
    has an explicit total, the remainder is shared by the other parts in
    whole points: the earlier parts are rounded up and the later ones down,
    so 11 points over three parts gives 4, 4, 3.  A remainder that is not a
    whole number is shared equally instead, with the last part absorbing the
    rounding.  Without a section total, the open parts get ``default_points``.
    """
    explicit = [subquestion.points for subquestion in section.subquestions]
    open_count = sum(value is None for value in explicit)
    if section.points is None:
        values = [_effective_points(value, default_points) for value in explicit]
        rounded = [_score(value) for value in values[:-1]]
        rounded.append(_score(sum(values) - sum(rounded)))
        return rounded
    remainder = section.points - sum(value for value in explicit if value is not None)
    if open_count and remainder <= 0:
        raise ConversionError(
            f"Written section {section.title!r}: explicit \\qtipoints values "
            f"leave nothing of the {section.points:g} point total for the "
            "remaining parts"
        )
    if not open_count and abs(remainder) > 1e-9:
        raise ConversionError(
            f"Written section {section.title!r}: \\qtipoints values sum to "
            f"{section.points - remainder:g}, not the section total {section.points:g}"
        )
    shares: List[float] = []
    if open_count:
        whole = round(remainder)
        if abs(remainder - whole) < 1e-9:
            base, extra = divmod(whole, open_count)
            shares = [base + 1] * extra + [base] * (open_count - extra)
        else:
            shares = [remainder / open_count] * open_count
    values = [shares.pop(0) if value is None else value for value in explicit]
    rounded = [_score(value) for value in values[:-1]]
    rounded.append(_score(sum(values) - sum(rounded)))
    return rounded


def build_written_item(
    section: WrittenSection,
    stimulus_html: str,
    feedback_html: Optional[str],
    default_points: float,
    digest: str,
    essay_template: Optional[JsonObject] = None,
) -> JsonObject:
    """Build one essay item with a single response for a written section."""
    qid = f"w{section.number:03d}"
    question = _essay_question(
        _reference(digest, f"{qid}-widget"),
        stimulus_html,
        feedback_html,
        section_points(section, default_points),
        essay_template,
    )
    return _item(latex_to_plain(section.title), _reference(digest, qid), question)


def build_written_parts_item(
    section: WrittenSection,
    part_stimuli: Sequence[str],
    part_feedback: Sequence[Optional[str]],
    default_points: float,
    digest: str,
    essay_template: Optional[JsonObject] = None,
) -> JsonObject:
    r"""Build one item with a separate essay question per ``\punkt``.

    The questions appear in order, each with its own response field and its
    own points, so the parts are answered and graded separately while the
    shared context still appears once, before part a).
    """
    qid = f"w{section.number:03d}"
    points = part_points(section, default_points)
    questions = [
        _essay_question(
            _reference(digest, f"{qid}-part-{index:03d}-widget"),
            stimulus,
            feedback,
            maximum,
            essay_template,
        )
        for index, (stimulus, feedback, maximum) in enumerate(
            zip(part_stimuli, part_feedback, points), start=1
        )
    ]
    return _item(latex_to_plain(section.title), _reference(digest, qid), *questions)


def build_bank(items: Sequence[JsonObject]) -> JsonObject:
    return {
        "data": list(items),
        "metadata": {
            "author_version": AUTHOR_VERSION,
            "date_created": int(time.time()),
            "created_by": CREATED_BY,
            "content": "item",
        },
    }


def _walk_keys(value: object, path: str, found: Dict[str, Set[str]]) -> None:
    """Record the key set of every object in ``value``, by structural path."""
    if isinstance(value, dict):
        found.setdefault(path, set()).update(value.keys())
        for key, child in value.items():
            _walk_keys(child, f"{path}.{key}" if path else key, found)
    elif isinstance(value, list):
        for child in value:
            _walk_keys(child, f"{path}[]", found)


def compare_keys(bank: JsonObject, fixture: JsonObject) -> List[Tuple[str, str, str]]:
    """Return (path, 'missing'|'extra', key) differences against a fixture.

    Comparison is by structural path, so ``data[].questions[].data`` collects
    the keys of every question's data object in either file.  Keys that exist
    only for some question types in the fixture (for example the essay
    ``custom`` fields) show up as missing when the bank has no such question,
    so the result is informational rather than pass/fail.
    """
    mine: Dict[str, Set[str]] = {}
    theirs: Dict[str, Set[str]] = {}
    _walk_keys(bank, "", mine)
    _walk_keys(fixture, "", theirs)
    differences: List[Tuple[str, str, str]] = []
    for path in sorted(set(mine) | set(theirs)):
        for key in sorted(theirs.get(path, set()) - mine.get(path, set())):
            differences.append((path, "missing", key))
        for key in sorted(mine.get(path, set()) - theirs.get(path, set())):
            differences.append((path, "extra", key))
    return differences


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_bank(bank: object) -> List[str]:
    """Check a produced Learnosity file mechanically before uploading it.

    The checks cover document structure, reference consistency, scoring
    fields and types, and the option/answer mapping.  Each problem is a
    human-readable line; an empty list means the file passed.
    """
    problems: List[str] = []
    if not isinstance(bank, dict) or not isinstance(bank.get("data"), list):
        return ["top level must be an object with a 'data' list"]
    metadata = bank.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("content") != "item":
        problems.append("metadata.content must be 'item'")
    seen: Set[str] = set()

    def reference_ok(value: object, where: str) -> None:
        try:
            uuid.UUID(str(value))
        except ValueError:
            problems.append(f"{where}: reference {value!r} is not a UUID")
            return
        if value in seen:
            problems.append(f"{where}: duplicate reference {value}")
        seen.add(str(value))

    for index, item in enumerate(bank["data"]):
        where = f"item {index + 1}"
        if not isinstance(item, dict):
            problems.append(f"{where}: not an object")
            continue
        title = item.get("title")
        if isinstance(title, str) and title.strip():
            where = f"item {index + 1} ({title})"
        else:
            problems.append(f"{where}: missing title")
        reference_ok(item.get("reference"), where)
        if item.get("status") != "published":
            problems.append(f"{where}: status must be 'published'")
        for key in ("description", "stimulus", "note", "source"):
            if not isinstance(item.get(key), str):
                problems.append(f"{where}: {key} must be a string")
        for key in ("workflow", "metadata", "features", "tags", "labels"):
            if not isinstance(item.get(key), list):
                problems.append(f"{where}: {key} must be a list")
        widgets = (item.get("definition") or {}).get("widgets")
        questions = item.get("questions")
        if not isinstance(widgets, list) or not isinstance(questions, list):
            problems.append(f"{where}: definition.widgets and questions must be lists")
            continue
        if len(widgets) != len(questions):
            problems.append(f"{where}: {len(widgets)} widgets but {len(questions)} questions")
        for widget, question in zip(widgets, questions):
            if widget.get("reference") != question.get("reference"):
                problems.append(f"{where}: widget and question references differ")
            if widget.get("widget_type") != "response" or question.get("widget_type") != "response":
                problems.append(f"{where}: widget_type must be 'response' on widget and question")
        for question in questions:
            reference_ok(question.get("reference"), where)
            data = question.get("data")
            if not isinstance(data, dict):
                problems.append(f"{where}: question data missing")
                continue
            kind = question.get("type")
            if kind != data.get("type"):
                problems.append(f"{where}: question type {kind!r} differs from data.type {data.get('type')!r}")
            if not isinstance(data.get("stimulus"), str) or not data["stimulus"].strip():
                problems.append(f"{where}: empty stimulus")
            validation = data.get("validation")
            if not isinstance(validation, dict):
                problems.append(f"{where}: validation missing")
                continue
            if kind == "mcq":
                problems.extend(f"{where}: {text}" for text in _validate_mcq(data, validation))
            elif kind == "custom":
                for key in ("custom_type", "js", "css", "height", "width"):
                    if key not in data:
                        problems.append(f"{where}: custom question lacks {key}")
                if not _is_number(validation.get("max_score")) or validation["max_score"] <= 0:
                    problems.append(f"{where}: validation.max_score must be a positive number")
            elif kind == "longtextV2":
                if not _is_number(validation.get("max_score")) or validation["max_score"] <= 0:
                    problems.append(f"{where}: validation.max_score must be a positive number")
            else:
                problems.append(f"{where}: unexpected question type {kind!r}")
    return problems


def _validate_mcq(data: JsonObject, validation: JsonObject) -> List[str]:
    problems: List[str] = []
    if data.get("multiple_responses") is not True:
        problems.append("multiple_responses must be true")
    if "minScore" in validation:
        problems.append("minScore belongs in data, not validation")
    if not _is_number(data.get("minScore")) or data["minScore"] != 0:
        problems.append("data.minScore must be the number 0")
    if validation.get("scoring_type") != "partialMatch":
        problems.append(f"scoring_type must be 'partialMatch', not {validation.get('scoring_type')!r}")
    if validation.get("allow_negative_scores") is not True:
        problems.append("allow_negative_scores must be the boolean true")
    options = data.get("options")
    if not isinstance(options, list) or len(options) < 2:
        problems.append("fewer than two options")
        return problems
    values = [option.get("value") for option in options]
    expected = [str(index) for index in range(len(options))]
    if values != expected:
        problems.append(f"option values {values} are not {expected}")
    for option in options:
        if not isinstance(option.get("label"), str) or not option["label"].strip():
            problems.append("empty option label")
    response = validation.get("valid_response")
    if not isinstance(response, dict):
        problems.append("valid_response missing")
        return problems
    correct = response.get("value")
    if not isinstance(correct, list) or not correct:
        problems.append("valid_response.value must be a non-empty list")
    else:
        if len(set(correct)) != len(correct):
            problems.append("valid_response.value has duplicates")
        if any(value not in expected for value in correct):
            problems.append(f"valid_response.value {correct} refers to unknown options")
        elif correct != sorted(correct, key=int):
            problems.append("valid_response.value is not in document order")
    score = response.get("score")
    penalty = validation.get("penalty")
    if not _is_number(score) or score <= 0:
        problems.append("valid_response.score must be a positive number")
    elif round(score, SCORE_DECIMALS) != score:
        problems.append(f"score {score} has more than {SCORE_DECIMALS} decimals")
    if not _is_number(penalty) or penalty < 0:
        problems.append("penalty must be a non-negative number")
    elif round(penalty, SCORE_DECIMALS) != penalty:
        problems.append(f"penalty {penalty} has more than {SCORE_DECIMALS} decimals")
    if isinstance(correct, list) and _is_number(penalty):
        wrong = len(options) - len(correct)
        if wrong == 0 and penalty != 0:
            problems.append("penalty must be 0 when every option is correct")
        if wrong > 0 and penalty == 0:
            problems.append("penalty is 0 although there are incorrect options")
    return problems


def item_maximum_scores(item: JsonObject) -> List[Number]:
    """Return the maximum score of every question in an item."""
    scores: List[Number] = []
    for question in item["questions"]:  # type: ignore[union-attr]
        data = question["data"]
        validation = data["validation"]
        if data["type"] == "mcq":
            response = validation["valid_response"]
            scores.append(_score(response["score"] * len(response["value"])))
        else:
            scores.append(validation["max_score"])
    return scores
