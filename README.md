# LaTeX to Canvas QTI and WISEflow JSON

`latex2quiz.py` converts the multiple-choice and written parts of the existing
exam LaTeX format into a QTI 2.1 item-bank package for Canvas, or into
WISEflow's native item format (Learnosity item JSON). It can also print a
problem set as PDFs with one question per page, with and without answers.
The source format
in `ad-exams/danish/` and `dma-exams/danish/` works without a migration. Any
external file referenced with commands such as `\includegraphics` must also be
present.

The exporter renders question text, answer options, and explanations with
LaTeX and stores them as high-resolution PNG resources. This deliberately
favours faithful, portable output over editable HTML: TikZ figures,
`clrscode3e` pseudo-code, tables, and mathematics look the same as in the
printed exam. The multiple-choice selection instruction is included in the
stem image as well, so it uses the same LaTeX font. Every image also has a
Unicode text alternative in the QTI XML. Common mathematical commands become
symbols such as `Θ`, `≤`, `∈`, `∑`, and `√`; structural constructs such as
fractions, binomial coefficients, roots, superscripts, and subscripts are
converted to readable linear text.

## Requirements

- Python 3.9 or newer (no Python packages are required)
- `pdflatex`, including the LaTeX packages used by the exam
- Poppler's `pdftoppm`

On macOS, MacTeX supplies `pdflatex`, and `brew install poppler` supplies
`pdftoppm`.

## Use

Generate a QTI 2.1 package for Canvas with:

```sh
python3 latex2quiz.py ad-exams/danish/ad-problems-2025-june.tex
```

This writes `ad-exams/danish/ad-problems-2025-june-qti.zip`. Choose QTI 2.1 when the
importer asks for a version.

Useful options include:

```sh
# Parse and validate only; this does not require LaTeX.
python3 latex2quiz.py --check ad-exams/danish/ad-problems-2025-june.tex

# Change the default score and shuffle MC choices.
python3 latex2quiz.py --points 4 --shuffle -o exam-qti.zip exam.tex

# Suggest taller written-response fields.
python3 latex2quiz.py --written-lines 20 exam.tex

# Add course-specific packages or macros when converting a fragment that has
# no document preamble of its own.
python3 latex2quiz.py --preamble my-exam-preamble.tex questions.tex
```

Run `python3 latex2quiz.py --help` for all options.

### PDFs with one question per page

```sh
# Write ad-problems-2025-june-without-answers.pdf and
# ad-problems-2025-june-with-answers.pdf next to the problem set.
python3 latex2quiz.py --format pdf ad-exams/danish/ad-problems-2025-june.tex

# English labels, and the PDFs in another folder.
python3 latex2quiz.py --format pdf --language en -o pdfs ad-exams/english/ad-problems-2025-june.tex
```

Every multiple-choice question and every written problem starts on a new page;
a long problem continues onto the next. The header shows the problem file's
name and the page number. The version with answers also says "Med svar"
("With answers") in the header, ticks the correct choices, and prints the
explanations (leave them out with `--no-feedback`). The PDFs contain only the
problems; use the folder's `template.tex` for an exam with a front page.
`--language` sets the language of the header and labels (default `da`).

### WISEflow JSON (Learnosity items)

For WISEflow, use its native format, a JSON file of Learnosity items. It is
imported into the content bank with partial-credit scoring, essay points, and
item titles intact:

```sh
# Write ad-exams/danish/ad-problems-2025-june-learnosity.json instead of a QTI package.
python3 latex2quiz.py --format learnosity ad-exams/danish/ad-problems-2025-june.tex

# Write both formats; -o names the ZIP and --json-output the JSON.
python3 latex2quiz.py --format both --json-output bank.json ad-exams/danish/ad-problems-2025-june.tex

# Use WISEflow's own essay question type, copied from an export of any item
# bank made in the target WISEflow environment.
python3 latex2quiz.py --format learnosity --essay-template WISEflow-export.json exam.tex
```

Unlike the QTI package, the JSON contains editable HTML. Running text becomes
paragraphs, lists, and inline formatting; mathematics is kept as LaTeX inside
`\( ... \)` and `\[ ... \]` delimiters and rendered by MathJax in WISEflow
(`is_math` is enabled). Constructs without an HTML equivalent are rendered
with LaTeX at their natural width and embedded as `data:` PNG images:
`tikzpicture`, `codebox` pseudo-code, `tabular`, `\includegraphics`, and any
unknown environment. They are rendered at `--html-dpi` (default 384, four
times the pixel density of the displayed size; the QTI package uses `--dpi`). Macros defined in the document with `\newcommand` are
expanded first, `\proc`, `\id`, and `\const` are rewritten to MathJax
equivalents, and `\ref` is replaced by the section number LaTeX would print.
Unrecognized text-mode commands are dropped (their braced argument is kept as
text) and reported as a warning. No LaTeX installation is needed when the
exam contains none of the rendered constructs.

Scoring follows an item export from WISEflow. Each MC question is a
multiple-response `mcq` with `partialMatch` scoring ("partial match per
response"): every selected correct choice earns the question value divided by
the number of correct choices, every selected incorrect choice costs the value
divided by the number of incorrect choices, and `minScore` clamps the question
at zero. Written sections become essay questions with `max_score` set to the
section total. By default they use Learnosity's built-in `longtextV2` type;
`--essay-template` copies WISEflow's custom essay question definition (with
spell checking and its environment-specific script locations) from an export
instead. If the essay type does not render MathJax, `--essay-images`
renders each written question as one image, as in the QTI package, while
keeping the explanation as HTML. Each `\punkt` becomes its own essay
question inside the section's item, answered and graded separately: a part
keeps its `\qtipoints` value, and the rest of the section total is shared by
the other parts in whole points, earlier parts rounded up and later parts
down (11 points over three parts gives 4, 4, 3), so the parts always add up
to the section total. Without a section total, parts without a value get
`--points` each. The shared context still appears once, before part a).
`--essay-single` gives each section one essay question and one response
field instead, as in the QTI package. `\forklaring` text is stored as `distractor_rationale` (MC) or
`sample_answer` (essay) metadata. Scores are rounded once, to three decimals
as WISEflow stores them. Item and question references are fresh UUID4
values on every run, as in WISEflow's own exports; apart from them and the
`date_created` stamp, the output is deterministic.

Before uploading, check a produced file mechanically:

```sh
python3 validate_learnosity.py bank.json --fixture tests/fixtures/wiseflow-export.json
```

The validator checks the item structure, reference consistency, scoring
fields and types, and the option/answer mapping, and exits non-zero on any
problem. With `--fixture` it also lists key differences against a WISEflow
export at every nesting level, which is informational.

## Browser version (prototype)

The repository includes the files the browser version needs, so it runs from
GitHub Pages (Settings → Pages → deploy from the `main` branch, root folder)
at `https://<user>.github.io/latex2quiz/`. Running `web/setup.py` is needed
only to rebuild them, or to add the full TeX Live bundles for the fallback
described below. These files come from BusyTeX and TeX Live and keep their
own licenses (LPPL, GPL, OFL and others); see
[web/THIRD-PARTY-LICENSES.md](web/THIRD-PARTY-LICENSES.md).

`web/` runs the converter entirely in the browser. The Python code runs
unchanged in [Pyodide](https://pyodide.org); LaTeX is compiled by
[BusyTeX](https://github.com/busytex/busytex) (TeX Live 2023 compiled to
WebAssembly) in a worker, and [pdf.js](https://mozilla.github.io/pdf.js/)
turns the PDF pages into PNG images. Exam files never leave the computer.

One-time setup, on a machine with TeX Live 2023 (the version BusyTeX is
built from):

```sh
python3 web/setup.py
```

This downloads BusyTeX and its TeX Live package bundles (about 210 MB) into
`web/vendor/busytex/`, and packs the files the exams actually use, listed in
`web/texlive-files.txt`, into a small bundle of about 9 MB
(`latex2quiz-texlive.js` and `.data`). It also copies the packages the
bundles lack (PGF/TikZ, preview, and a few cm-super fonts) from the local TeX
installation into `web/vendor/texmf-extra.json`. Then serve the repository
root and open the page:

```sh
python3 -m http.server 8000
# open http://localhost:8000/web/
```

Select the problem set together with the files it uses (figure PDFs,
`skriftlige.tex`). The page finds the problem set among them (the `.tex` file
with `\multiplechoicestart`; a chooser appears only if several files have
one), takes the language of the instructions from the macro names (English
names give English), and shows the problems right
away, one sheet per problem, typeset by LaTeX: the question, its choices and
the explanation. **Show answers** switches the marks on the correct choices
and the explanations on and off without compiling again. A whole exam takes
about 5 seconds once TeX is loaded. The status panel is visible only while
the page works or when something fails.

**Export to QTI** and **Export to WISEflow** download the converted files.
They match the command line: the QTI XML and the image sizes are identical,
and the images differ only in anti-aliasing. The QTI export reuses the images
already shown, so it takes well under a second; the WISEflow export renders
its figures at a higher resolution and takes a second or two.

The page loads only the small bundle, so the first conversion downloads about
45 MB (mostly the 30 MB TeX engine); the browser caches it. If a document
needs a TeX file outside the small bundle, or LaTeX has to substitute a
missing font, the page loads the full bundles and compiles again, provided
they are on the server. When an exam starts using a new LaTeX package or
font, run `python3 web/update_tex_files.py` (it compiles every problem set
with the local TeX and records the files read) and then `web/setup.py` again,
so the small bundle keeps covering all exams.

To host the page, serve these files from the repository: `web/index.html`,
`web/app.js`, `web/latex2quiz_web.py`, `latex2quiz_lib/*.py`,
`web/vendor/texmf-extra.json`, and from `web/vendor/busytex/` the files
`busytex.js`, `busytex.wasm`, `busytex_pipeline.js`, `busytex_worker.js` and
`latex2quiz-texlive.js`/`.data`. Add the other `.js`/`.data` pairs there to
enable the fallback; the largest file is then 105 MB instead of 30 MB.

Limitations: Pyodide and pdf.js load from public CDNs, so the page needs
internet access; only Chrome has been tested; `--preamble` and
`--essay-template` are not available in the page; a document that needs a
LaTeX package or font missing even from the full bundles fails with the TeX
log.

## Exam files and PDF templates

Each course has a folder, `ad-exams/` (Algorithms and Data Structures) and
`dma-exams/` (Discrete Mathematics and Algorithms), with the Danish originals
in `danish/` and machine translations in `english/`. A problem set is named
`<course>-problems-<year>-<month>.tex` (trial exams `<course>-problems-<year>-trial.tex`)
and has the same name in both languages. Problem files contain only the
problems, without a preamble or front page; every file whose name starts with
`ad-` or `dma-` is a problem set, and the tests read all of them. Other `.tex`
files are included by the problem sets or the templates: `skriftlige.tex`
(English `written.tex`) holds the instructions for the written AD problems.

To make the PDF of an exam, copy the folder's `template.tex`, and set the exam
date, duration and problem file at the top. Uncomment `\answerstrue` for the
version with answers and explanations. The template supplies the preamble,
all exam macros, and the front page; it counts the problems automatically.
Compile it in the same folder:

```sh
cd dma-exams/danish
cp template.tex reexam-april-2026.tex   # then edit the settings
pdflatex reexam-april-2026.tex && pdflatex reexam-april-2026.tex
```

The English templates and translations leave out information that is local
to one edition of the course, such as the institution, course code, exam
system and permitted aids. Each such place holds a `\placeholder{...}` that
describes what to fill in; it prints as *[description]*.

## Code structure

`latex2quiz.py` is intentionally a small compatibility launcher. The
implementation is divided by responsibility under `latex2quiz_lib/`:

- `source.py` parses multiple-choice and written LaTeX questions.
- `alttext.py` converts rendered LaTeX fragments to Unicode alternatives.
- `render.py` creates the PNG resources.
- `qti.py` builds QTI 2.1 item and manifest XML.
- `htmltext.py` converts LaTeX fragments to HTML with MathJax delimiters.
- `learnosity.py` builds WISEflow's Learnosity item JSON.
- `package.py` renders, validates, and writes the ZIP package and JSON file.
- `pdf.py` writes the PDFs with one question per page.
- `cli.py` implements command-line validation and reporting.
- `model.py` contains the shared immutable data structures and errors.

The compatibility launcher re-exports the previous Python API, so existing
imports and command lines continue to work. Run the test suite with
`python3 -m unittest discover -s tests -v`.

## Authoring format

Existing exams can remain unchanged. A minimal new file can also be a LaTeX
fragment:

```tex
% This makes the QTI-only annotation invisible in the printed exam.
\providecommand{\qtipoints}[1]{}

\multiplechoicestart

\spoergsmaal{Asymptotic growth}
Which function grows fastest as $n \to \infty$?
\etsvar
\qtipoints{2}
\mulighederstart
\svar $n^2$
\svar $2^n$ \korrekt
\svar $n \log n$
\mulighederslut
\forklaring{Exponential growth eventually dominates every polynomial.}

\multiplechoiceslut

\section*{Written questions}
\section{Proofs}\qtipoints{10}
Let $G=(V,E)$ be a connected graph. The following diagram and definitions are
shared by all parts of this problem.

\punkt{a)}{Prove that $G$ has a spanning tree.}
\forklaring{One possible proof starts with a depth-first traversal.}

Now assume that all edge weights are distinct.
\punkt{b)}
{Prove that the minimum spanning tree is unique.}
```

- `\etsvar` must have exactly one `\korrekt` answer, but it is exported as a
  multiple-response interaction so candidates may select several choices.
- `\fleresvar` may have several correct answers and is also exported as a
  multiple-response interaction.
- For both markers, correct selections split the available points equally and
  incorrect selections split the same total negative weight. Thus the correct
  choices sum to the question value, the incorrect choices sum to its negative,
  and selecting every choice sums to exactly zero in QTI-compliant scoring.
- The default is 4 points per MC question. Put `\qtipoints{number}` in an MC
  stem to override that question's value. As in the printed exam, the value
  is appended to the MC title as `(4%)`, and the title heads the question
  text as well as naming the item, in both output formats. For a written problem, put the macro
  immediately after `\section{...}` to set the section total. Existing trailing
  title markers such as `(9\%)` are recognized as the total automatically. If
  neither is present, the written total is the sum of 4 points per `\punkt`;
  individual `\punkt` prompts may override their contribution with
  `\qtipoints{number}`. Defining the command as shown above keeps it invisible
  when compiling the printed exam. The command is optional, so archived exams
  need no conversion.
- If an old question has neither type marker, the converter infers its type
  from the number of correct answers and prints a warning.
- `\itxsvar{...}` is accepted for backward compatibility and ignored; the
  actual LaTeX answer is rendered.
- `\forklaring{...}` is optional and becomes general feedback. Use
  `--no-feedback` to leave all explanations out of a student-facing package.

### English macro names

The English exams in `ad-exams/english/` and `dma-exams/english/` use English
names for the same macros. The converter accepts either spelling, and a file
may even mix them:

| Danish | English |
|---|---|
| `\spoergsmaal` | `\question` |
| `\etsvar` / `\fleresvar` | `\oneanswer` / `\multipleanswers` |
| `\mulighederstart` / `\mulighederslut` | `\optionsstart` / `\optionsend` |
| `\svar` / `\korrekt` | `\answer` / `\correct` |
| `\forklaring` | `\explanation` |
| `\multiplechoiceslut` | `\multiplechoiceend` (`\multiplechoicestart` is unchanged) |
| `\punkt` | `\subquestion` |
| `\itxsvar` | `\itxanswer` |
| `\sideskift` | `\pageshift` |
| `\mcprocent` | `\mcpercent` |
| `\svarside` / `\medsvar` | `\answerpage` / `\withanswers` |
| `\nylinie` | `\newline` (standard LaTeX) |

`\qtipoints` is the same in both languages. The English `template.tex` files
(see [Exam files and PDF templates](#exam-files-and-pdf-templates)) define the
English macros.

Every ordinary `\section{...}` after `\multiplechoiceslut` becomes one written
section and one QTI 2.1 essay item with a single response field. All `\punkt`
prompts in the section are rendered in source order before that field, so the
shared context appears once and the section cannot be shuffled internally.
Text or figures inserted between two `\punkt` commands remain attached to the
following prompt. `--shuffle` affects MC choices only.

Putting the second `\punkt` argument on the next line, as many archived exams
do, is equivalent. A genuinely unbraced prompt extending to the next
`\forklaring` or `\punkt` is accepted as well.

The section title and initial shared text, tables, code, and figures appear
once before the first subquestion. Material inserted between parts (a) and (b)
appears once before part (b). Context, earlier prompts, and solutions are not
repeated across subquestions.

Written responses are scored manually. `--written-lines` controls the
suggested initial height of the response field; an importer may choose its own
height. A section-level `\qtipoints` value or legacy percentage title sets the
item's total. Without a section total, explicit `\punkt` values and the default
from `--points` are summed to obtain the item total.

Canvas presents essay answers in its Rich Content Editor. Candidates can
insert media or documents unless the quiz's **Disable Document Uploads**
setting is enabled. WISEflow essay questions support inserted images. Its
Appendix Manager can additionally provide drawing, webcam-photo, and file
upload tools for open-ended questions, but a manager must enable those tools
on the flow; that flow-level policy cannot be set in the exported items.
See Canvas's guide to [answering New Quizzes question
types](https://community.instructure.com/en/kb/articles/661355-how-do-i-answer-each-type-of-question-in-new-quizzes)
and WISEflow's [Appendix Manager
guide](https://help.wiseflow.net/service-centre/using-the-appendix-manager).

## Import caveats

The Learnosity JSON mirrors the structure of a WISEflow item export, but the
import has not been verified against every WISEflow release. After importing,
preview an MC item and an essay item and check the points, as WISEflow itself
recommends for imported items. If WISEflow
rejects `longtextV2` essays, export any item bank containing a WISEflow essay
question and pass it with `--essay-template`.

The QTI package uses standard QTI response mappings, but after importing it
into Canvas you should preview every item and verify partial/negative scoring
before using it in an exam. How general feedback (`\forklaring`) is shown also
depends on the importer.

Canvas New Quizzes does not preserve configurable per-choice weights for a
multiple-answer item. Its `PartialScore` algorithm awards and deducts the
question value divided by the number of correct choices for every selected
correct and incorrect choice. Consequently, selecting every choice can still
earn points in Canvas when a question has more correct than incorrect choices,
even though the QTI mapping sums to zero. Canvas offers `Exact Match` as the
only built-in grading alternative, but that removes all partial credit.

The package is intentionally a QTI 2.1 item bank. Exam settings such as time
limits, appendix tools, release rules, item order, and total grading policy
remain platform settings and are not inferred from the LaTeX document.

## License

The software is licensed under the MIT License, copyright Rasmus Pagh; see
[LICENSE](LICENSE). The exam problems are licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/): those in `ad-exams/`
are copyright Mikkel Abrahamsen, Rasmus Pagh and Amir Yehudayoff, and those in
`dma-exams/` are copyright Mikkel Abrahamsen and Rasmus Pagh. See the LICENSE
file in each folder.

The browser version includes third-party software (BusyTeX and TeX Live
files) under its own licenses, listed in
[web/THIRD-PARTY-LICENSES.md](web/THIRD-PARTY-LICENSES.md).
