# Third-party software in the browser version

The latex2quiz code is licensed under the MIT License (see `LICENSE` in the
repository root). The browser version also loads the files below from
`web/vendor/`, which are made by `web/setup.py` from other projects. They
keep their own licenses, which all allow redistribution. The licenses of
the TeX Live packages are taken from TeX Live 2023's package database
(`tlpkg/texlive.tlpdb`).

## TeX engine: `web/vendor/busytex/busytex.*`

From [BusyTeX](https://github.com/busytex/busytex), TeX Live 2023 compiled
to WebAssembly (release
`build_wasm_4499aa69fd3cf77ad86a47287d9a5193cf5ad993_7936974349_1`).

| File | License |
|---|---|
| `busytex_pipeline.js`, `busytex_worker.js` | MIT (BusyTeX's scripts) |
| `busytex.js`, `busytex.wasm` | The licenses of the TeX Live programs compiled into them, in particular pdfTeX (GPL 2.0 or later) and kpathsea (LGPL 2.1). BusyTeX's README: "MIT - applies only to the code and scripts in the repo, not to the published binaries. The binaries include linked TexLive code, so the respective TexLive/dependencies licenses apply." |

`busytex.js` also contains Emscripten's runtime (MIT or University of
Illinois/NCSA) and an LZ4 decoder by Pierre Curto (MIT).

The source code of the binaries is BusyTeX's repository at the commit named
in the release above, together with the TeX Live 2023 sources
(<https://tug.org/texlive/svn/>). See also TeX Live's licensing statement,
<https://tug.org/texlive/LICENSE.TL>.

## TeX Live files: `web/vendor/busytex/latex2quiz-texlive.*`

The 173 files listed in `web/texlive-files.txt`, taken unchanged from
BusyTeX's TeX Live 2023 bundles, plus the generated files kpathsea and pdfTeX
need (`ls-R` file databases, `pdflatex.fmt`, `pdftex.map`, `fonts.conf`).

| License | TeX Live packages |
|---|---|
| LaTeX Project Public License (LPPL) 1.3c | latex, amsmath, graphics, graphics-def, latex-tools-dev, iftex, kvdefinekeys, l3backend, pdftexcmds, xcolor |
| LPPL 1.3 | adjustbox, collectbox, epstopdf-pkg, grfext, ifoddpage, infwarerr, kvoptions, kvsetkeys, ltxcmds, luatex85, xkeyval |
| LPPL (version not stated) | clrscode3e, varwidth |
| LPPL 1.2 | fancybox |
| MIT | enumitem |
| SIL Open Font License | amsfonts (including the Type 1 Computer Modern fonts) |
| Knuth's license | cm (Computer Modern font metrics) |
| GNU LGPL 2.1 | kpathsea (`texmf.cnf`) |
| Public domain | graphics-cfg |
| Free (other) | ec (`tcrm1200.tfm`) |
| TeX Live configuration files | latexconfig (`epstopdf-sys.cfg`), mptopdf (`supp-pdf.mkii`) |

`pdflatex.fmt` is LaTeX's format, built from the LaTeX kernel (LPPL 1.3c).

## Packages added from TeX Live: `web/vendor/texmf-extra.json`

Packages that BusyTeX's bundles lack, copied unchanged from TeX Live 2023.

| Package | License |
|---|---|
| pgf (PGF/TikZ) | LPPL 1.3c, GPL 2, or GNU FDL (for the manual), at the user's choice |
| preview | GPL 3 |
| cm-super (the TS1 fonts `sf*.pfb` and `cm-super-ts1.enc`) | GPL |

`cm-super-ts1-web.map` is a font map written by `web/setup.py` (MIT, as part
of latex2quiz).

## Libraries loaded from CDNs

The page also loads, but does not include, [Pyodide](https://pyodide.org)
0.27.2 (Mozilla Public License 2.0) and
[pdf.js](https://mozilla.github.io/pdf.js/) 3.11.174 (Apache License 2.0).
