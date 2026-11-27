"""Read and write BusyTeX data packages (Emscripten file packages).

A package is a pair ``name.js`` / ``name.data``.  The ``.js`` file holds the
file list (paths and byte ranges) and, for BusyTeX's own packages, the chunk
table of the LZ4-compressed ``.data``.  ``write_package`` produces a package
with uncompressed data, which BusyTeX's LZ4 loader compresses when it loads it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Iterable, Tuple

CHUNK_SIZE = 2048  # Emscripten's MiniLZ4 chunk size


def _lz4_block_decompress(source: bytes, size: int) -> bytes:
    """Decompress one raw LZ4 block whose decompressed size is ``size``."""
    out = bytearray()
    i = 0
    while i < len(source):
        token = source[i]
        i += 1
        literals = token >> 4
        if literals == 15:
            while True:
                extra = source[i]
                i += 1
                literals += extra
                if extra != 255:
                    break
        out += source[i:i + literals]
        i += literals
        if i >= len(source):
            break
        offset = source[i] | (source[i + 1] << 8)
        i += 2
        length = token & 15
        if length == 15:
            while True:
                extra = source[i]
                i += 1
                length += extra
                if extra != 255:
                    break
        length += 4
        start = len(out) - offset
        for k in range(length):  # the match may overlap its own output
            out.append(out[start + k])
    if len(out) != size:
        raise ValueError(f"LZ4 block decompressed to {len(out)} bytes, expected {size}")
    return bytes(out)


class Package:
    """One BusyTeX data package, with random access to its files."""

    def __init__(self, js_path: Path):
        self.js_path = js_path
        text = js_path.read_text(encoding="latin-1")  # comment lines are not all UTF-8
        start = text.rindex("loadPackage(") + len("loadPackage(")
        self.metadata = json.JSONDecoder().raw_decode(text[start:])[0]
        self.files: Dict[str, Tuple[int, int]] = {
            entry["filename"]: (entry["start"], entry["end"]) for entry in self.metadata["files"]
        }
        marker = text.find("var compressedData = ")
        self.chunks = (
            json.JSONDecoder().raw_decode(text[marker + len("var compressedData = "):])[0]
            if marker >= 0 else None
        )
        self.data = js_path.with_suffix(".data").read_bytes()
        self.provides = re.findall(r"^// (\\ProvidesPackage.*)$", text, re.M)
        self._cache: Dict[int, bytes] = {}

    def _chunk(self, index: int) -> bytes:
        if index not in self._cache:
            offset = self.chunks["offsets"][index]
            size = self.chunks["sizes"][index]
            raw = self.data[offset:offset + size]
            total = self.metadata["files"][-1]["end"]
            length = min(CHUNK_SIZE, total - index * CHUNK_SIZE)
            self._cache[index] = (
                _lz4_block_decompress(raw, length) if self.chunks["successes"][index] else raw
            )
        return self._cache[index]

    def read(self, filename: str) -> bytes:
        start, end = self.files[filename]
        if self.chunks is None:
            return self.data[start:end]
        pieces = []
        for index in range(start // CHUNK_SIZE, (end - 1) // CHUNK_SIZE + 1 if end > start else start // CHUNK_SIZE):
            chunk = self._chunk(index)
            lo = max(start - index * CHUNK_SIZE, 0)
            hi = min(end - index * CHUNK_SIZE, CHUNK_SIZE)
            pieces.append(chunk[lo:hi])
        return b"".join(pieces)


LOADER = """\
{provides}
// Data package for latex2quiz, made by web/texbundle.py from BusyTeX's TeX Live
// packages: only the files the exams need.  BusyTeX's LZ4 loader compresses
// the data in memory when it loads it.
(function() {{
  var Module = typeof BusytexPipeline !== 'undefined' ? BusytexPipeline : {{}};
  var DATA = {data_name};
  var metadata = {metadata};
  function runWithFS() {{
    var dependency = 'datafile_' + DATA;
    Module['addRunDependency'](dependency);
    var url = Module['locateFile'] ? Module['locateFile'](DATA, '') : DATA;
    fetch(url).then(function(response) {{
      if (!response.ok) throw new Error('Cannot load ' + url + ': HTTP ' + response.status);
      return response.arrayBuffer();
    }}).then(function(buffer) {{
      Module['LZ4'].loadPackage({{ metadata: metadata, data: buffer }}, false);
      Module['removeRunDependency'](dependency);
    }});
  }}
  if (Module['calledRun']) {{
    runWithFS();
  }} else {{
    if (!Module['preRun']) Module['preRun'] = [];
    Module['preRun'].push(runWithFS);
  }}
}})();
"""


def write_package(js_path: Path, files: Iterable[Tuple[str, bytes]], provides: Iterable[str] = ()) -> int:
    """Write ``js_path`` and its ``.data`` file; return the data size in bytes."""
    entries = []
    data = bytearray()
    for filename, contents in sorted(files):
        entries.append({"filename": filename, "start": len(data), "end": len(data) + len(contents)})
        data += contents
    data_path = js_path.with_suffix(".data")
    data_path.write_bytes(bytes(data))
    metadata = {"files": entries, "remote_package_size": len(data)}
    js_path.write_text(
        LOADER.format(
            provides="\n".join("// " + line for line in sorted(set(provides))),
            data_name=json.dumps(data_path.name),
            metadata=json.dumps(metadata),
        ),
        encoding="utf-8",
    )
    return len(data)
