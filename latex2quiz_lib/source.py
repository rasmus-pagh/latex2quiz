"""Parsing for the repository's LaTeX exam dialect."""
from __future__ import annotations

import math
import re
from typing import List, Optional, Tuple

from .model import Answer, ConversionError, Question, WrittenSection, WrittenSubquestion

DEFAULT_PREAMBLE = r"""
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{enumitem}
\usepackage{xspace}
\usepackage{tikz}
\usepackage{calc}
\usepackage{fancybox}
\usepackage{clrscode3e}
\usepackage[export]{adjustbox}
\usetikzlibrary{arrows,arrows.meta,automata,backgrounds,calc,
  decorations.pathmorphing,decorations.pathreplacing,fit,matrix,patterns,
  positioning,shapes,shapes.geometric,trees}
\providecommand{\nylinie}{\\}
\providecommand{\sideskift}{\par\bigskip}
\providecommand{\pageshift}{\par\bigskip}
\providecommand{\mcprocent}{}
\providecommand{\mcpercent}{}
\providecommand{\placeholder}[1]{\textit{[#1]}}
\tikzset{
  treenode/.style={align=center,inner sep=0pt,text centered,font=\sffamily},
  black/.style={treenode,circle,text=white,font=\sffamily\bfseries,
    draw=black,fill=black,text width=1.5em},
  red/.style={treenode,circle,text=white,draw=red,fill=red,
    text width=1.5em,very thick},
  white/.style={treenode,rectangle,draw=none,
    minimum width=0.5em,minimum height=0.5em},
  gray/.style={treenode,rectangle,draw=black,
    minimum width=0.5em,minimum height=0.5em}
}
""".strip()


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def strip_comments(text: str) -> str:
    """Remove TeX comments while retaining newlines and escaped percent signs."""
    output: List[str] = []
    for line in text.splitlines(keepends=True):
        cut = len(line)
        for index, char in enumerate(line):
            if char != "%":
                continue
            slash_count = 0
            cursor = index - 1
            while cursor >= 0 and line[cursor] == "\\":
                slash_count += 1
                cursor -= 1
            if slash_count % 2 == 0:
                cut = index
                break
        kept = line[:cut]
        if line.endswith("\n") and not kept.endswith("\n"):
            kept += "\n"
        output.append(kept)
    return "".join(output)


# English names for the Danish exam macros. Sources may use either spelling;
# the parser always refers to a macro by its Danish name.
MACRO_ALIASES = {
    "spoergsmaal": "question",
    "svar": "answer",
    "korrekt": "correct",
    "etsvar": "oneanswer",
    "fleresvar": "multipleanswers",
    "mulighederstart": "optionsstart",
    "mulighederslut": "optionsend",
    "multiplechoiceslut": "multiplechoiceend",
    "forklaring": "explanation",
    "punkt": "subquestion",
    "itxsvar": "itxanswer",
    "sideskift": "pageshift",
    "mcprocent": "mcpercent",
    "svarside": "answerpage",
    "medsvar": "withanswers",
    "nylinie": "newline",
}


def _command_pattern(name: str, line_start: bool = False) -> re.Pattern[str]:
    prefix = r"^[ \t]*" if line_start else ""
    names = re.escape(name)
    if name in MACRO_ALIASES:
        names = f"(?:{names}|{re.escape(MACRO_ALIASES[name])})"
    return re.compile(prefix + rf"\\{names}(?![A-Za-z@])", re.MULTILINE)


def _stray_item(answer_text: str) -> Optional[int]:
    """Offset of the first line-start ``\\item`` that is not inside a nested
    list environment, or ``None``. Such an ``\\item`` prints like an answer but
    is not one: the parser only splits answers at ``\\svar``."""
    depth = 0
    events = re.finditer(
        r"\\(begin|end)\{[^}]*\}|" + _command_pattern("item", line_start=True).pattern,
        answer_text,
        re.MULTILINE,
    )
    for event in events:
        if event.group(1) == "begin":
            depth += 1
        elif event.group(1) == "end":
            depth = max(0, depth - 1)
        elif depth == 0:
            return event.start()
    return None


def _balanced_group(text: str, start: int, context: str) -> Tuple[str, int]:
    cursor = start
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    if cursor >= len(text) or text[cursor] != "{":
        raise ConversionError(f"Expected '{{' after {context} on line {_line_number(text, start)}")

    depth = 0
    content_start = cursor + 1
    for index in range(cursor, len(text)):
        char = text[index]
        if char not in "{}":
            continue
        slash_count = 0
        before = index - 1
        while before >= 0 and text[before] == "\\":
            slash_count += 1
            before -= 1
        if slash_count % 2:
            continue
        if char == "{":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return text[content_start:index], index + 1
    raise ConversionError(f"Unclosed group after {context} on line {_line_number(text, start)}")


def _remove_group_command(text: str, name: str) -> str:
    pattern = _command_pattern(name)
    while True:
        match = pattern.search(text)
        if not match:
            return text
        try:
            _, end = _balanced_group(text, match.end(), f"\\{name}")
        except ConversionError:
            return text[: match.start()] + text[match.end() :]
        text = text[: match.start()] + text[end:]


def _command_definition_spans(text: str) -> List[Tuple[int, int]]:
    pattern = re.compile(
        r"^[ \t]*\\(?:newcommand|renewcommand|providecommand)(?![A-Za-z@])",
        re.MULTILINE,
    )
    spans: List[Tuple[int, int]] = []
    for match in pattern.finditer(text):
        cursor = match.end()
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if cursor < len(text) and text[cursor] == "{":
            _, cursor = _balanced_group(text, cursor, "a command declaration")
        else:
            command_name = re.match(r"\\[A-Za-z@]+", text[cursor:])
            if not command_name:
                continue
            cursor += command_name.end()

        while True:
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1
            if cursor >= len(text) or text[cursor] != "[":
                break
            closing = text.find("]", cursor + 1)
            if closing < 0:
                raise ConversionError(
                    "Unclosed optional argument in a LaTeX command declaration"
                )
            cursor = closing + 1
        _, definition_end = _balanced_group(text, cursor, "a command declaration")
        spans.append((match.start(), definition_end))
    return spans


def _remove_command_definitions(text: str) -> str:
    for start, end in reversed(_command_definition_spans(text)):
        text = text[:start] + text[end:]
    return text


def _clean_fragment(text: str) -> str:
    text = _remove_command_definitions(text)
    text = _remove_group_command(text, "itxsvar")
    text = _remove_group_command(text, "qtipoints")
    text = _command_pattern("korrekt").sub("", text)
    text = _command_pattern("etsvar").sub("", text)
    text = _command_pattern("fleresvar").sub("", text)
    return text.strip()


def _extract_points(text: str, context: str) -> Optional[float]:
    r"""Read one optional ``\qtipoints{number}`` annotation from a fragment."""
    matches = list(_command_pattern("qtipoints").finditer(text))
    if not matches:
        return None
    if len(matches) > 1:
        raise ConversionError(f"{context} contains more than one \\qtipoints command")
    raw, _ = _balanced_group(text, matches[0].end(), "\\qtipoints")
    try:
        value = float(raw.strip())
    except ValueError as error:
        raise ConversionError(
            f"{context} has invalid points value {raw.strip()!r}"
        ) from error
    if not math.isfinite(value) or value <= 0:
        raise ConversionError(f"{context} points must be a finite number greater than zero")
    return value


def _clean_written_fragment(text: str) -> str:
    text = _remove_group_command(text, "label")
    for command in ("newpage", "clearpage", "pagebreak", "sideskift"):
        text = _command_pattern(command).sub("", text)
    return _clean_fragment(text)


def _written_stem(title: Optional[str], context: str, label: str, prompt: str) -> str:
    parts: List[str] = []
    if title:
        parts.append(rf"\section*{{{title}}}")
    if context:
        parts.append(context)
    if label:
        parts.append(rf"\textbf{{{label}}}\quad {prompt}")
    else:
        parts.append(prompt)
    return "\n\n".join(parts)


def _points_from_section_title(title: str) -> Optional[float]:
    r"""Return the legacy total from a trailing marker such as ``(9\%)``."""
    match = re.search(r"\(\s*([0-9]+(?:\.[0-9]+)?)\s*\\?%\s*\)\s*$", title)
    return float(match.group(1)) if match else None


def parse_questions(source: str) -> Tuple[List[Question], List[str]]:
    """Parse questions from the legacy exam LaTeX format."""
    text = strip_comments(source)
    start_match = _command_pattern("multiplechoicestart", line_start=True).search(text)
    if not start_match:
        raise ConversionError("No \\multiplechoicestart line found")
    end_match = _command_pattern("multiplechoiceslut", line_start=True).search(
        text, start_match.end()
    )
    if not end_match:
        raise ConversionError("No \\multiplechoiceslut line found")

    section_start = start_match.end()
    section = text[section_start : end_match.start()]
    question_matches = list(_command_pattern("spoergsmaal", line_start=True).finditer(section))
    if not question_matches:
        raise ConversionError("No \\spoergsmaal questions found in the multiple-choice section")

    questions: List[Question] = []
    warnings: List[str] = []
    for index, match in enumerate(question_matches):
        absolute_start = section_start + match.start()
        title, title_end = _balanced_group(section, match.end(), "\\spoergsmaal")
        block_end = (
            question_matches[index + 1].start()
            if index + 1 < len(question_matches)
            else len(section)
        )
        block = section[title_end:block_end]
        question_line = _line_number(text, absolute_start)

        options_start = _command_pattern("mulighederstart").search(block)
        if not options_start:
            raise ConversionError(
                f"Question {index + 1} ({title.strip()!r}, line {question_line}) "
                "has no \\mulighederstart"
            )
        options_end = _command_pattern("mulighederslut").search(block, options_start.end())
        if not options_end:
            raise ConversionError(
                f"Question {index + 1} ({title.strip()!r}, line {question_line}) "
                "has no \\mulighederslut"
            )

        stem_raw = block[: options_start.start()]
        single_markers = list(_command_pattern("etsvar").finditer(stem_raw))
        multiple_markers = list(_command_pattern("fleresvar").finditer(stem_raw))
        if single_markers and multiple_markers:
            raise ConversionError(
                f"Question {index + 1} on line {question_line} contains both "
                "\\etsvar and \\fleresvar"
            )

        answer_text = block[options_start.end() : options_end.start()]
        answer_base = absolute_start + (title_end - match.start()) + options_start.end()
        stray_item = _stray_item(answer_text)
        if stray_item is not None:
            raise ConversionError(
                f"Question {index + 1} on line {question_line}: answer on line "
                f"{_line_number(text, answer_base + stray_item)} starts with \\item; "
                "use \\svar for each answer"
            )
        answer_matches = list(_command_pattern("svar", line_start=True).finditer(answer_text))
        if len(answer_matches) < 2:
            raise ConversionError(
                f"Question {index + 1} on line {question_line} has fewer than two answers"
            )

        answers: List[Answer] = []
        for answer_index, answer_match in enumerate(answer_matches):
            answer_end = (
                answer_matches[answer_index + 1].start()
                if answer_index + 1 < len(answer_matches)
                else len(answer_text)
            )
            raw = answer_text[answer_match.end() : answer_end]
            correct = bool(_command_pattern("korrekt").search(raw))
            answer_line = _line_number(text, answer_base + answer_match.start())
            cleaned = _clean_fragment(raw)
            if not cleaned:
                raise ConversionError(
                    f"Question {index + 1}, answer {answer_index + 1} "
                    f"on line {answer_line} is empty"
                )
            answers.append(Answer(cleaned, correct, answer_line))

        correct_count = sum(answer.correct for answer in answers)
        if correct_count == 0:
            raise ConversionError(
                f"Question {index + 1} on line {question_line} has no \\korrekt answer"
            )

        if single_markers:
            kind = "single"
            if correct_count != 1:
                raise ConversionError(
                    f"Question {index + 1} on line {question_line} uses \\etsvar "
                    f"but has {correct_count} correct answers"
                )
        elif multiple_markers:
            kind = "multiple"
        else:
            kind = "single" if correct_count == 1 else "multiple"
            warnings.append(
                f"line {question_line}: question {index + 1} has no \\etsvar or "
                f"\\fleresvar; inferred {kind} from {correct_count} correct answer(s)"
            )

        remainder = block[options_end.end() :]
        feedback: Optional[str] = None
        feedback_match = _command_pattern("forklaring").search(remainder)
        if feedback_match:
            feedback, _ = _balanced_group(
                remainder, feedback_match.end(), "\\forklaring"
            )
            feedback = _clean_fragment(feedback)
            if not feedback:
                feedback = None

        questions.append(
            Question(
                number=index + 1,
                title=title.strip(),
                stem=_clean_fragment(stem_raw),
                kind=kind,
                answers=tuple(answers),
                feedback=feedback,
                points=_extract_points(
                    stem_raw,
                    f"Question {index + 1} on line {question_line}",
                ),
                line=question_line,
            )
        )

    return questions, warnings


def parse_written_sections(source: str) -> List[WrittenSection]:
    r"""Parse each written ``\section`` as one ordered essay item.

    Material before the first ``\punkt`` is attached only to the first
    subquestion. Material between points is attached only to the following
    subquestion, so the complete section reads in order without duplication.
    """
    text = strip_comments(source)
    mc_start = _command_pattern("multiplechoicestart", line_start=True).search(text)
    if not mc_start:
        raise ConversionError("No \\multiplechoicestart line found")
    mc_end = _command_pattern("multiplechoiceslut", line_start=True).search(
        text, mc_start.end()
    )
    if not mc_end:
        raise ConversionError("No \\multiplechoiceslut line found")

    written_start = mc_end.end()
    document_end = re.search(r"\\end\s*\{document\}", text[written_start:])
    written_end = (
        written_start + document_end.start() if document_end else len(text)
    )
    written = text[written_start:written_end]

    # A starred section is the general "Skriftlige opgaver" heading. Only
    # ordinary sections delimit actual written problems.
    section_pattern = re.compile(
        r"^[ \t]*\\section(?![A-Za-z@*])", re.MULTILINE
    )
    section_matches = list(section_pattern.finditer(written))
    sections: List[WrittenSection] = []

    for section_index, section_match in enumerate(section_matches):
        section_title, title_end = _balanced_group(
            written, section_match.end(), "\\section"
        )
        block_end = (
            section_matches[section_index + 1].start()
            if section_index + 1 < len(section_matches)
            else len(written)
        )
        block = written[title_end:block_end]
        point_matches = list(_command_pattern("punkt", line_start=True).finditer(block))
        if not point_matches:
            continue

        clean_title = section_title.strip()
        initial_context = block[: point_matches[0].start()]
        section_points = _extract_points(
            initial_context,
            f"Written section {clean_title!r}",
        )
        if section_points is None:
            section_points = _points_from_section_title(clean_title)
        pending_context = _clean_written_fragment(initial_context)
        section_context = pending_context
        subquestions: List[WrittenSubquestion] = []
        for point_index, point_match in enumerate(point_matches):
            point_end = (
                point_matches[point_index + 1].start()
                if point_index + 1 < len(point_matches)
                else len(block)
            )
            label, label_end = _balanced_group(block, point_match.end(), "\\punkt")
            item_tail = block[label_end:point_end]
            nonspace = 0
            while nonspace < len(item_tail) and item_tail[nonspace].isspace():
                nonspace += 1

            braced_prompt = nonspace < len(item_tail) and item_tail[nonspace] == "{"
            if braced_prompt:
                prompt, prompt_end = _balanced_group(
                    item_tail, nonspace, "the second argument of \\punkt"
                )
                trailing = item_tail[prompt_end:]
            else:
                feedback_in_tail = _command_pattern("forklaring").search(item_tail)
                prompt_end = feedback_in_tail.start() if feedback_in_tail else len(item_tail)
                prompt = item_tail[:prompt_end]
                trailing = item_tail[prompt_end:]

            feedback: Optional[str] = None
            interstitial = trailing
            feedback_match = _command_pattern("forklaring").search(trailing)
            if feedback_match:
                before_feedback = trailing[: feedback_match.start()]
                feedback_raw, feedback_end = _balanced_group(
                    trailing, feedback_match.end(), "\\forklaring"
                )
                feedback = _clean_written_fragment(feedback_raw) or None
                interstitial = before_feedback + trailing[feedback_end:]

            clean_prompt = _clean_written_fragment(prompt)
            if not clean_prompt:
                absolute_point = written_start + section_match.start() + (
                    title_end - section_match.start()
                ) + point_match.start()
                raise ConversionError(
                    f"Written question on line {_line_number(text, absolute_point)} "
                    "has an empty prompt"
                )

            absolute_point = written_start + title_end + point_match.start()
            clean_label = label.strip()
            subquestions.append(
                WrittenSubquestion(
                    number=point_index + 1,
                    label=clean_label,
                    context=pending_context,
                    prompt=clean_prompt,
                    stem=_written_stem(
                        clean_title if point_index == 0 else None,
                        pending_context,
                        clean_label,
                        clean_prompt,
                    ),
                    feedback=feedback,
                    points=_extract_points(
                        prompt,
                        (
                            f"Written question {clean_label or point_index + 1} "
                            f"in section {clean_title!r}"
                        ),
                    ),
                    line=_line_number(text, absolute_point),
                )
            )

            pending_context = _clean_written_fragment(interstitial)

        section_line = _line_number(text, written_start + section_match.start())
        sections.append(
            WrittenSection(
                number=len(sections) + 1,
                title=clean_title,
                context=section_context,
                subquestions=tuple(subquestions),
                points=section_points,
                line=section_line,
            )
        )

    return sections


def _extract_preamble(source: str) -> str:
    match = re.search(r"\\begin\s*\{document\}", source)
    if not match:
        return DEFAULT_PREAMBLE
    preamble = source[: match.start()]
    preamble = re.sub(
        r"^[ \t]*\\documentclass(?:\[[^\n]*?\])?\s*\{[^\n]*?\}[ \t]*(?:%[^\n]*)?$",
        "",
        preamble,
        count=1,
        flags=re.MULTILINE,
    )
    return preamble.strip()


def _extract_body_command_definitions(source: str) -> str:
    r"""Copy LaTeX command declarations made after ``\begin{document}``.

    Some archived exams introduce a reusable problem statement in the body and
    invoke it in more than one question. Those declarations must be available
    in the isolated rendering document as well. A fragment without
    ``\begin{document}`` is all body.
    """
    text = strip_comments(source)
    document = re.search(r"\\begin\s*\{document\}", text)
    body = text[document.end() :] if document else text
    return "\n".join(
        body[start:end].strip() for start, end in _command_definition_spans(body)
    )

