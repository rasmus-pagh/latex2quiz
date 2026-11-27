// Browser front end for latex2quiz: the Python implementation runs unchanged
// in Pyodide; LaTeX is compiled by BusyTeX (TeX Live in WebAssembly) in a
// worker, and pdf.js turns the PDF pages into PNG images.
'use strict';

const PYODIDE_INDEX = 'https://cdn.jsdelivr.net/pyodide/v0.27.2/full/';
const PDFJS_WORKER = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
// Every module of latex2quiz_lib (tests/test_latex2quiz.py checks this list).
const PYTHON_MODULES = [
  '__init__', 'alttext', 'cli', 'htmltext', 'learnosity', 'model', 'package',
  'qti', 'render', 'source',
];
const BUSYTEX = new URL('vendor/busytex/', location.href).href;
// The small bundle holds only the TeX Live files the exams need (built by
// web/setup.py from web/texlive-files.txt). The full bundles are the fallback
// when a document needs anything else; a server may leave them out.
const SMALL_BUNDLE = [BUSYTEX + 'latex2quiz-texlive.js'];
const FULL_BUNDLES = [
  'texlive-basic.js',
  'ubuntu-texlive-latex-base.js',
  'ubuntu-texlive-latex-recommended.js',
  'ubuntu-texlive-latex-extra.js',
  'ubuntu-texlive-science.js',
].map(name => BUSYTEX + name);
// A failed compile with one of these messages may just need files outside the
// small bundle. LaTeX substitutes a missing font shape with only a warning, so
// a successful compile that substituted one is retried as well.
const MISSING_FILE = /not found|not loadable|cannot find|cannot open/i;
const SUBSTITUTED_FONT = /Font shape `[^']*' undefined|Some font shapes were not available/;
const WORK = '/work';

const $ = id => document.getElementById(id);
const uploaded = new Map(); // file name -> Uint8Array
let pyodide = null;
let bridge = null;
let tex = null;
let texExtras = null;

function setStatus(text, kind = '') {
  $('status').textContent = text;
  $('status').className = kind;
}

function log(text) {
  $('log').textContent += text.endsWith('\n') ? text : text + '\n';
  $('log').scrollTop = $('log').scrollHeight;
}

function seconds(start) {
  return ((performance.now() - start) / 1000).toFixed(1) + ' s';
}

async function initPython() {
  const start = performance.now();
  pyodide = await loadPyodide({ indexURL: PYODIDE_INDEX });
  const fs = pyodide.FS;
  fs.mkdirTree('/lib/latex2quiz_lib');
  fs.mkdirTree(WORK);
  const sources = await Promise.all([
    ...PYTHON_MODULES.map(name => fetchText(`../latex2quiz_lib/${name}.py`).then(text => [`/lib/latex2quiz_lib/${name}.py`, text])),
    fetchText('latex2quiz_web.py').then(text => ['/lib/latex2quiz_web.py', text]),
  ]);
  for (const [path, text] of sources) fs.writeFile(path, text);
  pyodide.runPython("import sys; sys.path.insert(0, '/lib')");
  bridge = pyodide.pyimport('latex2quiz_web');
  log(`Python ready (${seconds(start)}).`);
}

async function fetchText(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Cannot load ${url}: HTTP ${response.status}`);
  return response.text();
}

// ---------------------------------------------------------------- TeX engine

class TexEngine {
  constructor(bundles) {
    this.bundles = bundles;
    this.worker = new Worker(BUSYTEX + 'busytex_worker.js');
    this.pending = null;
    this.printed = [];
    this.ready = new Promise((resolve, reject) => { this.onReady = resolve; this.onInitError = reject; });
    this.worker.onmessage = ({ data }) => this.receive(data);
    this.worker.onerror = event => this.fail(new Error(event.message || 'TeX worker failed'));
    this.worker.postMessage({
      busytex_js: BUSYTEX + 'busytex.js',
      busytex_wasm: BUSYTEX + 'busytex.wasm',
      preload_data_packages_js: bundles,
      data_packages_js: bundles,
      texmf_local: [],
      preload: true,
    });
  }

  receive(data) {
    if (data.print !== undefined) {
      this.printed.push(data.print);
      if (this.printed.length > 200) this.printed.shift();
    } else if (data.initialized !== undefined) {
      this.onReady();
    } else if (data.exception !== undefined) {
      this.fail(new Error(data.exception));
    } else if ('pdf' in data) {
      const pending = this.pending;
      this.pending = null;
      if (pending) pending.resolve(data);
    }
  }

  fail(error) {
    if (this.pending) {
      this.pending.reject(error);
      this.pending = null;
    } else {
      this.onInitError(error);
    }
  }

  async compile(files) {
    await this.ready;
    return new Promise((resolve, reject) => {
      this.pending = { resolve, reject };
      this.worker.postMessage({
        files, main_tex_path: 'render.tex', bibtex: false, verbose: 'silent',
        driver: 'pdftex_bibtex8', data_packages_js: this.bundles,
      });
    });
  }
}

async function loadTexExtras() {
  // PGF/TikZ and preview, which the BusyTeX bundles lack (see web/setup.py).
  const response = await fetch('vendor/texmf-extra.json');
  if (!response.ok) throw new Error('vendor/texmf-extra.json is missing: run web/setup.py first');
  const { files, font_map: fontMap } = await response.json();
  return {
    fontMap,
    files: Object.entries(files).map(([path, base64]) => ({ path, contents: decodeBase64(base64) })),
  };
}

function decodeBase64(text) {
  const binary = atob(text);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

// Compile the document the Python renderer asked for, rasterize every page
// at the requested resolutions, and hand the PNG data back to Python.
async function renderDocument(request) {
  if (!tex) {
    const start = performance.now();
    setStatus('Loading TeX (about 45 MB the first time)…');
    tex = new TexEngine(SMALL_BUNDLE);
    [texExtras] = await Promise.all([loadTexExtras(), tex.ready]);
    log(`TeX ready (${seconds(start)}).`);
  }
  setStatus(`Compiling ${request.pages} images with LaTeX…`);
  let start = performance.now();
  // The font map adds the TS1 fonts that the bundles lack; it only affects
  // which font files pdfTeX embeds, so the document is otherwise unchanged.
  const compiled = `\\pdfmapfile{+${texExtras.fontMap}}\n` + request.document;
  const files = [
    { path: 'render.tex', contents: compiled },
    ...texExtras.files,
    ...[...uploaded].map(([path, contents]) => ({ path, contents })),
  ];
  let result = await tex.compile(files);
  const failed = !result.pdf || result.exit_code !== 0;
  const output = compilerOutput(result);
  if (tex.bundles === SMALL_BUNDLE && (failed ? MISSING_FILE : SUBSTITUTED_FONT).test(output) &&
      await fullBundlesAvailable()) {
    log('This document needs TeX files outside the small bundle; loading the full TeX Live bundles (about 210 MB).');
    setStatus('Loading the full TeX Live bundles…');
    tex.worker.terminate();
    tex = new TexEngine(FULL_BUNDLES);
    result = await tex.compile(files);
  }
  if (!result.pdf || result.exit_code !== 0) {
    throw new Error(bridge.failure_message(compiled, compilerOutput(result)));
  }
  log(`LaTeX: ${request.pages} pages in ${seconds(start)}.`);

  start = performance.now();
  const pdf = await pdfjsLib.getDocument({ data: result.pdf }).promise;
  if (pdf.numPages !== request.pages) {
    throw new Error(`Expected ${request.pages} rendered pages, but the PDF has ${pdf.numPages}`);
  }
  for (const resolution of request.resolutions) {
    setStatus(`Making images at ${resolution} dpi…`);
    const pngs = [];
    for (let number = 1; number <= pdf.numPages; number++) {
      pngs.push(await rasterize(await pdf.getPage(number), resolution));
    }
    bridge.provide_pages(request.key, resolution, pngs);
  }
  log(`Images: ${request.pages} pages at ${request.resolutions.join(' and ')} dpi in ${seconds(start)}.`);
}

function compilerOutput(result) {
  const output = (result.logs || [])
    .map(entry => [entry.stdout, entry.stderr, entry.log].filter(Boolean).join('\n')).join('\n');
  // If TeX printed nothing, the engine's own messages say why.
  return output.trim() ? output : tex.printed.slice(-40).join('\n');
}

async function fullBundlesAvailable() {
  try {
    return (await fetch(FULL_BUNDLES[0], { method: 'HEAD' })).ok;
  } catch {
    return false;
  }
}

async function rasterize(page, resolution) {
  const viewport = page.getViewport({ scale: resolution / 72 });
  const canvas = document.createElement('canvas');
  canvas.width = Math.ceil(viewport.width);
  canvas.height = Math.ceil(viewport.height);
  const context = canvas.getContext('2d');
  context.fillStyle = '#ffffff';
  context.fillRect(0, 0, canvas.width, canvas.height);
  await page.render({ canvasContext: context, viewport }).promise;
  const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
  page.cleanup();
  return new Uint8Array(await blob.arrayBuffer());
}

// ------------------------------------------------------------------ commands

// Run the command line, rendering documents for it until it finishes.
async function runCommand(args) {
  for (let round = 0; round < 3; round++) {
    const proxy = bridge.run(args);
    const result = proxy.toJs({ dict_converter: Object.fromEntries });
    proxy.destroy();
    if (result.status === 'done') return result;
    await renderDocument(result);
  }
  throw new Error('Rendering did not converge');
}

function mainFile() {
  return `${WORK}/${$('main').value}`;
}

function writeUploads() {
  const fs = pyodide.FS;
  for (const name of fs.readdir(WORK)) {
    if (name !== '.' && name !== '..') fs.unlink(`${WORK}/${name}`);
  }
  for (const [name, bytes] of uploaded) fs.writeFile(`${WORK}/${name}`, bytes);
}

function report(result, started) {
  if (result.stdout) log(result.stdout);
  if (result.stderr) log(result.stderr);
  if (result.code === 0) setStatus(`Done in ${seconds(started)}.`, 'ok');
  else setStatus('Failed: see the messages below.', 'error');
}

async function check() {
  const started = performance.now();
  await withBusy(async () => {
    writeUploads();
    report(await runCommand([mainFile(), '--check', '--language', $('language').value]), started);
  });
}

async function convert() {
  const started = performance.now();
  await withBusy(async () => {
    writeUploads();
    $('downloads').textContent = '';
    const input = mainFile();
    const result = await runCommand([input, '--format', $('format').value, '--language', $('language').value]);
    report(result, started);
    if (result.code !== 0) return;
    const stem = input.replace(/\.tex$/, '');
    for (const [suffix, type] of [['-qti.zip', 'application/zip'], ['-learnosity.json', 'application/json']]) {
      const path = stem + suffix;
      if (!pyodide.FS.analyzePath(path).exists) continue;
      const link = document.createElement('a');
      link.href = URL.createObjectURL(new Blob([pyodide.FS.readFile(path)], { type }));
      link.download = path.slice(WORK.length + 1);
      link.textContent = `Download ${link.download}`;
      $('downloads').append(link);
    }
  });
}

async function withBusy(action) {
  for (const id of ['check', 'convert', 'files']) $(id).disabled = true;
  $('log').textContent = '';
  setStatus('Working…');
  try {
    await action();
  } catch (error) {
    setStatus('Failed: see the messages below.', 'error');
    log(String(error && error.message ? error.message : error));
  } finally {
    for (const id of ['check', 'convert', 'files']) $(id).disabled = false;
  }
}

$('files').addEventListener('change', async event => {
  uploaded.clear();
  for (const file of event.target.files) uploaded.set(file.name, new Uint8Array(await file.arrayBuffer()));
  const texFiles = [...uploaded.keys()].filter(name => name.endsWith('.tex')).sort();
  const select = $('main');
  select.textContent = '';
  for (const name of texFiles) select.append(new Option(name, name));
  const preferred = texFiles.find(name => /^(ad|dma)-/.test(name));
  if (preferred) select.value = preferred;
  select.disabled = texFiles.length === 0;
  if (!texFiles.length) select.append(new Option('No .tex file selected'));
  const ready = texFiles.length > 0 && bridge !== null;
  $('check').disabled = $('convert').disabled = !ready;
});

$('check').addEventListener('click', check);
$('convert').addEventListener('click', convert);

pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER;
initPython().then(() => {
  setStatus('Ready. Select the files to convert.');
  if (uploaded.size) $('check').disabled = $('convert').disabled = false;
}).catch(error => {
  setStatus('Python failed to load.', 'error');
  log(String(error));
});
