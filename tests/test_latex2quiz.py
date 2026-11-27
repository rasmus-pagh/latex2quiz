import ast
import base64
import importlib
import json
import re
import struct
import shutil
import subprocess
import tempfile
import unittest
import uuid
import xml.etree.ElementTree as ET
import zipfile
from decimal import Decimal
from pathlib import Path

import latex2quiz
import latex2quiz_lib


SAMPLE = r"""
% A definition must not be mistaken for the section start.
\newcommand{\multiplechoicestart}{}
\multiplechoicestart

\spoergsmaal{Nested {title}}
What is $1+1$? % ignored comment with \svar
\etsvar
\mulighederstart
\svar 1
\svar {$2$} \korrekt
\itxsvar{plain legacy override}
\svar 3
\mulighederslut
\forklaring{Because $1+1=2$.}

\spoergsmaal{Several}
Choose the letters.
\fleresvar
\mulighederstart
\svar A \korrekt
\svar B
\svar C \korrekt
\mulighederslut

\multiplechoiceslut

\section*{Written questions}
\section{Proofs (6\%)}
Shared setup with $x=2$.

\punkt{a)}{Prove the first claim.}
\forklaring{First solution.}

Additional setup with \includegraphics{diagram.pdf}.
\punkt{b)}
Prove the second claim.
\forklaring{Second solution.}
"""


class ParserTests(unittest.TestCase):
    def test_parse_legacy_format(self):
        questions, warnings = latex2quiz.parse_questions(SAMPLE)
        self.assertEqual([], warnings)
        self.assertEqual(2, len(questions))
        self.assertEqual("Nested {title}", questions[0].title)
        self.assertEqual("single", questions[0].kind)
        self.assertEqual([False, True, False], [a.correct for a in questions[0].answers])
        self.assertNotIn("itxsvar", questions[0].answers[1].latex)
        self.assertEqual("multiple", questions[1].kind)
        self.assertEqual(2, sum(a.correct for a in questions[1].answers))

    def test_missing_type_is_inferred(self):
        source = SAMPLE.replace(r"\fleresvar", "", 1)
        questions, warnings = latex2quiz.parse_questions(source)
        self.assertEqual("multiple", questions[1].kind)
        self.assertEqual(1, len(warnings))

    def test_single_requires_one_correct_answer(self):
        source = SAMPLE.replace(r"\svar 3", r"\svar 3 \korrekt", 1)
        with self.assertRaisesRegex(latex2quiz.ConversionError, "uses \\\\etsvar"):
            latex2quiz.parse_questions(source)

    def test_english_macro_names_parse_like_danish(self):
        english = SAMPLE
        for danish, name in sorted(
            latex2quiz.MACRO_ALIASES.items(), key=lambda pair: -len(pair[0])
        ):
            english = re.sub(rf"\\{danish}(?![A-Za-z@])", lambda _m: "\\" + name, english)
        self.assertNotIn(r"\svar", english)
        self.assertEqual(latex2quiz.parse_questions(SAMPLE), latex2quiz.parse_questions(english))
        self.assertEqual(
            latex2quiz.parse_written_sections(SAMPLE),
            latex2quiz.parse_written_sections(english),
        )

    def test_fragment_command_definitions_reach_the_render_preamble(self):
        fragment = "\\newcommand{\\shared}{text}\n" + SAMPLE
        self.assertIn(
            "\\newcommand{\\shared}{text}",
            latex2quiz._extract_body_command_definitions(fragment),
        )

    def test_item_used_as_answer_is_rejected(self):
        source = SAMPLE.replace(r"\svar 3", r"\item 3", 1)
        with self.assertRaisesRegex(latex2quiz.ConversionError, "starts with \\\\item"):
            latex2quiz.parse_questions(source)

    def test_item_inside_list_in_answer_is_allowed(self):
        source = SAMPLE.replace(
            r"\svar 3",
            "\\svar 3\n\\begin{itemize}\n\\item nested\n\\end{itemize}",
            1,
        )
        questions, _ = latex2quiz.parse_questions(source)
        self.assertIn("nested", questions[0].answers[-1].latex)

    def test_question_and_written_part_can_override_default_points(self):
        source = SAMPLE.replace(
            r"\etsvar", r"\etsvar" "\n" r"\qtipoints{2.5}", 1
        ).replace(
            r"\punkt{a)}{Prove the first claim.}",
            r"\punkt{a)}{\qtipoints{3}Prove the first claim.}",
            1,
        )
        questions, _ = latex2quiz.parse_questions(source)
        sections = latex2quiz.parse_written_sections(source)
        self.assertEqual(2.5, questions[0].points)
        self.assertNotIn("qtipoints", questions[0].stem)
        self.assertEqual(3.0, sections[0].subquestions[0].points)
        self.assertIsNone(sections[0].subquestions[1].points)
        self.assertNotIn("qtipoints", sections[0].subquestions[0].stem)

    def test_points_annotation_must_be_positive_number(self):
        source = SAMPLE.replace(r"\etsvar", r"\etsvar\qtipoints{zero}", 1)
        with self.assertRaisesRegex(latex2quiz.ConversionError, "invalid points"):
            latex2quiz.parse_questions(source)

    def test_escaped_percent_is_not_a_comment(self):
        self.assertEqual("100\\% sure \n", latex2quiz.strip_comments("100\\% sure % no\n"))

    def test_latex_to_plain_uses_structural_unicode(self):
        source = (
            r"T(n)=\Theta(n\log n),\quad x\in\mathbb{R},\quad "
            r"x\leq\sqrt{n},\quad \frac{n^2}{2}+\binom{n}{k}"
        )
        self.assertEqual(
            "T(n)=Θ(n log n), x ∈ ℝ, x ≤ √(n), (n²)/(2)+C(n, k)",
            latex2quiz.latex_to_plain(source),
        )

    def test_latex_to_plain_preserves_legacy_converter_macros(self):
        source = (
            r"\lg n + \sum_{i=1}^n i; \lfloor x\rfloor; A^*; "
            r"\langle a,b\rangle; x\ne y; \texttt{ABC}"
        )
        self.assertEqual(
            "lg n + ∑ᵢ₌₁ⁿ i; ⌊x⌋; A*; ⟨a,b⟩; x ≠ y; ABC",
            latex2quiz.latex_to_plain(source),
        )

    def test_latex_to_plain_handles_exam_macros_and_media(self):
        source = (
            r"100\% and {\bf bold}; \proc{Find}(A_i); "
            r"\Phi(H)\geq0; A\subseteq B; \includegraphics[width=2cm]{graph.pdf}"
        )
        self.assertEqual(
            "100% and bold; Find(Aᵢ); Φ(H) ≥ 0; A ⊆ B; [image: graph.pdf]",
            latex2quiz.latex_to_plain(source),
        )

    def test_body_command_definitions_are_promoted_and_removed_from_fragments(self):
        source = r"""
\begin{document}
\newcommand{\sharedproblem}[1]{Shared #1}
\sharedproblem{setup}
\end{document}
"""
        self.assertIn(
            r"\newcommand{\sharedproblem}[1]{Shared #1}",
            latex2quiz._extract_body_command_definitions(source),
        )
        cleaned = latex2quiz._clean_fragment(source)
        self.assertNotIn(r"\newcommand", cleaned)
        self.assertIn(r"\sharedproblem{setup}", cleaned)

    def test_written_section_keeps_order_without_repeating_context(self):
        sections = latex2quiz.parse_written_sections(SAMPLE)
        self.assertEqual(1, len(sections))
        self.assertEqual("Proofs (6\\%)", sections[0].title)
        self.assertEqual(6.0, sections[0].points)
        self.assertEqual(2, len(sections[0].subquestions))
        first, second = sections[0].subquestions
        self.assertEqual("a)", first.label)
        self.assertEqual("b)", second.label)
        self.assertIn("Shared setup", first.stem)
        self.assertNotIn("Shared setup", second.stem)
        self.assertNotIn("First solution", second.stem)
        self.assertNotIn("first claim", second.stem)
        self.assertIn("includegraphics{diagram.pdf}", second.stem)
        self.assertIn("second claim", second.stem)
        self.assertEqual("Second solution.", second.feedback)

    def test_all_repository_examples_parse(self):
        examples = Path(__file__).resolve().parents[1] / "ad-exams" / "danish"
        counts = {}
        for path in sorted(examples.glob("ad-*.tex")):
            questions, _warnings = latex2quiz.parse_questions(
                path.read_text(encoding="utf-8")
            )
            counts[path.name] = len(questions)
        self.assertEqual(8, len(counts))
        self.assertEqual(9, counts["ad-problems-2023-trial.tex"])
        self.assertTrue(all(count == 18 for name, count in counts.items() if name != "ad-problems-2023-trial.tex"))

        written_section_counts = {
            path.name: len(latex2quiz.parse_written_sections(path.read_text(encoding="utf-8")))
            for path in sorted(examples.glob("ad-*.tex"))
        }
        self.assertEqual(
            {
                "ad-problems-2024-june.tex": 4,
                "ad-problems-2023-april.tex": 4,
                "ad-problems-2024-april.tex": 3,
                "ad-problems-2026-april.tex": 3,
                "ad-problems-2025-june.tex": 3,
                "ad-problems-2026-june.tex": 3,
                "ad-problems-2025-march.tex": 3,
                "ad-problems-2023-trial.tex": 4,
            },
            written_section_counts,
        )
        subquestion_count = sum(
            len(section.subquestions)
            for path in sorted(examples.glob("ad-*.tex"))
            for section in latex2quiz.parse_written_sections(
                path.read_text(encoding="utf-8")
            )
        )
        self.assertEqual(62, subquestion_count)

    def test_english_translations_match_danish_structure(self):
        def structure(path):
            text = path.read_text(encoding="utf-8")
            questions, _ = latex2quiz.parse_questions(text)
            sections = latex2quiz.parse_written_sections(text)
            return (
                [(q.kind, q.points, tuple(a.correct for a in q.answers)) for q in questions],
                [
                    (s.points, tuple((sq.label, sq.points) for sq in s.subquestions))
                    for s in sections
                ],
            )

        root = Path(__file__).resolve().parents[1]
        checked = 0
        for course in ("ad", "dma"):
            for danish in sorted((root / f"{course}-exams" / "danish").glob(f"{course}-*.tex")):
                english = root / f"{course}-exams" / "english" / danish.name
                self.assertTrue(english.exists(), english)
                self.assertEqual(structure(danish), structure(english), danish.name)
                checked += 1
        self.assertEqual(11, checked)

    def test_all_dma_examples_parse(self):
        examples = Path(__file__).resolve().parents[1] / "dma-exams" / "danish"
        counts = {}
        for path in sorted(examples.glob("dma-*.tex")):
            text = path.read_text(encoding="utf-8")
            questions, _warnings = latex2quiz.parse_questions(text)
            counts[path.name] = (len(questions), len(latex2quiz.parse_written_sections(text)))
        self.assertEqual(
            {
                "dma-problems-2026-april.tex": (25, 0),
                "dma-problems-2026-january.tex": (25, 0),
                "dma-problems-2026-trial.tex": (25, 0),
            },
            counts,
        )


class XmlTests(unittest.TestCase):
    def setUp(self):
        self.questions, _ = latex2quiz.parse_questions(SAMPLE)
        self.written_sections = latex2quiz.parse_written_sections(SAMPLE)
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.rendered = {}
        for request in latex2quiz._render_requests(
            self.questions, self.written_sections, True, "da"
        ):
            path = self.root / f"{request.key}.png"
            path.write_bytes(b"not needed by XML builder")
            self.rendered[request.key] = latex2quiz.RenderedImage(path, request.alt, 100, 20)

    def tearDown(self):
        self.temporary.cleanup()

    def test_exactly_one_correct_item_still_allows_multiple_selections(self):
        tree = latex2quiz.build_item_xml(
            self.questions[0], self.rendered, 4.0, "da", False, True
        )
        root = tree.getroot()
        ns = {"q": latex2quiz.QTI_NS}
        declaration = root.find("q:responseDeclaration", ns)
        self.assertEqual("multiple", declaration.attrib["cardinality"])
        self.assertEqual(
            ["q001_a002"],
            [element.text for element in root.findall("q:responseDeclaration/q:correctResponse/q:value", ns)],
        )
        interaction = root.find("q:itemBody/q:choiceInteraction", ns)
        self.assertEqual("3", interaction.attrib["maxChoices"])
        self.assertIsNone(interaction.find("q:prompt", ns))
        entries = root.findall("q:responseDeclaration/q:mapping/q:mapEntry", ns)
        self.assertEqual(["-2", "4", "-2"], [entry.attrib["mappedValue"] for entry in entries])
        self.assertIsNotNone(root.find("q:modalFeedback", ns))

    def test_mc_instruction_is_part_of_the_rendered_stem(self):
        requests = latex2quiz._render_requests(
            self.questions, self.written_sections, True, "da"
        )
        stems = {request.key: request.latex for request in requests}
        self.assertIn(
            "Der er præcis ét korrekt svar, men du må vælge flere.",
            stems["q001-stem"],
        )
        self.assertIn(
            "Vælg ét eller flere korrekte svar.", stems["q002-stem"]
        )

    def test_stem_starts_with_the_title_and_percentage(self):
        stem = latex2quiz._mc_stem_latex(self.questions[0], "da", 4.0)
        self.assertTrue(stem.startswith("\\section*{Nested {title} (4\\%)}"))
        stem = latex2quiz._mc_stem_latex(self.questions[1], "en", 2.5)
        self.assertTrue(stem.startswith("\\section*{Several (2.5\\%)}"))
        self.assertEqual("<h3>Several (2.5%)</h3><p>Choose the letters.</p><p>Select one or more correct answers.</p>",
                         latex2quiz.HtmlConverter().convert(stem))
        self.assertTrue(self.written_sections[0].subquestions[0].stem.startswith("\\section*{Proofs (6\\%)}"))

    def test_multiple_answer_mapping(self):
        tree = latex2quiz.build_item_xml(
            self.questions[1], self.rendered, 4.0, "en", False, False
        )
        root = tree.getroot()
        ns = {"q": latex2quiz.QTI_NS}
        entries = root.findall("q:responseDeclaration/q:mapping/q:mapEntry", ns)
        self.assertEqual(["2", "-4", "2"], [entry.attrib["mappedValue"] for entry in entries])
        processing = root.find("q:responseProcessing", ns)
        self.assertIn("map_response", processing.attrib["template"])

    def test_mapping_totals_are_exact_even_when_split_into_thirds(self):
        positive = latex2quiz._split_mapping_total(4.0, 3)
        negative = latex2quiz._split_mapping_total(-4.0, 3)
        self.assertEqual(Decimal("4"), sum(map(Decimal, positive), Decimal(0)))
        self.assertEqual(Decimal("-4"), sum(map(Decimal, negative), Decimal(0)))
        self.assertEqual(
            Decimal("0"),
            sum(map(Decimal, positive + negative), Decimal(0)),
        )

    def test_written_section_is_one_canvas_compatible_ordered_essay(self):
        tree = latex2quiz.build_written_item_xml(
            self.written_sections[0], self.rendered, 6.0, "da", True, 15
        )
        root = tree.getroot()
        ns = {"q": latex2quiz.QTI_NS}
        declarations = root.findall("q:responseDeclaration", ns)
        interactions = root.findall("q:itemBody/q:extendedTextInteraction", ns)
        self.assertEqual(["RESPONSE"], [d.attrib["identifier"] for d in declarations])
        self.assertEqual(["RESPONSE"], [i.attrib["responseIdentifier"] for i in interactions])
        self.assertTrue(all(d.attrib["baseType"] == "string" for d in declarations))
        self.assertTrue(all(i.attrib["format"] == "xhtml" for i in interactions))
        self.assertTrue(all(i.attrib["expectedLines"] == "15" for i in interactions))
        outcome = root.find("q:outcomeDeclaration[@identifier='SCORE']", ns)
        self.assertEqual("6", outcome.attrib["normalMaximum"])
        images = root.findall("q:itemBody/q:div/q:img", ns)
        self.assertEqual(
            ["assets/w001-part-001.png", "assets/w001-part-002.png"],
            [image.attrib["src"] for image in images],
        )
        self.assertIsNotNone(root.find("q:modalFeedback", ns))

    def test_question_points_override_changes_score_and_mapping(self):
        source = SAMPLE.replace(r"\etsvar", r"\etsvar\qtipoints{2}", 1)
        questions, _ = latex2quiz.parse_questions(source)
        tree = latex2quiz.build_item_xml(
            questions[0], self.rendered, 4.0, "da", False, False
        )
        root = tree.getroot()
        ns = {"q": latex2quiz.QTI_NS}
        outcome = root.find("q:outcomeDeclaration[@identifier='SCORE']", ns)
        self.assertEqual("2", outcome.attrib["normalMaximum"])
        self.assertEqual("Nested title (2%)", root.attrib["title"])
        entries = root.findall("q:responseDeclaration/q:mapping/q:mapEntry", ns)
        self.assertEqual(["-1", "2", "-1"], [e.attrib["mappedValue"] for e in entries])

    def test_written_section_points_can_be_explicit(self):
        source = SAMPLE.replace(
            r"\section{Proofs (6\%)}",
            r"\section{Proofs}\qtipoints{7}",
            1,
        )
        sections = latex2quiz.parse_written_sections(source)
        self.assertEqual(7.0, sections[0].points)
        self.assertNotIn("qtipoints", sections[0].subquestions[0].stem)
        tree = latex2quiz.build_written_item_xml(
            sections[0], self.rendered, 4.0, "da", False, 12
        )
        ns = {"q": latex2quiz.QTI_NS}
        outcome = tree.getroot().find(
            "q:outcomeDeclaration[@identifier='SCORE']", ns
        )
        self.assertEqual("7", outcome.attrib["normalMaximum"])

    def test_manifest_has_one_resource_per_question(self):
        tree = latex2quiz.build_manifest(
            "package-test", self.questions, self.written_sections, True
        )
        root = tree.getroot()
        resources = root.findall(f"{{{latex2quiz.IMSCP_NS}}}resources/{{{latex2quiz.IMSCP_NS}}}resource")
        self.assertEqual(3, len(resources))
        self.assertEqual("imsqti_item_xmlv2p1", resources[0].attrib["type"])


class HtmlTests(unittest.TestCase):
    def convert(self, latex, images=None, labels=None):
        converter = latex2quiz.HtmlConverter(images, labels)
        return converter.convert(latex), converter

    def test_text_and_math_become_paragraphs_with_mathjax_delimiters(self):
        markup, converter = self.convert(
            "Let $x<y$ and \\emph{note} that\n\n"
            "\\[\\sum_{i=1}^n i\\] holds.\\par Next \\textbf{bold} --- done."
        )
        self.assertEqual(
            "<p>Let \\(x&lt;y\\) and <i>note</i> that</p>"
            "<p>\\[\\sum_{i=1}^n i\\] holds.</p>"
            "<p>Next <b>bold</b> — done.</p>",
            markup,
        )
        self.assertEqual([], converter.figures)
        self.assertEqual(set(), converter.unknown)

    def test_exam_macros_are_rewritten_for_mathjax(self):
        markup, _ = self.convert(
            "{\\sc Merge} runs $\\proc{Merge}(A)$ in $x\\in{\\bf R}$ "
            "with $\\id{key}$ and \\begin{align*}a &= b\\\\c &= d\\end{align*}"
        )
        self.assertIn('<span style="font-variant:small-caps">Merge</span>', markup)
        self.assertIn("\\(\\text{Merge}(A)\\)", markup)
        self.assertIn("\\(x\\in\\mathbf{R}\\)", markup)
        self.assertIn("\\(\\mathit{key}\\)", markup)
        self.assertIn(
            "\\[\\begin{aligned}a &amp;= b\\\\c &amp;= d\\end{aligned}\\]", markup
        )

    def test_lists_and_centering_become_html_blocks(self):
        markup, _ = self.convert(
            "Intro\\begin{enumerate}[label=(\\alph*)]\\item one\\item $2$\\end{enumerate}"
            "\\begin{center}Centered\\end{center}"
        )
        self.assertEqual(
            '<p>Intro</p><ol type="a"><li>one</li><li>\\(2\\)</li></ol>'
            '<div style="text-align:center"><p>Centered</p></div>',
            markup,
        )

    def test_unsupported_environments_and_graphics_become_figures(self):
        latex = (
            "Code: {\\small\\begin{codebox}\\li $x$\\End\\end{codebox}} "
            "and \\includegraphics[width=2cm]{g.pdf} then "
            "\\begin{center}\\begin{tikzpicture}\\node{a};\\end{tikzpicture}\\end{center}"
        )
        self.assertEqual(
            [
                "\\begin{codebox}\\li $x$\\End\\end{codebox}",
                "\\includegraphics[width=2cm]{g.pdf}",
                "\\begin{tikzpicture}\\node{a};\\end{tikzpicture}",
            ],
            latex2quiz.figure_latex(latex),
        )
        with tempfile.TemporaryDirectory() as temporary:
            png = Path(temporary) / "fig.png"
            png.write_bytes(b"\x89PNG fake")
            images = [latex2quiz.RenderedImage(png, "alt", 10, 5)] * 3
            markup, converter = self.convert(latex, images)
        self.assertEqual(3, len(converter.figures))
        self.assertEqual(3, markup.count('<img src="data:image/png;base64,'))
        self.assertIn('alt="[figure]"', markup)
        self.assertIn('alt="x end"', markup)
        self.assertIn("<p>and <img", markup)

    def test_unknown_commands_keep_argument_text_and_are_reported(self):
        markup, converter = self.convert("A \\mystery[opt]{kept} B \\ref{sec:x}")
        self.assertEqual("<p>A kept B sec:x</p>", markup)
        self.assertEqual({"mystery"}, converter.unknown)
        markup, _ = self.convert("opgave~\\ref{sec:x}", labels={"sec:x": "17"})
        self.assertEqual("<p>opgave&nbsp;17</p>", markup)

    def test_document_macros_are_expanded_and_labels_resolved(self):
        source = r"""
\newcommand{\spoergsmaal}[1]{\section{#1}}
\newcommand{\twice}[2][x]{#1 and #2}
\newcommand{\problem}{Shared $\Theta(n)$}
\DeclareMathOperator{\polylog}{polylog}
\begin{document}
\spoergsmaal{First}\label{q:one}
\section{Second}\label{sec:two}
"""
        macros = latex2quiz.extract_macros(source)
        self.assertNotIn("spoergsmaal", latex2quiz.STRUCTURAL_MACROS - {"spoergsmaal"})
        expanded = latex2quiz.expand_macros(
            r"\twice{b} \twice[a]{c}: \problem\ $\polylog n$ \spoergsmaal{x}",
            macros,
        )
        self.assertEqual(
            r"x and b a and c: Shared $\Theta(n)$\ $\operatorname{polylog}n$ "
            r"\spoergsmaal{x}",
            expanded,
        )
        self.assertEqual(
            {"q:one": "1", "sec:two": "2"}, latex2quiz.section_labels(source)
        )
        with self.assertRaisesRegex(latex2quiz.ConversionError, "did not terminate"):
            latex2quiz.expand_macros(r"\loop", {"loop": latex2quiz.Macro("loop", 0, None, r"\loop")})


class LearnosityTests(unittest.TestCase):
    def setUp(self):
        self.questions, _ = latex2quiz.parse_questions(SAMPLE)
        self.written_sections = latex2quiz.parse_written_sections(SAMPLE)

    def test_mc_item_scores_match_the_qti_mapping(self):
        item = latex2quiz.build_mc_item(
            self.questions[1],
            "<p>stem</p>",
            ["A", "B", "C"],
            "<p>why</p>",
            4.0,
            False,
            "abc123",
        )
        self.assertEqual("Several (4%)", item["title"])
        self.assertEqual("Several (4%)", item["questions"][0]["data"]["title"])
        self.assertEqual("published", item["status"])
        question = item["questions"][0]
        self.assertEqual(
            question["reference"], item["definition"]["widgets"][0]["reference"]
        )
        self.assertNotEqual(question["reference"], item["reference"])
        data = question["data"]
        self.assertEqual("mcq", data["type"])
        self.assertTrue(data["multiple_responses"])
        self.assertTrue(data["is_math"])
        self.assertEqual(0, data["minScore"])
        self.assertFalse(data["shuffle_options"])
        self.assertEqual(
            [{"label": "A", "value": "0"}, {"label": "B", "value": "1"}, {"label": "C", "value": "2"}],
            data["options"],
        )
        validation = data["validation"]
        self.assertEqual("partialMatch", validation["scoring_type"])
        self.assertTrue(validation["allow_negative_scores"])
        self.assertEqual({"score": 2, "value": ["0", "2"]}, validation["valid_response"])
        self.assertEqual(4, validation["penalty"])
        self.assertEqual({"distractor_rationale": "<p>why</p>"}, data["metadata"])
        self.assertEqual([4], latex2quiz.item_maximum_scores(item))

    def test_mc_item_references_are_fresh_uuids(self):
        first = latex2quiz.build_mc_item(self.questions[0], "", ["a", "b", "c"], None, 4.0, True, "d1")
        again = latex2quiz.build_mc_item(self.questions[0], "", ["a", "b", "c"], None, 4.0, True, "d1")
        references = {
            first["reference"], again["reference"],
            first["questions"][0]["reference"], again["questions"][0]["reference"],
        }
        self.assertEqual(4, len(references))
        for reference in references:
            self.assertEqual(4, uuid.UUID(reference).version)
        self.assertTrue(first["questions"][0]["data"]["shuffle_options"])
        self.assertNotIn("metadata", first["questions"][0]["data"])
        validation = first["questions"][0]["data"]["validation"]
        self.assertEqual({"score": 4, "value": ["1"]}, validation["valid_response"])
        self.assertEqual(2, validation["penalty"])

    def test_written_item_uses_section_total_and_template(self):
        item = latex2quiz.build_written_item(
            self.written_sections[0], "<p>parts</p>", "<p>solutions</p>", 4.0, "d1"
        )
        data = item["questions"][0]["data"]
        self.assertEqual("longtextV2", data["type"])
        self.assertEqual({"max_score": 6}, data["validation"])
        self.assertEqual({"sample_answer": "<p>solutions</p>"}, data["metadata"])
        self.assertEqual("Proofs (6%)", item["title"])

        export = {
            "data": [
                {
                    "questions": [
                        {
                            "type": "custom",
                            "data": {
                                "type": "custom",
                                "custom_type": "custom_type_long_essay_spell_check",
                                "js": {"question": "https://example/question.js"},
                                "stimulus": "old",
                                "validation": {"max_score": 1},
                            },
                            "metadata": {"name": "Essay (med stavekontrol)"},
                        }
                    ]
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "export.json"
            path.write_text(json.dumps(export), encoding="utf-8")
            template = latex2quiz.load_essay_template(path)
            path.write_text(json.dumps({"data": []}), encoding="utf-8")
            with self.assertRaisesRegex(latex2quiz.ConversionError, "No essay question"):
                latex2quiz.load_essay_template(path)
        item = latex2quiz.build_written_item(
            self.written_sections[0], "<p>parts</p>", None, 4.0, "d1", template
        )
        question = item["questions"][0]
        self.assertEqual("custom", question["type"])
        self.assertEqual({"name": "Essay (med stavekontrol)"}, question["metadata"])
        self.assertEqual("<p>parts</p>", question["data"]["stimulus"])
        self.assertEqual({"max_score": 6}, question["data"]["validation"])
        self.assertEqual("https://example/question.js", question["data"]["js"]["question"])
        self.assertNotIn("metadata", question["data"])
        self.assertTrue(question["data"]["is_math"])

    def test_essay_images_render_each_written_stem_as_one_figure(self):
        fragments = latex2quiz._html_fragments(
            SAMPLE, self.questions, self.written_sections, True, "da", essay_images=True, essay_parts=False
        )
        requests = latex2quiz._figure_requests(fragments)
        self.assertEqual(
            ["w001-part-001-figure-001", "w001-part-002-figure-001"],
            [r.key for r in requests],
        )
        self.assertIn("Shared setup", requests[0].latex)
        self.assertIn("includegraphics{diagram.pdf}", requests[1].latex)
        self.assertNotIn(latex2quiz.IMAGE_ENVIRONMENT, latex2quiz.figure_latex(fragments["q001-stem"]))

    def test_scores_are_rounded_once_to_three_decimals(self):
        source = SAMPLE.replace(
            "\\svar C \\korrekt",
            "\\svar C \\korrekt\n\\svar D \\korrekt\n\\svar E \\korrekt\n"
            "\\svar F \\korrekt\n\\svar G\n\\svar H",
        )
        questions, _ = latex2quiz.parse_questions(source)
        mst = questions[1]
        self.assertEqual((5, 3), (sum(a.correct for a in mst.answers), sum(not a.correct for a in mst.answers)))
        item = latex2quiz.build_mc_item(mst, "<p>s</p>", ["x"] * 8, None, 4.0, False, "d")
        validation = item["questions"][0]["data"]["validation"]
        self.assertEqual(0.8, validation["valid_response"]["score"])
        self.assertEqual(1.333, validation["penalty"])
        self.assertEqual(["0", "2", "3", "4", "5"], validation["valid_response"]["value"])
        self.assertEqual([], latex2quiz.validate_bank(latex2quiz.build_bank([item])))
        # All answers correct: no penalty and no division by zero.
        all_correct = SAMPLE.replace("\\svar B\n", "\\svar B \\korrekt\n", 1)
        questions, _ = latex2quiz.parse_questions(all_correct)
        item = latex2quiz.build_mc_item(questions[1], "", ["x"] * 3, None, 4.0, False, "d")
        self.assertEqual(0, item["questions"][0]["data"]["validation"]["penalty"])
        self.assertEqual(1.333, item["questions"][0]["data"]["validation"]["valid_response"]["score"])

    def test_correct_answers_map_like_the_qti_items_in_every_exam(self):
        root = Path(__file__).resolve().parents[1]
        paths = sorted((root / "ad-exams" / "danish").glob("ad-*.tex")) + sorted(
            (root / "dma-exams" / "danish").glob("dma-*.tex")
        )
        checked = 0
        not_first = 0
        for path in paths:
            questions, _ = latex2quiz.parse_questions(path.read_text(encoding="utf-8"))
            for question in questions:
                labels = [f"o{index}" for index in range(len(question.answers))]
                item = latex2quiz.build_mc_item(question, "s", labels, None, 4.0, False, "d")
                data = item["questions"][0]["data"]
                rendered = {}
                qid = f"q{question.number:03d}"
                for key in [f"{qid}-stem"] + [f"{qid}-answer-{i:03d}" for i in range(1, len(labels) + 1)]:
                    rendered[key] = latex2quiz.RenderedImage(Path("x.png"), "alt", 1, 1)
                root = latex2quiz.build_item_xml(question, rendered, 4.0, "da", False, False).getroot()
                ns = {"q": latex2quiz.QTI_NS}
                qti_correct = [
                    element.text for element in root.findall("q:responseDeclaration/q:correctResponse/q:value", ns)
                ]
                expected = [str(int(identifier.rsplit("_a", 1)[1]) - 1) for identifier in qti_correct]
                self.assertEqual(expected, data["validation"]["valid_response"]["value"], path.name)
                self.assertEqual([str(i) for i in range(len(labels))], [o["value"] for o in data["options"]])
                self.assertEqual(labels, [o["label"] for o in data["options"]])
                mapped = {
                    entry.attrib["mapKey"]: Decimal(entry.attrib["mappedValue"])
                    for entry in root.findall("q:responseDeclaration/q:mapping/q:mapEntry", ns)
                }
                correct_total = sum(mapped[identifier] for identifier in qti_correct)
                self.assertEqual(float(correct_total), round(data["validation"]["valid_response"]["score"] * len(expected), 2))
                checked += 1
                if expected and expected[0] != "0":
                    not_first += 1
        self.assertGreater(checked, 100)
        self.assertGreater(not_first, 30)

    def test_validator_accepts_fixture_and_flags_problems(self):
        fixture_path = Path(__file__).resolve().parent / "fixtures" / "wiseflow-export.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        # The fixture itself breaks the rule on most items: exactMatch without a
        # penalty, and widgets lacking widget_type. Nothing else is flagged.
        problems = latex2quiz.validate_bank(fixture)
        self.assertTrue(problems)
        self.assertTrue(
            all(any(k in p for k in ("scoring_type", "penalty", "widget_type")) for p in problems),
            problems,
        )
        self.assertFalse(any("Mindste udspændende træ" in p and "scoring_type" in p and p.startswith("item 1 ") for p in problems))
        bank = latex2quiz.build_bank([
            latex2quiz.build_mc_item(self.questions[0], "<p>s</p>", ["a", "b", "c"], None, 4.0, False, "d"),
            latex2quiz.build_written_item(self.written_sections[0], "<p>w</p>", None, 4.0, "d"),
        ])
        self.assertEqual([], latex2quiz.validate_bank(bank))
        broken = json.loads(json.dumps(bank))
        data = broken["data"][0]["questions"][0]["data"]
        data["validation"]["minScore"] = 0
        del data["minScore"]
        data["validation"]["allow_negative_scores"] = "true"
        data["validation"]["valid_response"]["value"] = ["2", "1"]
        broken["data"][0]["definition"]["widgets"][0]["reference"] = "other"
        problems = latex2quiz.validate_bank(broken)
        self.assertEqual(5, len(problems), problems)
        differences = latex2quiz.compare_keys(bank, fixture)
        self.assertIn(("data[].questions[].data", "extra", "shuffle_options"), differences)
        self.assertIn(("data[].questions[].data", "missing", "shuffle_scores"), differences)
        self.assertNotIn(("data[]", "missing", "labels"), differences)

    def test_written_parts_share_the_section_total(self):
        section = self.written_sections[0]  # "Proofs (6%)", two parts, no part points
        self.assertEqual([3, 3], latex2quiz.part_points(section, 4.0))
        source = SAMPLE.replace(
            r"\punkt{a)}{Prove the first claim.}",
            r"\punkt{a)}{\qtipoints{1}Prove the first claim.}",
        )
        section = latex2quiz.parse_written_sections(source)[0]
        self.assertEqual([1, 5], latex2quiz.part_points(section, 4.0))
        no_total = latex2quiz.parse_written_sections(
            source.replace(r"\section{Proofs (6\%)}", r"\section{Proofs}")
        )[0]
        self.assertEqual([1, 4], latex2quiz.part_points(no_total, 4.0))
        thirds = latex2quiz.parse_written_sections(
            SAMPLE.replace(r"\section{Proofs (6\%)}", r"\section{Proofs (11\%)}")
            .replace("Prove the second claim.", "Prove the second claim.\n\\punkt{c)}{Third.}")
        )[0]
        self.assertEqual([4, 4, 3], latex2quiz.part_points(thirds, 4.0))
        ten = latex2quiz.parse_written_sections(
            SAMPLE.replace(r"\section{Proofs (6\%)}", r"\section{Proofs (10\%)}")
            .replace("Prove the second claim.", "Prove the second claim.\n\\punkt{c)}{Third.}")
        )[0]
        self.assertEqual([4, 3, 3], latex2quiz.part_points(ten, 4.0))
        fractional = latex2quiz.parse_written_sections(
            SAMPLE.replace(r"\section{Proofs (6\%)}", r"\section{Proofs}\qtipoints{7.5}")
        )[0]
        self.assertEqual([3.75, 3.75], latex2quiz.part_points(fractional, 4.0))
        over = latex2quiz.parse_written_sections(
            source.replace(r"\qtipoints{1}", r"\qtipoints{7}")
        )[0]
        with self.assertRaisesRegex(latex2quiz.ConversionError, "leave nothing"):
            latex2quiz.part_points(over, 4.0)

        item = latex2quiz.build_written_parts_item(
            section, ["<p>a</p>", "<p>b</p>"], ["<p>sol a</p>", None], 4.0, "d"
        )
        self.assertEqual("Proofs (6%)", item["title"])
        self.assertEqual(2, len(item["questions"]))
        self.assertEqual(
            [w["reference"] for w in item["definition"]["widgets"]],
            [q["reference"] for q in item["questions"]],
        )
        self.assertEqual(2, len({q["reference"] for q in item["questions"]}))
        self.assertEqual(
            [{"max_score": 1}, {"max_score": 5}],
            [q["data"]["validation"] for q in item["questions"]],
        )
        self.assertEqual("<p>sol a</p>", item["questions"][0]["data"]["metadata"]["sample_answer"])
        self.assertNotIn("metadata", item["questions"][1]["data"])
        self.assertEqual([1, 5], latex2quiz.item_maximum_scores(item))
        self.assertEqual([], latex2quiz.validate_bank(latex2quiz.build_bank([item])))

        fragments = latex2quiz._html_fragments(
            SAMPLE, self.questions, self.written_sections, True, "da"
        )
        self.assertNotIn("w001-feedback", fragments)
        self.assertEqual("First solution.", fragments["w001-part-001-feedback"])
        self.assertEqual("Second solution.", fragments["w001-part-002-feedback"])

    def test_bank_wrapper_and_html_fragments(self):
        bank = latex2quiz.build_bank([{"reference": "x"}])
        self.assertEqual("item", bank["metadata"]["content"])
        self.assertEqual([{"reference": "x"}], bank["data"])
        fragments = latex2quiz._html_fragments(
            SAMPLE, self.questions, self.written_sections, True, "da", essay_parts=False
        )
        self.assertIn("Vælg ét eller flere korrekte svar.", fragments["q002-stem"])
        self.assertEqual("{$2$}", fragments["q001-answer-002"])
        self.assertIn("Second solution.", fragments["w001-feedback"])
        requests = latex2quiz._figure_requests(fragments)
        self.assertEqual(["w001-part-002-figure-001"], [r.key for r in requests])
        self.assertTrue(requests[0].figure)
        self.assertEqual("\\includegraphics{diagram.pdf}", requests[0].latex)

    def test_cli_rejects_mismatched_output_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "exam.tex"
            source.write_text(SAMPLE, encoding="utf-8")
            with self.assertRaises(SystemExit):
                latex2quiz.main(["--format", "learnosity", "-o", "x.zip", str(source)])
            with self.assertRaises(SystemExit):
                latex2quiz.main(["--json-output", "x.json", str(source)])
            with self.assertRaises(SystemExit):
                latex2quiz.main(["--essay-template", "missing.json", "--format", "learnosity", str(source)])



class PdfDocumentTests(unittest.TestCase):
    def _document(self, with_answers, language="da"):
        questions, _ = latex2quiz.parse_questions(SAMPLE)
        sections = latex2quiz.parse_written_sections(SAMPLE)
        return latex2quiz.pdf_document_source(
            SAMPLE, "my_exam.tex", questions, sections, with_answers, language
        )

    def test_one_page_per_question_and_written_problem(self):
        document = self._document(False)
        # Two MC questions and one written problem: two page breaks.
        self.assertEqual(2, document.count(r"\clearpage"))
        self.assertIn(r"\fancyhead[L]{\texttt{my\_exam.tex}}", document)
        self.assertIn(r"\fancyhead[R]{Side \thepage}", document)
        self.assertIn(r"\section*{Proofs (6\%)}", document)
        self.assertIn(r"\textbf{b)}\quad Prove the second claim.", document)

    def test_answers_only_in_the_version_with_answers(self):
        without = self._document(False)
        with_answers = self._document(True)
        for text in (r"\checkmark", "Because $1+1=2$.", "First solution.", "Med svar"):
            self.assertNotIn(text, without)
            self.assertIn(text, with_answers)
        self.assertEqual(3, with_answers.count(r"\ensuremath{\checkmark}"))

    def test_english_labels(self):
        document = self._document(True, "en")
        self.assertIn(r"\fancyhead[R]{Page \thepage}", document)
        self.assertIn(r"\textbf{Answer:}", document)
        self.assertIn("With answers", document)

    def test_output_paths(self):
        self.assertEqual(
            (Path("a/x-without-answers.pdf"), Path("a/x-with-answers.pdf")),
            latex2quiz.pdf_output_paths(Path("a/x.tex")),
        )
        self.assertEqual(
            (Path("out/x-without-answers.pdf"), Path("out/x-with-answers.pdf")),
            latex2quiz.pdf_output_paths(Path("a/x.tex"), Path("out")),
        )

@unittest.skipUnless(shutil.which("pdflatex") and shutil.which("pdftoppm"), "LaTeX tools unavailable")
class RenderingIntegrationTests(unittest.TestCase):
    def test_pdf_versions_with_and_without_answers(self):
        source = r"""
\multiplechoicestart
\spoergsmaal{Two plus two}
What is $2+2$?
\etsvar
\mulighederstart
\svar 3
\svar 4 \korrekt
\mulighederslut
\forklaring{Count.}
\spoergsmaal{Letters}
Pick a vowel.
\fleresvar
\mulighederstart
\svar A \korrekt
\svar B
\mulighederslut
\multiplechoiceslut
\section{Written proof}
\punkt{a)}{Prove the claim.}
\forklaring{By induction.}
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "exam.tex"
            input_path.write_text(source, encoding="utf-8")
            self.assertEqual(
                0, latex2quiz.main([str(input_path), "--format", "pdf", "-o", str(root / "out")])
            )
            for name in ("exam-without-answers.pdf", "exam-with-answers.pdf"):
                data = (root / "out" / name).read_bytes()
                self.assertTrue(data.startswith(b"%PDF"))
                if shutil.which("pdfinfo"):
                    info = subprocess.run(
                        ["pdfinfo", str(root / "out" / name)],
                        capture_output=True, text=True, check=True,
                    ).stdout
                    self.assertRegex(info, r"Pages:\s+3\n", name)

    def test_convert_minimal_exam(self):
        source = r"""
\multiplechoicestart
\spoergsmaal{Two plus two}
What is $2+2$?
\etsvar
\mulighederstart
\svar 3
\svar 4 \korrekt
\mulighederslut
\multiplechoiceslut
\section{Written proof}
Use the definition above.
\punkt{a)}{Prove the claim.}
Additional information for the second part.
\punkt{b)}{Give a counterexample.}
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "exam.tex"
            output_path = root / "exam-qti.zip"
            input_path.write_text(source, encoding="utf-8")
            (
                mc_count,
                written_section_count,
                written_subquestion_count,
                image_count,
                warnings,
            ) = latex2quiz.convert(
                input_path,
                output_path,
                "Test bank",
                "en",
                1.0,
                72,
                False,
                False,
                "",
            )
            self.assertEqual(
                (1, 1, 2, 5, []),
                (
                    mc_count,
                    written_section_count,
                    written_subquestion_count,
                    image_count,
                    warnings,
                ),
            )
            with zipfile.ZipFile(output_path) as archive:
                self.assertEqual(
                    {
                        "imsmanifest.xml",
                        "items/q001.xml",
                        "items/assets/q001-stem.png",
                        "items/assets/q001-answer-001.png",
                        "items/assets/q001-answer-002.png",
                        "items/w001.xml",
                        "items/assets/w001-part-001.png",
                        "items/assets/w001-part-002.png",
                    },
                    set(archive.namelist()),
                )
                ET.fromstring(archive.read("imsmanifest.xml"))
                ET.fromstring(archive.read("items/q001.xml"))
                ET.fromstring(archive.read("items/w001.xml"))

    def test_convert_learnosity_with_embedded_figure(self):
        source = r"""
\multiplechoicestart
\spoergsmaal{Table}
Consider
\begin{center}\begin{tabular}{|c|c|}\hline 1 & 2\\\hline\end{tabular}\end{center}
What is $1+1$?
\etsvar
\mulighederstart
\svar 1
\svar {\bf 2} \korrekt
\mulighederslut
\forklaring{Because.}
\multiplechoiceslut
\section{Written}
\punkt{a)}{Prove $x<y$.}
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "exam.tex"
            json_path = root / "exam.json"
            zip_path = root / "exam.zip"
            input_path.write_text(source, encoding="utf-8")
            counts = latex2quiz.convert(
                input_path, zip_path, "Bank", "en", 4.0, 72, False, True, "",
                learnosity_path=json_path, html_dpi=144, essay_parts=False,
            )
            # 4 QTI images (stem, 2 answers, feedback) + 1 written part + 1 figure.
            self.assertEqual((1, 1, 1, 6, []), counts)
            with zipfile.ZipFile(zip_path) as archive:
                self.assertNotIn("items/assets/q001-stem-figure-001.png", archive.namelist())
                self.assertIn("items/assets/q001-stem.png", archive.namelist())
            bank = json.loads(json_path.read_text(encoding="utf-8"))
            mc, essay = bank["data"]
            stimulus = mc["questions"][0]["data"]["stimulus"]
            self.assertTrue(stimulus.startswith("<h3>Table (4%)</h3><p>Consider</p><div style=\"text-align:center\"><p><img src=\"data:image/png;base64,"))
            self.assertIn("<p>What is \\(1+1\\)?</p><p>Exactly one answer is correct", stimulus)
            self.assertEqual(
                ["1", "<b>2</b>"],
                [option["label"] for option in mc["questions"][0]["data"]["options"]],
            )
            self.assertEqual("<p>Because.</p>", mc["questions"][0]["data"]["metadata"]["distractor_rationale"])
            # The figure is rendered at 144 dpi but declared at its 96 dpi size.
            width, height = map(int, re.search(r'width="(\d+)" height="(\d+)"', stimulus).groups())
            png = base64.b64decode(re.search(r'base64,([^"]+)"', stimulus).group(1))
            pixel_width, pixel_height = struct.unpack(">II", png[16:24])
            self.assertEqual((width, height), (round(pixel_width * 96 / 144), round(pixel_height * 96 / 144)))
            self.assertGreater(pixel_width, width)
            self.assertEqual(
                "<h3>Written</h3><p><b>a)</b>&nbsp;&nbsp;Prove \\(x&lt;y\\).</p>",
                essay["questions"][0]["data"]["stimulus"],
            )
            self.assertEqual({"max_score": 4}, essay["questions"][0]["data"]["validation"])

            counts = latex2quiz.convert(
                input_path, None, "Bank", "en", 4.0, 72, False, True, "",
                learnosity_path=json_path,
            )
            self.assertEqual(1, counts[3])


class FacadeSyncTests(unittest.TestCase):
    """Guards against latex2quiz.py drifting out of sync with latex2quiz_lib.

    latex2quiz.py hand-re-exports every top-level name from each
    latex2quiz_lib submodule so old imports and this test suite keep
    working. Nothing enforces that list stays complete, so a new
    function/class/constant added to a submodule could silently fail
    to reach the facade. This test parses each submodule's source to
    find what it defines and checks that latex2quiz re-exports the
    exact same object under the same name.
    """

    def _top_level_names(self, source, filename):
        tree = ast.parse(source, filename=filename)
        names = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.append(node.name)
            elif isinstance(node, ast.Assign):
                names.extend(t.id for t in node.targets if isinstance(t, ast.Name))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.append(node.target.id)
        return [n for n in names if not (n.startswith("__") and n.endswith("__"))]

    def test_facade_reexports_every_submodule_definition(self):
        lib_dir = Path(latex2quiz_lib.__file__).parent
        missing = []
        mismatched = []
        for path in sorted(lib_dir.glob("*.py")):
            if path.stem == "__init__":
                continue
            submodule = importlib.import_module(f"latex2quiz_lib.{path.stem}")
            for name in self._top_level_names(path.read_text(), str(path)):
                if not hasattr(latex2quiz, name):
                    missing.append(f"{path.stem}.{name}")
                elif getattr(latex2quiz, name) is not getattr(submodule, name):
                    mismatched.append(f"{path.stem}.{name}")

        self.assertEqual(
            [], missing,
            "Defined in latex2quiz_lib but not re-exported from latex2quiz.py "
            "-- add it to the matching import block (or, if it's meant to "
            "stay internal, exclude it explicitly and note why).",
        )
        self.assertEqual(
            [], mismatched,
            "latex2quiz re-exports these names but they resolve to a "
            "different object than the submodule defines -- likely "
            "imported from the wrong module.",
        )



def _png(width, height):
    """A valid white greyscale PNG of the given size."""
    import zlib

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    rows = b"".join(b"\x00" + b"\xff" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


class BrowserBridgeTests(unittest.TestCase):
    """The Pyodide bridge in web/ runs the command line with page-supplied images."""

    ROOT = Path(__file__).resolve().parents[1]

    def setUp(self):
        import sys

        from latex2quiz_lib import package

        sys.path.insert(0, str(self.ROOT / "web"))
        self.addCleanup(sys.path.remove, str(self.ROOT / "web"))
        original = package.render_latex
        import latex2quiz_web

        self.addCleanup(setattr, package, "render_latex", original)
        package.render_latex = latex2quiz_web.browser_render_latex
        self.web = latex2quiz_web
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

    def test_conversion_asks_for_rendering_then_uses_the_pages(self):
        source = Path(self.temporary.name) / "exam.tex"
        source.write_text(SAMPLE, encoding="utf-8")
        args = [str(source), "--format", "both"]
        first = self.web.run(args)
        self.assertEqual("render", first["status"])
        self.assertIn(r"\begin{document}", first["document"])
        self.assertEqual([192, 384], first["resolutions"])
        for resolution in first["resolutions"]:
            pages = [_png(resolution, resolution // 2)] * first["pages"]
            self.web.provide_pages(first["key"], resolution, pages)
        second = self.web.run(args)
        self.assertEqual("done", second["status"])
        self.assertEqual(0, second["code"], second["stderr"])
        self.assertIn("Wrote QTI 2.1 package", second["stdout"])
        self.assertTrue(zipfile.is_zipfile(source.with_name("exam-qti.zip")))
        bank = json.loads(source.with_name("exam-learnosity.json").read_text(encoding="utf-8"))
        self.assertTrue(bank["data"])

    def test_check_and_usage_errors_finish_without_rendering(self):
        source = Path(self.temporary.name) / "exam.tex"
        source.write_text(SAMPLE, encoding="utf-8")
        checked = self.web.run([str(source), "--check"])
        self.assertEqual(("done", 0), (checked["status"], checked["code"]))
        self.assertIn("OK:", checked["stdout"])
        missing = self.web.run([str(source.with_name("missing.tex"))])
        self.assertEqual(("done", 2), (missing["status"], missing["code"]))

    def test_web_page_loads_every_module(self):
        script = (self.ROOT / "web" / "app.js").read_text(encoding="utf-8")
        listed = re.search(r"const PYTHON_MODULES = \[(.*?)\];", script, re.S).group(1)
        self.assertEqual(
            sorted(re.findall(r"'([\w]+)'", listed)),
            sorted(path.stem for path in (self.ROOT / "latex2quiz_lib").glob("*.py")),
        )

if __name__ == "__main__":
    unittest.main()
