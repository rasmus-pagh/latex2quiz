"""Dependency-free conversion of LaTeX fragments to Unicode alt text."""
from __future__ import annotations

import re
import unicodedata
from typing import List, Optional

from .source import strip_comments

_LATEX_UNICODE_SYMBOLS = {
    # Relations, sets, and logic.
    "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥",
    "ne": "≠", "neq": "≠", "approx": "≈", "equiv": "≡",
    "sim": "∼", "propto": "∝", "in": "∈", "notin": "∉",
    "subset": "⊂", "subseteq": "⊆", "supset": "⊃", "supseteq": "⊇",
    "cup": "∪", "cap": "∩", "bigcup": "⋃", "bigcap": "⋂",
    "setminus": "∖", "emptyset": "∅", "varnothing": "∅",
    "forall": "∀", "exists": "∃", "neg": "¬", "lnot": "¬",
    "land": "∧", "wedge": "∧", "lor": "∨", "vee": "∨",
    "mid": "∣", "vert": "|", "parallel": "∥",
    # Operators and delimiters.
    "sum": "∑", "prod": "∏", "int": "∫", "oint": "∮",
    "cdot": "·", "times": "×", "pm": "±", "mp": "∓",
    "infty": "∞", "partial": "∂", "nabla": "∇",
    "lfloor": "⌊", "rfloor": "⌋", "lceil": "⌈", "rceil": "⌉",
    "langle": "⟨", "rangle": "⟩", "backslash": "∖",
    "checkmark": "✓", "ell": "ℓ",
    # Arrows.
    "to": "→", "rightarrow": "→", "Rightarrow": "⇒",
    "leftarrow": "←", "gets": "←", "Leftarrow": "⇐",
    "leftrightarrow": "↔", "Leftrightarrow": "⇔", "mapsto": "↦",
    "uparrow": "↑", "downarrow": "↓", "nwarrow": "↖",
    "nearrow": "↗", "swarrow": "↙", "searrow": "↘",
    # Greek letters seen in the archive plus common companions.
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ",
    "epsilon": "ε", "varepsilon": "ε", "zeta": "ζ", "eta": "η",
    "theta": "θ", "vartheta": "ϑ", "iota": "ι", "kappa": "κ",
    "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ",
    "pi": "π", "varpi": "ϖ", "rho": "ρ", "sigma": "σ",
    "tau": "τ", "upsilon": "υ", "phi": "φ", "varphi": "ϕ",
    "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ",
    "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ", "Phi": "Φ",
    "Psi": "Ψ", "Omega": "Ω",
    # Typography and spacing.
    "ldots": "…", "dots": "…", "cdots": "⋯",
    "quad": " ", "qquad": " ", "enspace": " ", "medskip": "\n",
    "smallskip": "\n", "bigskip": "\n", "par": "\n",
}

_LATEX_WORD_OPERATORS = {
    "log", "lg", "ln", "min", "max", "gcd", "det", "exp",
    "Pr", "lim", "argmin", "argmax",
}

_LATEX_WRAPPERS = {
    "text", "textrm", "textsf", "texttt", "textbf", "textit", "textsc",
    "mathrm", "mathsf", "mathtt", "mathbf", "mathit", "mathcal",
    "mathfrak", "emph", "mbox", "fbox", "underline",
    "proc", "const", "id", "Procname", "operatorname",
}

_LATEX_DECLARATIONS = {
    "bf", "bfseries", "it", "itshape", "rm", "rmfamily", "sf",
    "sffamily", "tt", "ttfamily", "sc", "scshape", "small",
    "footnotesize", "scriptsize", "large", "Large", "LARGE", "huge", "Huge",
    "noindent", "left", "right", "bigl", "bigr", "Bigl", "Bigr",
}

_LATEX_ALGORITHM_WORDS = {
    "If": "if", "Then": "then", "Else": "else", "ElseIf": "else if",
    "For": "for", "To": "to", "While": "while", "Do": "do",
    "Return": "return", "Spawn": "spawn", "Sync": "sync", "End": "end",
}

_SUPERSCRIPT = str.maketrans("0123456789+-=()ni*", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱ*")
_SUBSCRIPT = str.maketrans("0123456789+-=()aeiox", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑᵢₒₓ")


class _LatexUnicodeParser:
    """Best-effort parser for readable, dependency-free LaTeX alternatives."""

    def __init__(self, source: str):
        self.source = source
        self.position = 0

    def parse(self, stop: Optional[str] = None) -> str:
        output: List[str] = []
        while self.position < len(self.source):
            character = self.source[self.position]
            if character == stop:
                self.position += 1
                break
            if character == "\\":
                output.append(self._command())
            elif character == "{":
                self.position += 1
                output.append(self.parse("}"))
            elif character == "}":
                self.position += 1
            elif character in "^_":
                self.position += 1
                output.append(self._script(character))
            elif character == "$":
                self.position += 1
            elif character == "~":
                self.position += 1
                output.append(" ")
            elif character == "&":
                self.position += 1
                output.append(" | ")
            else:
                output.append(character)
                self.position += 1
        return "".join(output)

    def _command(self) -> str:
        self.position += 1
        if self.position >= len(self.source):
            return ""
        character = self.source[self.position]
        if character == "\\":
            self.position += 1
            return "\n"
        if not (character.isalpha() or character == "@"):
            self.position += 1
            return {
                "%": "%", "{": "{", "}": "}", "_": "_", "#": "#",
                "&": "&", "$": "$", " ": " ", ",": " ", ";": " ",
                ":": " ", "!": "", "(": "", ")": "", "[": "", "]": "",
            }.get(character, character)

        start = self.position
        while self.position < len(self.source) and (
            self.source[self.position].isalpha() or self.source[self.position] == "@"
        ):
            self.position += 1
        name = self.source[start:self.position]
        if self.position < len(self.source) and self.source[self.position] == "*":
            self.position += 1
        while self.position < len(self.source) and self.source[self.position] in " \t":
            self.position += 1

        if name in _LATEX_UNICODE_SYMBOLS:
            return _LATEX_UNICODE_SYMBOLS[name]
        if name in _LATEX_WORD_OPERATORS:
            return f" {name} "
        if name in _LATEX_ALGORITHM_WORDS:
            return f" {_LATEX_ALGORITHM_WORDS[name]} "
        if name == "li":
            return "\n"
        if name in _LATEX_DECLARATIONS:
            return ""
        if name in {"frac", "tfrac", "dfrac"}:
            return f"({self._argument()})/({self._argument()})"
        if name in {"binom", "tbinom", "dbinom"}:
            return f"C({self._argument()}, {self._argument()})"
        if name == "sqrt":
            index = self._optional_argument()
            radicand = self._argument()
            return f"√{'[' + index + ']' if index else ''}({radicand})"
        if name in {"overset", "underset"}:
            annotation = self._argument()
            base = self._argument()
            marker = "^" if name == "overset" else "_"
            return f"{base}{marker}({annotation})"
        if name in _LATEX_WRAPPERS:
            return self._argument()
        if name == "mathbb":
            value = self._argument()
            return value.translate(str.maketrans({
                "N": "ℕ", "Z": "ℤ", "Q": "ℚ", "R": "ℝ",
                "C": "ℂ", "H": "ℍ", "P": "ℙ",
            }))
        if name in {"textcolor", "colorbox"}:
            self._argument()
            return self._argument()
        if name == "color":
            self._argument()
            return ""
        if name == "includegraphics":
            self._optional_argument()
            return f"[image: {self._argument()}]"
        if name == "href":
            self._argument()
            return self._argument()
        if name in {"url", "ref", "pageref"}:
            return self._argument()
        if name in {"begin", "end"}:
            self._argument()
            return "\n" if name == "end" else ""
        if name in {"label", "vspace", "hspace", "setlength", "addtolength"}:
            self._optional_argument()
            self._argument()
            return ""
        if name == "item":
            self._optional_argument()
            return "\n• "
        if name == "not":
            return "¬"

        # Unknown formatting-style macros commonly wrap useful text. Preserve
        # that argument while discarding the command itself and its options.
        self._optional_argument()
        saved = self.position
        self._skip_spaces()
        if self.position < len(self.source) and self.source[self.position] == "{":
            return self._argument()
        self.position = saved
        return ""

    def _argument(self) -> str:
        self._skip_spaces()
        if self.position >= len(self.source):
            return ""
        if self.source[self.position] == "{":
            self.position += 1
            return self.parse("}")
        if self.source[self.position] == "\\":
            return self._command()
        character = self.source[self.position]
        self.position += 1
        return character

    def _optional_argument(self) -> str:
        saved = self.position
        self._skip_spaces()
        if self.position >= len(self.source) or self.source[self.position] != "[":
            self.position = saved
            return ""
        self.position += 1
        depth = 1
        start = self.position
        while self.position < len(self.source) and depth:
            if self.source[self.position] == "[":
                depth += 1
            elif self.source[self.position] == "]":
                depth -= 1
                if depth == 0:
                    content = self.source[start:self.position]
                    self.position += 1
                    return _LatexUnicodeParser(content).parse()
            self.position += 1
        return ""

    def _script(self, marker: str) -> str:
        value = self._argument().strip()
        if marker == "^" and value == "*":
            return "*"
        table = _SUPERSCRIPT if marker == "^" else _SUBSCRIPT
        translated = value.translate(table)
        supported = all(
            character.translate(table) != character or not character.isalnum()
            for character in value
        )
        if value and supported:
            return translated
        return f"{marker}({value})" if value else marker

    def _skip_spaces(self) -> None:
        while self.position < len(self.source) and self.source[self.position].isspace():
            self.position += 1


def latex_to_plain(text: str) -> str:
    """Convert a LaTeX fragment to a readable Unicode text alternative."""
    plain = _LatexUnicodeParser(strip_comments(text)).parse()
    plain = unicodedata.normalize("NFC", plain)
    plain = "".join(
        character
        for character in plain
        if character in "\n\t" or ord(character) >= 32
    )
    relations = "≤≥≠≈≡∼∝∈∉⊂⊆⊃⊇∪∩∖∣⇒⇐⇔↦←→"
    plain = re.sub(f" *([{relations}]) *", r" \1 ", plain)
    plain = re.sub(r"[ \t]+", " ", plain)
    plain = re.sub(r" *\n *", "\n", plain)
    plain = re.sub(r"\n{3,}", "\n\n", plain)
    plain = re.sub(r" +([,.;:!?\)])", r"\1", plain)
    plain = re.sub(r"\( +", "(", plain)
    plain = plain.strip()
    return plain or "LaTeX content"

