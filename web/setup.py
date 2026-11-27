#!/usr/bin/env python3
"""Fetch the TeX engine for the browser version into web/vendor/.

Downloads a WebAssembly build of TeX Live 2023 (BusyTeX) with its package
bundles (about 210 MB), and packs the files the exams need, listed in
web/texlive-files.txt, into a small bundle (about 9 MB) that the page loads
instead.  The page falls back to the full bundles when an exam needs a file
outside the small one, if they are on the server.  The LaTeX packages the
bundles lack (PGF/TikZ, preview, a few fonts) are collected from the local
TeX installation into web/vendor/texmf-extra.json.
Run it once before serving the page; it skips downloads already there.
"""
from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from texbundle import Package, write_package  # noqa: E402

BUSYTEX_RELEASE = (
    "https://github.com/busytex/busytex/releases/download/"
    "build_wasm_4499aa69fd3cf77ad86a47287d9a5193cf5ad993_7936974349_1/"
)
BUSYTEX_FILES = [
    "busytex.js",
    "busytex.wasm",
    "busytex_pipeline.js",
    "busytex_worker.js",
    "texlive-basic.js",
    "texlive-basic.data",
    "ubuntu-texlive-latex-base.js",
    "ubuntu-texlive-latex-base.data",
    "ubuntu-texlive-latex-recommended.js",
    "ubuntu-texlive-latex-recommended.data",
    "ubuntu-texlive-latex-extra.js",
    "ubuntu-texlive-latex-extra.data",
    "ubuntu-texlive-science.js",
    "ubuntu-texlive-science.data",
]
# Packages missing from the BusyTeX bundles: (a file that kpsewhich can find,
# how many directory levels up the package tree starts).
EXTRA_PACKAGES = [
    ("pgfcore.code.tex", 2),  # tex/generic/pgf
    ("tikz.sty", 2),  # tex/latex/pgf
    ("preview.sty", 1),  # tex/latex/preview
]
EXTRA_SUFFIXES = {".tex", ".sty", ".def", ".cfg", ".clo", ".fd"}
# Type 1 fonts for the TS1 (text companion) encoding, which the BusyTeX
# bundles lack. The exams only use SFRM1200 (12pt roman); a few neighbouring
# sizes and styles are included for safety. The page loads FONT_MAP with
# \pdfmapfile before compiling.
TS1_FONTS = ["sfrm1000", "sfrm1095", "sfrm1200", "sfrm1440", "sfbx1200", "sfti1200", "sftt1200", "sfsl1200"]
FONT_MAP = "cm-super-ts1-web.map"

VENDOR = Path(__file__).resolve().parent / "vendor"
SMALL_BUNDLE = "latex2quiz-texlive.js"


def download_busytex() -> None:
    target = VENDOR / "busytex"
    target.mkdir(parents=True, exist_ok=True)
    for name in BUSYTEX_FILES:
        destination = target / name
        if destination.exists() and destination.stat().st_size > 0:
            continue
        print(f"Downloading {name} ...", flush=True)
        partial = destination.with_suffix(destination.suffix + ".part")
        with urllib.request.urlopen(BUSYTEX_RELEASE + name) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out)
        partial.rename(destination)


def collect_extra_packages() -> None:
    kpsewhich = shutil.which("kpsewhich")
    if not kpsewhich:
        sys.exit("kpsewhich not found: install TeX Live 2023 to supply PGF/TikZ, preview and the cm-super fonts")
    VENDOR.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    for probe, levels in EXTRA_PACKAGES:
        found = subprocess.run([kpsewhich, probe], capture_output=True, text=True).stdout.strip()
        if not found:
            sys.exit(f"kpsewhich cannot find {probe}")
        root = Path(found).parents[levels - 1]
        for path in sorted(root.rglob("*")):
            if path.suffix not in EXTRA_SUFFIXES or not path.is_file():
                continue
            # TeX finds these by name in the working directory, so the tree
            # is flattened; the names are unique within these packages.
            if path.name in files:
                sys.exit(f"duplicate file name {path.name} in {root}")
            files[path.name] = base64.b64encode(path.read_bytes()).decode("ascii")
    shipped = set()
    for font in TS1_FONTS:
        found = subprocess.run([kpsewhich, font + ".pfb"], capture_output=True, text=True).stdout.strip()
        if not found:
            sys.exit(f"kpsewhich cannot find {font}.pfb (install cm-super)")
        files[font + ".pfb"] = base64.b64encode(Path(found).read_bytes()).decode("ascii")
        shipped.add(font + ".pfb")
    encoding = subprocess.run([kpsewhich, "cm-super-ts1.enc"], capture_output=True, text=True).stdout.strip()
    font_map = subprocess.run([kpsewhich, "cm-super-ts1.map"], capture_output=True, text=True).stdout.strip()
    if not encoding or not font_map:
        sys.exit("kpsewhich cannot find the cm-super TS1 encoding or map")
    files["cm-super-ts1.enc"] = base64.b64encode(Path(encoding).read_bytes()).decode("ascii")
    lines = [
        line for line in Path(font_map).read_text(encoding="ascii").splitlines()
        if any(("<" + name) in line for name in shipped)
    ]
    files[FONT_MAP] = base64.b64encode(("\n".join(lines) + "\n").encode("ascii")).decode("ascii")
    destination = VENDOR / "texmf-extra.json"
    destination.write_text(
        json.dumps({"encoding": "base64", "font_map": FONT_MAP, "files": files}), encoding="utf-8"
    )
    print(f"Wrote {destination} with {len(files)} files")


def build_small_bundle() -> None:
    """Pack the files in texlive-files.txt from the full bundles."""
    wanted = [
        line.strip()
        for line in (Path(__file__).resolve().parent / "texlive-files.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    sources = [Package(VENDOR / "busytex" / name) for name in BUSYTEX_FILES if name.endswith(".js") and not name.startswith("busytex")]
    files = []
    provides = set()
    for filename in wanted:
        source = next((package for package in sources if filename in package.files), None)
        if source is None:
            sys.exit(f"{filename} is not in the BusyTeX bundles; run web/update_tex_files.py")
        contents = source.read(filename)
        files.append((filename, contents))
        if filename.endswith((".sty", ".cls")):
            provides.update(
                "\\ProvidesPackage{" + name.decode("latin-1") + "}"
                for name in re.findall(rb"\\Provides(?:Package|Class)\s*\{([^}]+)\}", contents)
            )
    size = write_package(VENDOR / "busytex" / SMALL_BUNDLE, files, provides)
    print(f"Wrote {SMALL_BUNDLE} with {len(files)} files ({size / 1e6:.1f} MB)")


if __name__ == "__main__":
    collect_extra_packages()
    download_busytex()
    build_small_bundle()
    print("Done. Serve the repository root, e.g. `python3 -m http.server 8000`,")
    print("and open http://localhost:8000/web/")
