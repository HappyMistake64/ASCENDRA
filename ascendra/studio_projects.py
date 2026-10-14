"""Generate static project candidates without executing model-produced code.

Structural checks are not browser tests, security certification, or evidence
that the requested application works. Preview generated code only in an
isolated browser origin without credentials. Publishing is a separate action.
"""
import ctypes
import errno
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit

from .capability_agent import _validate_schema


MAX_FILE_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 768 * 1024
ALLOWED_FILES = ("index.html", "styles.css", "app.js")
PROJECT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"files": {
        "type": "array", "minItems": 1, "maxItems": 3,
        "items": {"type": "object", "additionalProperties": False,
                  "properties": {"path": {"type": "string", "enum": list(ALLOWED_FILES)},
                                 "content": {"type": "string", "maxLength": MAX_FILE_BYTES}},
                  "required": ["path", "content"]}}},
    "required": ["files"],
}


class _HTMLReferences(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.references = []
        self.tags = set()
        self.styles = []
        self.in_style = False

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag)
        self.in_style = self.in_style or tag == "style"
        for name, value in attrs:
            if value is None:
                continue
            if name in {"href", "src", "action", "poster", "data"}:
                self.references.append(value)
            elif name == "style":
                self.styles.append(value)
            elif name in {"srcset", "srcdoc"}:
                raise ValueError("srcset/srcdoc are unsupported in this static-project format")
        if tag == "base":
            raise ValueError("HTML base URLs are unsupported")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "style":
            self.in_style = False

    def handle_data(self, data):
        if self.in_style:
            self.styles.append(data)


def _references(files):
    parser = _HTMLReferences()
    parser.feed(files["index.html"])
    parser.close()
    if not {"html", "head", "body"} <= parser.tags:
        raise ValueError("index.html must contain html, head and body elements")
    refs = list(parser.references)
    css = files.get("styles.css", "") + "\n" + "\n".join(parser.styles)
    # Deliberately basic static extraction; dynamic JS URLs are not evaluated.
    refs.extend(m.group(1).strip().strip("\"'") for m in re.finditer(r"url\(\s*([^)]*)\)", css, re.I))
    refs.extend(m.group(1) for m in re.finditer(r"@import\s+[\"']([^\"']+)[\"']", css, re.I))
    js = files.get("app.js", "")
    refs.extend(m.group(1) for m in re.finditer(r"(?:\bfrom\s*|\bimport\s*(?:\(\s*)?)[\"']([^\"']+)[\"']", js))
    external = set()
    for raw in refs:
        reference = raw.strip()
        if not reference or reference.startswith("#"):
            continue
        parsed = urlsplit(reference)
        if parsed.scheme or parsed.netloc:
            if parsed.scheme.lower() not in {"https", "mailto", "tel"} or (parsed.scheme == "https" and not parsed.netloc):
                raise ValueError("Unsupported reference URL scheme")
            external.add(reference)
            continue
        path = unquote(parsed.path)
        if not path:
            continue
        if path.startswith("/") or "\\" in path or any(p == ".." for p in path.split("/")) or "%" in path:
            raise ValueError("Unsafe local reference")
        if path.startswith("./"):
            path = path[2:]
        if path not in files:
            raise ValueError("Missing local reference: " + path)
    return sorted(external)


def _rename_new(source, destination):
    """Linux atomic publication with NOREPLACE (never clobber a raced target)."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    if rename is None:
        raise RuntimeError("Atomic no-overwrite publication requires Linux renameat2")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1):
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise FileExistsError(destination)
        raise OSError(code, os.strerror(code), str(destination))


def build_project(description: str, destination: Path, *, decide) -> dict:
    """Make one bounded static-web candidate via decide(request, schema).

    Destination must be new, its parent must already exist, and no component
    may be a symlink. One model call; at most three model files, 256 KiB each,
    768 KiB total. Parent directory must be trusted against concurrent renames.
    Errors leave no partial destination. No shell, generated JS, or HTML runs.
    """
    if not isinstance(description, str) or not description.strip() or len(description.encode("utf-8")) > 16000:
        raise ValueError("Description must contain 1–16000 UTF-8 bytes")
    destination = Path(os.path.abspath(destination))
    for component in (destination, *destination.parents):
        if component.is_symlink():
            raise ValueError("Symlink destinations/parents are forbidden")
    if destination.exists():
        raise FileExistsError(destination)
    if not destination.parent.is_dir():
        raise ValueError("Destination parent must already exist")
    response = decide({
        "task": "Create a static web application candidate from the user's description.",
        "description": description,
        "format": "Return index.html and optionally styles.css and app.js. Use complete HTML with html/head/body. No other files, backend, shell commands, package install, base, srcdoc or srcset. Local references must match included files. README and manifest are supplied by the host.",
        "validation_warning": "Generated code is not executed. Do not claim functional tests passed.",
    }, PROJECT_SCHEMA)
    _validate_schema(response, PROJECT_SCHEMA)
    files = {}
    total = 0
    for item in response["files"]:
        name, content = item["path"], item["content"]
        size = len(content.encode("utf-8"))
        if name in files or "\0" in content or size > MAX_FILE_BYTES:
            raise ValueError("Duplicate file, NUL content, or file size limit exceeded")
        files[name] = content
        total += size
    if total > MAX_TOTAL_BYTES or not files.get("index.html", "").strip():
        raise ValueError("Total size exceeded or index.html missing/empty")
    external = _references(files)
    files["README.md"] = (
        "# ASCENDRA static-web candidate\n\n"
        "Generated from a description. Structural checks only; functionality, accessibility, "
        "security and external dependencies have NOT been verified.\n\n"
        "After reviewing the source, serve this folder locally:\n\n"
        "```sh\npython -m http.server 8000 --bind 127.0.0.1\n```\n\n"
        "Open http://127.0.0.1:8000 in an isolated browser profile without credentials. "
        "Generated JavaScript runs in the browser. No deployment was performed.\n")
    manifest = {
        "status": "built", "artifact_type": "static_web_candidate",
        "description": description,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": [{"path": name, "bytes": len(content.encode()),
                   "sha256": hashlib.sha256(content.encode()).hexdigest()}
                  for name, content in sorted(files.items())],
        "checks": {"file_allowlist": True, "size_limits": True,
                   "html_required_elements_present": True,
                   "extracted_local_references_exist": True,
                   "code_executed": False, "functional_tests_passed": None},
        "external_references": external,
        "limitations": ["Static extraction cannot validate computed URLs or all CSS/JS syntax.",
                        "External resources, runtime behavior and security are not verified."],
    }
    staging = Path(tempfile.mkdtemp(prefix=".ascendra-build-", dir=destination.parent))
    try:
        for name, content in files.items():
            (staging / name).write_text(content, encoding="utf-8")
        (staging / "ascendra-project.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _rename_new(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return manifest
