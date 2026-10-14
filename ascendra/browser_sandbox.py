"""Fail-closed Linux namespace isolation for generated project browser checks.

Only a dedicated report directory is writable outside ephemeral /tmp. No host
network, user home, workspace, provider credentials or ambient environment is
passed through. The caller must impose time/memory/CPU/process limits.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil


class SandboxUnavailable(RuntimeError):
    pass


def _required(path: Path, label: str) -> Path:
    try:
        return path.resolve(strict=True)
    except OSError as exc:
        raise SandboxUnavailable(f"Missing {label}") from exc


def build_command(project: str | Path, contract: str | Path, output: str | Path) -> list[str]:
    """Return bwrap command; never silently run unsandboxed on setup failure."""
    bwrap = shutil.which("bwrap")
    node = shutil.which("node")
    if not bwrap or not node:
        raise SandboxUnavailable("bwrap and node are required for isolated verification")
    project = _required(Path(project), "project")
    contract = _required(Path(contract), "contract")
    output = Path(output).absolute()
    output_parent = _required(output.parent, "dedicated output directory")
    if not project.is_dir() or not contract.is_file():
        raise ValueError("Project must be a directory and contract a file")
    # Avoid accidentally exposing a broad writable parent or the candidate tree.
    if output_parent in (Path('/'), Path('/tmp'), Path('/workspace'), Path.home()) or output_parent == project or output_parent in project.parents:
        raise ValueError("Output must use a dedicated directory separate from the project")
    if output.is_symlink():
        raise ValueError("Report must not be a symlink")
    verifier = _required(Path(__file__).with_name("browser_verify.mjs"), "browser verifier")
    package = _required(Path(os.environ.get("ASCENDRA_PLAYWRIGHT_PACKAGE", "/workspace/sites/ascendra-observatory/package.json")), "Playwright package anchor")
    modules = package.parent / "node_modules"
    pw = _required(modules / "playwright", "Playwright")
    core = _required(modules / "playwright-core", "Playwright core")
    chromium = _required(Path(os.environ.get("ASCENDRA_CHROMIUM", "/usr/lib/chromium/chromium")), "Chromium")
    if not chromium.is_relative_to('/usr'):
        raise SandboxUnavailable("Chromium must be installed under /usr")
    node_path = _required(Path(node), "node")
    command = [bwrap, "--unshare-all", "--die-with-parent", "--new-session", "--clearenv", "--cap-drop", "ALL", "--ro-bind", "/usr", "/usr"]
    for directory in ("/lib", "/lib64", "/bin"):
        source = Path(directory)
        if source.is_symlink():
            command += ["--symlink", os.readlink(source), directory]
        elif source.exists():
            command += ["--ro-bind", directory, directory]
    if not node_path.is_relative_to('/usr'):
        # Mount the selected Node runtime only, not sibling credentials/tools.
        runtime = node_path.parent.parent
        if runtime == Path('/') or runtime == Path('/opt'):
            raise SandboxUnavailable("Node runtime layout is not supported")
        command += ["--ro-bind", str(runtime), str(runtime)]
    command += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/etc"]
    if Path('/etc/fonts').is_dir():
        command += ["--ro-bind", "/etc/fonts", "/etc/fonts"]
    command += [
        "--ro-bind", str(verifier), "/runner/browser_verify.mjs",
        "--ro-bind", str(package), "/runner/package.json",
        "--ro-bind", str(pw), "/runner/node_modules/playwright",
        "--ro-bind", str(core), "/runner/node_modules/playwright-core",
        "--ro-bind", str(project), "/project",
        "--ro-bind", str(contract), "/contract.json",
        "--bind", str(output_parent), "/output",
        "--setenv", "HOME", "/tmp", "--setenv", "PATH", "/usr/bin:/bin",
        "--setenv", "ASCENDRA_PLAYWRIGHT_PACKAGE", "/runner/package.json",
        "--setenv", "ASCENDRA_CHROMIUM", str(chromium),
        "--chdir", "/tmp", "--", str(node_path), "/runner/browser_verify.mjs",
        "/project", "/contract.json", "/output/" + output.name,
    ]
    return command
