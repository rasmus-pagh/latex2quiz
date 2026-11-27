"""Convert LaTeX fragments to HTML with MathJax delimiters.

The output is intended for Learnosity/WISEflow stimuli with ``is_math``
enabled: running text becomes HTML paragraphs, mathematics is kept as LaTeX
inside ``\\( ... \\)`` or ``\\[ ... \\]`` delimiters, and constructs that have
no HTML equivalent (TikZ pictures, ``codebox`` pseudo-code, tables, included
graphics, and unknown environments) are replaced by rendered images.

The converter walks a fragment twice during a conversion: a dry run collects
the LaTeX of every figure that must be rendered, and the second pass embeds
the rendered images in the same order.
"""
from __future__ import annotations

import base64
import html
import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .alttext import latex_to_plain
from .model import ConversionError, RenderedImage
from .source import _balanced_group, _command_definition_spans, strip_comments

_PAR = "\x01"
_BLOCK_START = "\x02"
_BLOCK_END = "\x03"
_MARKERS = f"[{_PAR}{_BLOCK_START}{_BLOCK_END}]"

# Display-math environments and the AMS environment that replaces them inside
# ``\[ ... \]``.  MathJax rejects ``align`` nested in display math, so the
# inner variants are used.
_MATH_ENVIRONMENTS: Dict[str, Optional[Tuple[str, str]]] = {
    "math": None,
    "displaymath": None,
    "equation": None,
    "align": ("aligned", ""),
    "flalign": ("aligned", ""),
    "alignat": ("alignedat", ""),
    "gather": ("gathered", ""),
    "multline": ("gathered", ""),
    "eqnarray": ("array", "{rcl}"),
}

_ALIGNED_BLOCKS = {
    "center": "text-align:center",
    "flushleft": "text-align:left",
    "flushright": "text-align:right",
    "figure": "text-align:center",
    "table": "text-align:center",
    "quote": "margin-left:2em",
    "quotation": "margin-left:2em",
    "verse": "margin-left:2em",
    "small": "font-size:smaller",
    "footnotesize": "font-size:smaller",
    "scriptsize": "font-size:smaller",
    "tiny": "font-size:smaller",
    "large": "font-size:larger",
    "Large": "font-size:larger",
    "LARGE": "font-size:larger",
    "huge": "font-size:larger",
    "Huge": "font-size:larger",
    "em": "font-style:italic",
    "sloppypar": "",
    "samepage": "",
    "document": "",
}
_DRAWINGS = {"tikzpicture", "picture", "pgfpicture", "pspicture"}
_HEADINGS = {
    "section": "h3", "subsection": "h4", "subsubsection": "h5",
    "paragraph": "h5", "subparagraph": "h6",
}
# Wrapping a fragment in this environment makes the converter render all of
# it as one image; the render preamble defines it as a no-op.
IMAGE_ENVIRONMENT = "latexqtiimage"
_LIST_ENVIRONMENTS = {"enumerate": "ol", "itemize": "ul", "description": "ul"}
_VERBATIM_ENVIRONMENTS = {"verbatim", "lstlisting", "alltt"}

# Text-mode font commands: name -> (tag, CSS used when a block wrapper is
# needed, whether the command is a declaration that applies to the rest of
# the current group).
_FONTS: Dict[str, Tuple[str, str, bool]] = {
    "textbf": ("b", "font-weight:bold", False),
    "bf": ("b", "font-weight:bold", True),
    "bfseries": ("b", "font-weight:bold", True),
    "textit": ("i", "font-style:italic", False),
    "emph": ("i", "font-style:italic", False),
    "id": ("i", "font-style:italic", False),
    "it": ("i", "font-style:italic", True),
    "itshape": ("i", "font-style:italic", True),
    "em": ("i", "font-style:italic", True),
    "slshape": ("i", "font-style:italic", True),
    "textsl": ("i", "font-style:italic", False),
    "texttt": ("code", "font-family:monospace", False),
    "tt": ("code", "font-family:monospace", True),
    "ttfamily": ("code", "font-family:monospace", True),
    "textsc": ("span", "font-variant:small-caps", False),
    "proc": ("span", "font-variant:small-caps", False),
    "const": ("span", "font-variant:small-caps", False),
    "sc": ("span", "font-variant:small-caps", True),
    "scshape": ("span", "font-variant:small-caps", True),
    "underline": ("u", "text-decoration:underline", False),
    "small": ("small", "font-size:smaller", True),
    "footnotesize": ("small", "font-size:smaller", True),
    "scriptsize": ("small", "font-size:smaller", True),
    "tiny": ("small", "font-size:smaller", True),
    "large": ("span", "font-size:larger", True),
    "Large": ("span", "font-size:larger", True),
    "LARGE": ("span", "font-size:larger", True),
    "huge": ("span", "font-size:larger", True),
    "Huge": ("span", "font-size:larger", True),
}

# Commands whose (single) argument is kept as ordinary text.
_TRANSPARENT = {
    "textsf", "textrm", "textnormal", "textmd", "textup", "mbox", "text",
    "hbox", "func", "mathrm", "makebox", "smash", "uppercase", "lowercase",
    "MakeUppercase", "MakeLowercase",
}
# Declarations that change nothing visible in HTML.
_NEUTRAL_DECLARATIONS = {
    "sffamily", "rmfamily", "normalsize", "normalfont", "mdseries", "upshape",
    "noindent", "indent", "raggedright", "raggedleft", "xspace", "relax",
    "protect", "hfill", "hfil", "vfill", "vfil", "strut", "nobreak",
    "frenchspacing", "nonfrenchspacing", "ignorespaces", "linebreak",
    "nolinebreak", "nopagebreak", "sloppy", "fussy", "mcprocent", "mcpercent",
    "unskip",
    "centering", "flushleft", "flushright", "selectfont", "dotfill",
}
# Commands that take arguments but produce nothing.
_SILENT_WITH_ARGUMENTS: Dict[str, int] = {
    "label": 1, "hspace": 1, "vspace": 1, "setlength": 2, "addtolength": 2,
    "phantom": 1, "hphantom": 1, "vphantom": 1, "rule": 2, "thispagestyle": 1,
    "pagestyle": 1, "setcounter": 2, "addtocounter": 2, "vskip": 0,
    "hskip": 0, "index": 1, "marginpar": 1, "caption": 0,
}
_PARAGRAPH_BREAKS = {
    "par", "medskip", "bigskip", "smallskip", "sideskift", "pageshift",
    "newpage", "clearpage", "pagebreak",
}
_LINE_BREAKS = {"newline", "nylinie"}
_SPACES = {
    ",": " ", ";": " ", ":": " ", " ": " ", "!": "", "/": "", "-": "",
    "@": "", "quad": "&nbsp;&nbsp;", "qquad": "&nbsp;&nbsp;&nbsp;&nbsp;",
    "enspace": "&nbsp;", "thinspace": " ", "enskip": "&nbsp;",
    "negthinspace": "",
}
_SYMBOLS = {
    "ldots": "…", "dots": "…", "textellipsis": "…", "checkmark": "✓",
    "textbackslash": "\\", "textasciitilde": "~", "textasciicircum": "^",
    "LaTeX": "LaTeX", "TeX": "TeX", "S": "§", "P": "¶", "copyright": "©",
    "dag": "†", "ddag": "‡", "pounds": "£", "euro": "€", "textbar": "|",
    "textless": "<", "textgreater": ">", "aa": "å", "AA": "Å", "o": "ø",
    "O": "Ø", "ae": "æ", "AE": "Æ", "ss": "ß", "oe": "œ", "OE": "Œ",
    "l": "ł", "L": "Ł", "i": "ı", "j": "ȷ", "textendash": "–",
    "textemdash": "—", "textquoteleft": "‘", "textquoteright": "’",
    "textquotedblleft": "“", "textquotedblright": "”", "ldq": "“",
    "rdq": "”", "slash": "/", "textperiodcentered": "·", "textdegree": "°",
    "textregistered": "®", "texttrademark": "™", "textbullet": "•",
    "textasteriskcentered": "*", "textvisiblespace": "␣",
}
# clrscode keywords occasionally appear in running text ("the \For loop").
_KEYWORDS = {
    "If": "if", "Then": "then", "Else": "else", "ElseIf": "else if",
    "For": "for", "To": "to", "Downto": "downto", "While": "while", "Do": "do",
    "Repeat": "repeat", "Until": "until", "Return": "return", "Spawn": "spawn",
    "Sync": "sync", "Error": "error", "Goto": "goto", "By": "by",
}

_ACCENTS = {
    '"': "\u0308", "'": "\u0301", "`": "\u0300", "^": "\u0302", "~": "\u0303",
    "=": "\u0304", ".": "\u0307", "u": "\u0306", "v": "\u030c", "H": "\u030b",
    "c": "\u0327", "r": "\u030a", "k": "\u0328", "d": "\u0323", "b": "\u0331",
    "t": "\u0361",
}

# Math-mode rewrites so that document macros render in MathJax.
_MATH_RENAMES = {
    "proc": "text", "const": "text", "textsc": "text", "id": "mathit",
    "func": "mathrm", "emph": "textit", "nylinie": "\\",
}
_MATH_DROPS = {
    "xspace", "sc", "bf", "it", "rm", "tt", "sf", "em", "small",
    "footnotesize", "scriptsize", "ensuremath", "noindent", "protect",
    "strut", "relax",
}

_MACRO_PATTERN = re.compile(r"\\\\|\\([A-Za-z@]+)")
_MATH_GROUP_FONTS = {
    "bf": "mathbf", "it": "mathit", "rm": "mathrm", "tt": "mathtt",
    "sf": "mathsf", "sc": "text", "cal": "mathcal",
}
_MATH_GROUP_FONT_PATTERN = re.compile(
    r"\{\s*\\(bf|it|rm|tt|sf|sc|cal)\b\s*([^{}]*)\}"
)


@dataclass(frozen=True)
class Macro:
    name: str
    arity: int
    default: Optional[str]
    body: str


# Exam-structure macros are consumed by the parser and must never be expanded
# into fragments.
STRUCTURAL_MACROS = {
    "multiplechoicestart", "multiplechoiceslut", "spoergsmaal", "etsvar",
    "fleresvar", "mulighederstart", "mulighederslut", "svar", "itxsvar",
    "korrekt", "forklaring", "punkt", "qtipoints", "medsvar", "svarside",
    # English spellings of the same macros (see source.MACRO_ALIASES).
    "multiplechoiceend", "question", "oneanswer", "multipleanswers",
    "optionsstart", "optionsend", "answer", "itxanswer", "correct",
    "explanation", "subquestion", "withanswers", "answerpage",
    "section", "subsection", "item", "begin", "end", "newcommand",
    "renewcommand", "providecommand", "def",
}


def extract_macros(source: str) -> Dict[str, Macro]:
    r"""Collect ``\newcommand``-style definitions from a LaTeX document.

    Later definitions override earlier ones, so a definition in the
    ``\else`` branch of an answers switch wins, as it does in LaTeX when the
    switch is off.  ``\DeclareMathOperator`` declarations are recorded as
    ``\operatorname`` macros.
    """
    text = strip_comments(source)
    macros: Dict[str, Macro] = {}
    header = re.compile(
        r"\s*\\(?:newcommand|renewcommand|providecommand)\*?\s*"
        r"(?:\{\s*\\([A-Za-z@]+)\s*\}|\\([A-Za-z@]+))"
    )
    for start, end in _command_definition_spans(text):
        definition = text[start:end]
        match = header.match(definition)
        if not match:
            continue
        name = match.group(1) or match.group(2)
        cursor = match.end()
        arity = 0
        default: Optional[str] = None
        count = re.compile(r"\s*\[\s*([0-9])\s*\]").match(definition, cursor)
        if count:
            arity = int(count.group(1))
            cursor = count.end()
            optional = re.compile(r"\s*\[").match(definition, cursor)
            if optional:
                closing = definition.find("]", optional.end())
                if closing < 0:
                    continue
                default = definition[optional.end():closing]
                cursor = closing + 1
        try:
            body, _ = _balanced_group(definition, cursor, f"\\{name}")
        except ConversionError:
            continue
        macros[name] = Macro(name, arity, default, body)
    for match in re.finditer(
        r"\\DeclareMathOperator\*?\s*\{\s*\\([A-Za-z@]+)\s*\}", text
    ):
        try:
            body, _ = _balanced_group(text, match.end(), "\\DeclareMathOperator")
        except ConversionError:
            continue
        macros[match.group(1)] = Macro(
            match.group(1), 0, None, r"\operatorname{" + body + "}"
        )
    return macros


def _read_argument(text: str, cursor: int) -> Tuple[str, int]:
    """Read one undelimited macro argument starting at ``cursor``."""
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    if cursor >= len(text):
        return "", cursor
    if text[cursor] == "{":
        return _balanced_group(text, cursor, "a macro argument")
    if text[cursor] == "\\":
        match = re.compile(r"\\(?:[A-Za-z@]+\*?|.)", re.DOTALL).match(text, cursor)
        if match:
            return match.group(0), match.end()
    return text[cursor], cursor + 1


def expand_macros(text: str, macros: Dict[str, Macro], limit: int = 100) -> str:
    """Expand user macros so that MathJax and the HTML converter see plain LaTeX."""
    if not macros:
        return text
    for _ in range(limit):
        output: List[str] = []
        position = 0
        changed = False
        for match in _MACRO_PATTERN.finditer(text):
            name = match.group(1)
            if (
                match.start() < position
                or not name
                or name in STRUCTURAL_MACROS
                or name not in macros
            ):
                continue
            macro = macros[name]
            cursor = match.end()
            arguments: List[str] = []
            if macro.default is not None:
                optional = re.compile(r"\s*\[").match(text, cursor)
                if optional:
                    closing = text.find("]", optional.end())
                    if closing < 0:
                        raise ConversionError(
                            f"Unclosed optional argument of \\{name}"
                        )
                    arguments.append(text[optional.end():closing])
                    cursor = closing + 1
                else:
                    arguments.append(macro.default)
            while len(arguments) < macro.arity:
                argument, cursor = _read_argument(text, cursor)
                arguments.append(argument)
            body = macro.body
            for index, argument in enumerate(arguments, start=1):
                body = body.replace(f"#{index}", argument)
            body = body.replace("##", "#")
            output.append(text[position:match.start()])
            output.append(body)
            # A trailing space after a parameterless command is consumed by TeX.
            if macro.arity == 0 and cursor < len(text) and text[cursor] == " ":
                cursor += 1
            position = cursor
            changed = True
        output.append(text[position:])
        text = "".join(output)
        if not changed:
            return text
    raise ConversionError("LaTeX macro expansion did not terminate")


def _image_tag(image: RenderedImage, alt: str) -> str:
    encoded = base64.b64encode(image.path.read_bytes()).decode("ascii")
    return (
        f'<img src="data:image/png;base64,{encoded}" '
        f'alt="{html.escape(alt, quote=True)}" '
        f'width="{image.width}" height="{image.height}" '
        f'style="max-width:100%;height:auto">'
    )


def _clean_math(content: str) -> str:
    def replace(match: "re.Match[str]") -> str:
        name = match.group(1)
        if not name:
            return match.group(0)
        if name in _MATH_RENAMES:
            return "\\" + _MATH_RENAMES[name]
        if name in _MATH_DROPS:
            return ""
        return match.group(0)

    content = _MATH_GROUP_FONT_PATTERN.sub(
        lambda match: (
            "\\" + _MATH_GROUP_FONTS[match.group(1)] + "{" + match.group(2).strip() + "}"
        ),
        content,
    )
    cleaned = _MACRO_PATTERN.sub(replace, content)
    return html.escape(cleaned.strip(), quote=False)


def _assemble(stream: str) -> str:
    """Turn a marker-annotated inline stream into paragraphs and blocks."""
    blocks: List[str] = []
    inline: List[str] = []

    def flush() -> None:
        text = re.sub(r"[ \t\n]+", " ", "".join(inline)).strip()
        inline.clear()
        text = re.sub(r"^(?:<br>\s*)+|(?:\s*<br>)+$", "", text).strip()
        text = re.sub(r"^(?:&nbsp;)+\s*", "", text)
        if text:
            blocks.append(f"<p>{text}</p>")

    in_block = False
    for piece in re.split(f"({_MARKERS})", stream):
        if piece == _PAR:
            flush()
        elif piece == _BLOCK_START:
            flush()
            in_block = True
        elif piece == _BLOCK_END:
            in_block = False
        elif in_block:
            blocks.append(piece)
        else:
            inline.append(piece)
    flush()
    return "".join(blocks)


def _wrap(inner: str, tag: str, style: str) -> str:
    if re.search(_MARKERS, inner):
        return f'{_BLOCK_START}<div style="{style}">{_assemble(inner)}</div>{_BLOCK_END}'
    if tag == "span" or style.startswith("font-size"):
        return f'<span style="{style}">{inner}</span>'
    return f"<{tag}>{inner}</{tag}>"


def section_labels(source: str) -> Dict[str, str]:
    r"""Map ``\label`` keys to the numbers of the sections containing them.

    Multiple-choice questions are ``\section`` headings in the printed exam
    (``\spoergsmaal`` or ``\question`` expands to one), so they share the counter with the
    written problems, exactly as LaTeX numbers them.
    """
    text = strip_comments(source)
    pattern = re.compile(
        r"^[ \t]*\\(?:section|spoergsmaal|question)(?![A-Za-z@*])|\\label\s*\{([^{}]*)\}",
        re.MULTILINE,
    )
    labels: Dict[str, str] = {}
    number = 0
    for match in pattern.finditer(text):
        if match.group(1) is None:
            number += 1
        elif number:
            labels[match.group(1).strip()] = str(number)
    return labels


class HtmlConverter:
    """Convert LaTeX fragments to HTML, collecting or embedding figures."""

    def __init__(
        self,
        images: Optional[Sequence[RenderedImage]] = None,
        labels: Optional[Dict[str, str]] = None,
    ):
        self.images = list(images) if images is not None else None
        self.labels = labels or {}
        self.figures: List[str] = []
        self.unknown: Set[str] = set()

    def convert(self, latex: str) -> str:
        return _assemble(_Parser(self, strip_comments(latex)).parse())

    def figure(self, latex: str, alt: str) -> str:
        index = len(self.figures)
        self.figures.append(latex)
        if self.images is None:
            return ""
        if index >= len(self.images):
            raise ConversionError("Fewer rendered figures than LaTeX figures")
        return _image_tag(self.images[index], alt)


class _Parser:
    def __init__(self, converter: HtmlConverter, text: str):
        self.converter = converter
        self.text = text
        self.position = 0
        self.group_closed = False

    # -- scanning helpers -------------------------------------------------

    def _skip_spaces(self) -> None:
        while self.position < len(self.text) and self.text[self.position] in " \t":
            self.position += 1

    def _raw_argument(self) -> str:
        argument, self.position = _read_argument(self.text, self.position)
        return argument

    def _raw_optional(self) -> Optional[str]:
        saved = self.position
        self._skip_spaces()
        if self.position < len(self.text) and self.text[self.position] == "[":
            depth = 0
            for index in range(self.position, len(self.text)):
                if self.text[index] == "[":
                    depth += 1
                elif self.text[index] == "]":
                    depth -= 1
                    if depth == 0:
                        content = self.text[self.position + 1:index]
                        self.position = index + 1
                        return content
        self.position = saved
        return None

    def _argument(self) -> str:
        """Parse one argument to HTML."""
        self._skip_spaces()
        if self.position >= len(self.text):
            return ""
        if self.text[self.position] == "{":
            self.position += 1
            return self.parse_group()
        return self._sub(self._raw_argument())

    def _sub(self, latex: str) -> str:
        return _Parser(self.converter, latex).parse()

    # -- main loop --------------------------------------------------------

    def parse(self, stop: Optional[str] = None) -> str:
        output: List[str] = []
        text = self.text
        while self.position < len(text):
            character = text[self.position]
            if character == stop:
                self.position += 1
                break
            if character == "\\":
                output.append(self._command(stop))
                if self.group_closed:
                    break
            elif character == "{":
                self.position += 1
                output.append(self.parse_group())
            elif character == "}":
                self.position += 1
            elif character == "$":
                output.append(self._dollar_math())
            elif character == "\n":
                match = re.compile(r"\n[ \t]*\n[\s]*").match(text, self.position)
                if match:
                    output.append(_PAR)
                    self.position = match.end()
                else:
                    output.append(" ")
                    self.position += 1
            elif character == "~":
                output.append("&nbsp;")
                self.position += 1
            elif character == "-" and text.startswith("---", self.position):
                output.append("—")
                self.position += 3
            elif character == "-" and text.startswith("--", self.position):
                output.append("–")
                self.position += 2
            elif character == "`" and text.startswith("``", self.position):
                output.append("“")
                self.position += 2
            elif character == "'" and text.startswith("''", self.position):
                output.append("”")
                self.position += 2
            elif character == "`":
                output.append("‘")
                self.position += 1
            elif character in "<>&":
                output.append(html.escape(character))
                self.position += 1
            else:
                output.append(character)
                self.position += 1
        return "".join(output)

    def parse_group(self) -> str:
        inner = _Parser(self.converter, self.text)
        inner.position = self.position
        result = inner.parse("}")
        self.position = inner.position
        return result

    # -- mathematics ------------------------------------------------------

    def _dollar_math(self) -> str:
        text = self.text
        if text.startswith("$$", self.position):
            end = text.find("$$", self.position + 2)
            if end < 0:
                self.position += 2
                return "$$"
            content = text[self.position + 2:end]
            self.position = end + 2
            return self._math(content, display=True)
        end = self.position + 1
        while end < len(text):
            if text[end] == "\\":
                end += 2
                continue
            if text[end] == "$":
                break
            end += 1
        if end >= len(text):
            self.position += 1
            return "$"
        content = text[self.position + 1:end]
        self.position = end + 1
        return self._math(content, display=False)

    def _delimited_math(self, closing: str, display: bool) -> str:
        end = self.text.find(closing, self.position)
        if end < 0:
            raise ConversionError(f"Unclosed mathematics: missing {closing}")
        content = self.text[self.position:end]
        self.position = end + len(closing)
        return self._math(content, display)

    @staticmethod
    def _math(content: str, display: bool) -> str:
        cleaned = _clean_math(content)
        if display:
            return f"\\[{cleaned}\\]"
        return f"\\({cleaned}\\)"

    # -- commands ---------------------------------------------------------

    def _command(self, stop: Optional[str]) -> str:
        text = self.text
        self.position += 1
        if self.position >= len(text):
            return ""
        character = text[self.position]
        if not (character.isalpha() or character == "@"):
            self.position += 1
            if character == "\\":
                self._raw_optional()
                return "<br>"
            if character == "(":
                return self._delimited_math("\\)", display=False)
            if character == "[":
                return self._delimited_math("\\]", display=True)
            if character in _ACCENTS:
                return self._accent(_ACCENTS[character])
            if character in _SPACES:
                return _SPACES[character]
            return html.escape(character)

        start = self.position
        while self.position < len(text) and (
            text[self.position].isalpha() or text[self.position] == "@"
        ):
            self.position += 1
        name = text[start:self.position]
        if self.position < len(text) and text[self.position] == "*":
            self.position += 1
        self._skip_spaces()

        if name == "begin":
            return self._environment(self._raw_argument().strip())
        if name == "end":
            self._raw_argument()
            return ""
        if name in _FONTS:
            tag, style, declaration = _FONTS[name]
            if declaration:
                inner = self.parse(stop)
                self.group_closed = True
            else:
                inner = self._argument()
            return _wrap(inner, tag, style)
        if name in _PARAGRAPH_BREAKS:
            return _PAR
        if name in _LINE_BREAKS:
            return "<br>"
        if name in _SPACES:
            return _SPACES[name]
        if name in _SYMBOLS:
            return _SYMBOLS[name]
        if name in _KEYWORDS:
            return f"<b>{_KEYWORDS[name]}</b>"
        if name in _ACCENTS:
            return self._accent(_ACCENTS[name])
        if name in _TRANSPARENT:
            self._raw_optional()
            return self._argument()
        if name in _NEUTRAL_DECLARATIONS:
            return ""
        if name in _SILENT_WITH_ARGUMENTS:
            self._raw_optional()
            for _ in range(_SILENT_WITH_ARGUMENTS[name]):
                self._raw_argument()
            return ""
        if name == "vspace":
            self._raw_argument()
            return _PAR
        if name == "ensuremath":
            return self._math(self._raw_argument(), display=False)
        if name == "includegraphics":
            optional = self._raw_optional()
            path = self._raw_argument()
            latex = r"\includegraphics"
            if optional is not None:
                latex += f"[{optional}]"
            latex += f"{{{path}}}"
            return self.converter.figure(latex, f"[image: {path}]")
        if name in {"url", "href"}:
            target = self._raw_argument()
            label = self._argument() if name == "href" else html.escape(target)
            return f'<a href="{html.escape(target, quote=True)}">{label}</a>'
        if name in {"ref", "eqref", "pageref", "cite", "autoref", "nameref"}:
            self._raw_optional()
            key = self._raw_argument().strip("{}").strip()
            return html.escape(self.converter.labels.get(key, key))
        if name == "footnote":
            self._raw_optional()
            return f" ({self._argument()})"
        if name == "textcolor":
            color = self._raw_argument()
            return _wrap(self._argument(), "span", f"color:{html.escape(color, quote=True)}")
        if name == "color":
            color = self._raw_argument()
            inner = self.parse(stop)
            self.group_closed = True
            return _wrap(inner, "span", f"color:{html.escape(color, quote=True)}")
        if name == "colorbox":
            color = self._raw_argument()
            return _wrap(
                self._argument(), "span", f"background:{html.escape(color, quote=True)}"
            )
        if name in {"fbox", "framebox", "Ovalbox", "ovalbox", "shadowbox", "doublebox"}:
            self._raw_optional()
            self._raw_optional()
            return _wrap(self._argument(), "span", "border:1px solid;padding:2px")
        if name == "verb":
            delimiter = text[self.position]
            end = text.find(delimiter, self.position + 1)
            if end < 0:
                end = len(text)
            content = text[self.position + 1:end]
            self.position = end + 1
            return f"<code>{html.escape(content)}</code>"
        if name == "item":
            label = self._raw_optional()
            marker = f"<b>{self._sub(label)}</b> " if label else "• "
            return f"<br>{marker}"
        if name in _HEADINGS:
            self._raw_optional()
            tag = _HEADINGS[name]
            return f"{_BLOCK_START}<{tag}>{self._argument()}</{tag}>{_BLOCK_END}"
        if name in {"input", "include"}:
            self._raw_argument()
            self.converter.unknown.add(name)
            return ""

        # Unknown command: drop it, its options, and keep a braced argument's
        # text, which usually is the visible content.
        self.converter.unknown.add(name)
        self._raw_optional()
        saved = self.position
        self._skip_spaces()
        if self.position < len(text) and text[self.position] == "{":
            return self._argument()
        self.position = saved
        return ""

    def _accent(self, combining: str) -> str:
        argument = self._raw_argument()
        argument = argument.strip("{}").strip()
        if argument in {r"\i", r"\j"}:
            argument = "ı" if argument == r"\i" else "ȷ"
        if len(argument) == 1:
            return unicodedata.normalize("NFC", argument + combining)
        return self._sub(argument)

    # -- environments -----------------------------------------------------

    def _environment_body(self, name: str) -> str:
        pattern = re.compile(
            r"\\(begin|end)\s*\{" + re.escape(name) + r"\}"
        )
        depth = 1
        cursor = self.position
        while True:
            match = pattern.search(self.text, cursor)
            if not match:
                raise ConversionError(f"Missing \\end{{{name}}}")
            if match.group(1) == "begin":
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    body = self.text[self.position:match.start()]
                    self.position = match.end()
                    return body
            cursor = match.end()

    def _environment(self, name: str) -> str:
        base = name.rstrip("*")
        if base in _MATH_ENVIRONMENTS:
            body = self._environment_body(name)
            inner = _MATH_ENVIRONMENTS[base]
            if base == "math":
                return self._math(body, display=False)
            if inner is None:
                return self._math(body, display=True)
            replacement, options = inner
            return self._math(
                rf"\begin{{{replacement}}}{options}{body}\end{{{replacement}}}",
                display=True,
            )
        if name in _ALIGNED_BLOCKS:
            self._raw_optional()
            body = self._environment_body(name)
            style = _ALIGNED_BLOCKS[name]
            content = self.converter.convert(body)
            if style:
                return f'{_BLOCK_START}<div style="{style}">{content}</div>{_BLOCK_END}'
            return f"{_BLOCK_START}{content}{_BLOCK_END}"
        if name in _LIST_ENVIRONMENTS:
            optional = self._raw_optional()
            body = self._environment_body(name)
            return self._list(name, optional, body)
        if name in _VERBATIM_ENVIRONMENTS:
            self._raw_optional()
            body = self._environment_body(name)
            escaped = html.escape(body.strip("\n"))
            return f"{_BLOCK_START}<pre>{escaped}</pre>{_BLOCK_END}"
        body = self._environment_body(name)
        latex = rf"\begin{{{name}}}{body}\end{{{name}}}"
        alt = "[figure]" if base in _DRAWINGS else latex_to_plain(latex)
        image = self.converter.figure(latex, alt)
        return f"{_BLOCK_START}<p>{image}</p>{_BLOCK_END}"

    def _list(self, name: str, optional: Optional[str], body: str) -> str:
        tag = _LIST_ENVIRONMENTS[name]
        attributes = ""
        if name == "enumerate" and optional:
            for marker, kind in (
                ("Alph", "A"), ("alph", "a"), ("Roman", "I"), ("roman", "i"),
            ):
                if f"\\{marker}" in optional:
                    attributes = f' type="{kind}"'
                    break
            else:
                match = re.search(r"\(?([aAiI])[).]", optional)
                if match:
                    attributes = f' type="{match.group(1)}"'
        items: List[str] = []
        for label, item in _split_items(body):
            content = self.converter.convert(item)
            paragraphs = re.findall(r"<p>(.*?)</p>", content, flags=re.DOTALL)
            if len(paragraphs) == 1 and content == f"<p>{paragraphs[0]}</p>":
                content = paragraphs[0]
            if label is not None:
                content = f"<b>{self._sub(label)}</b> {content}"
            items.append(f"<li>{content}</li>")
        return f"{_BLOCK_START}<{tag}{attributes}>{''.join(items)}</{tag}>{_BLOCK_END}"


def _split_items(body: str) -> List[Tuple[Optional[str], str]]:
    r"""Split a list body at top-level ``\item`` commands."""
    items: List[Tuple[Optional[str], str]] = []
    label: Optional[str] = None
    start: Optional[int] = None
    depth = 0
    environment_depth = 0
    index = 0
    while index < len(body):
        character = body[index]
        if character == "\\":
            if body.startswith("\\\\", index):
                index += 2
                continue
            match = re.compile(r"\\([A-Za-z@]+)").match(body, index)
            if match:
                name = match.group(1)
                if name == "begin":
                    environment_depth += 1
                elif name == "end":
                    environment_depth -= 1
                elif name == "item" and depth == 0 and environment_depth == 0:
                    if start is not None:
                        items.append((label, body[start:index]))
                    cursor = match.end()
                    label = None
                    while cursor < len(body) and body[cursor] in " \t":
                        cursor += 1
                    if cursor < len(body) and body[cursor] == "[":
                        closing = body.find("]", cursor)
                        if closing >= 0:
                            label = body[cursor + 1:closing]
                            cursor = closing + 1
                    start = cursor
                    index = cursor
                    continue
                index = match.end()
                continue
            index += 2
            continue
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
        index += 1
    if start is not None:
        items.append((label, body[start:]))
    return items


def figure_latex(latex: str) -> List[str]:
    """Return the LaTeX of every figure the HTML conversion needs rendered."""
    converter = HtmlConverter()
    converter.convert(latex)
    return converter.figures


def latex_to_html(
    latex: str,
    images: Sequence[RenderedImage] = (),
    labels: Optional[Dict[str, str]] = None,
) -> Tuple[str, Set[str]]:
    """Convert a fragment to HTML; ``images`` must match ``figure_latex``."""
    converter = HtmlConverter(images, labels)
    result = converter.convert(latex)
    return result, converter.unknown


def unwrap_paragraph(markup: str) -> str:
    """Return a single paragraph's inline HTML without its ``<p>`` wrapper."""
    match = re.fullmatch(r"<p>(.*)</p>", markup, flags=re.DOTALL)
    if match and "<p>" not in match.group(1):
        return match.group(1)
    return markup
