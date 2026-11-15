"""Build a Lambda code directory for one workspace app: locked third-party wheels for the
Lambda platform (Python 3.12, arm64) plus the source of every workspace package it uses.

    python lambda_bundle.py bw-workers /tmp/out      # what CDK runs at synth time

Third-party versions come from ``uv.lock`` (``uv export --frozen``), so a Lambda runs exactly
what CI tested. Needs ``uv`` on PATH and network access to PyPI; it never talks to AWS.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_VERSION = "3.12"
# Lambda python3.12 runs on Amazon Linux 2023 (glibc 2.34) on arm64 (lambda_.Architecture.ARM_64).
PLATFORM = "aarch64-manylinux_2_28"


def _uv(*args: str) -> str:
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is required to bundle Lambda code (https://docs.astral.sh/uv/)")
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [uv, *args], cwd=REPO_ROOT, check=False, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"uv {' '.join(args[:2])} failed:\n{result.stderr}")
    return result.stdout


def workspace_members(package: str) -> list[Path]:
    """Workspace directories (e.g. ``packages/domain``) that ``package`` depends on."""
    exported = _uv("export", "--frozen", "--no-dev", "--no-hashes", "--package", package)
    return [
        REPO_ROOT / line.removeprefix("-e ").strip()
        for line in exported.splitlines()
        if line.startswith("-e ./")
    ]


def bundle(package: str, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        requirements = Path(tmp) / "requirements.txt"
        _uv(
            "export",
            "--frozen",
            "--no-dev",
            "--no-hashes",
            "--no-emit-workspace",
            "--package",
            package,
            "--output-file",
            str(requirements),
        )
        _uv(
            "pip",
            "install",
            "--no-deps",
            "--link-mode",
            "copy",
            "--only-binary",
            ":all:",
            "--python-version",
            PYTHON_VERSION,
            "--python-platform",
            PLATFORM,
            "--target",
            str(output_dir),
            "-r",
            str(requirements),
        )
    for member in workspace_members(package):
        for source in (member / "src").iterdir():
            if source.is_dir() and not source.name.startswith((".", "_")):
                shutil.copytree(
                    source,
                    output_dir / source.name,
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: lambda_bundle.py <workspace-package> <output-dir>")
    bundle(sys.argv[1], Path(sys.argv[2]))
