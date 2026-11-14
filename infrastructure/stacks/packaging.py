"""Lambda code assets with their dependencies bundled at synth time.

``python_app_code("bw-workers")`` runs ``lambda_bundle.py`` locally (needs ``uv``), or in the
Lambda Python build image through Docker when uv is not installed. The asset hash is taken
from the bundled output, so an unchanged lockfile and source produce an unchanged asset.

Tests skip bundling (``aws:cdk:bundling-stacks`` = ``[]``); the asset then points at the
source tree and is never deployable, which is fine for template assertions.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import aws_cdk as cdk
import jsii
import lambda_bundle
from aws_cdk import aws_lambda as lambda_

REPO_ROOT = lambda_bundle.REPO_ROOT
UV_VERSION = "0.11.32"  # same as CI

# Kept out of the (unused) source fingerprint and of the Docker mount's copy.
SOURCE_EXCLUDES = [
    ".git",
    "**/.venv",
    "**/node_modules",
    "**/__pycache__",
    "**/.pytest_cache",
    "**/.mypy_cache",
    "**/.ruff_cache",
    "infrastructure/cdk.out",
    "apps/web",
    "device",
    "docs",
    "contracts",
    "tests",
]


@jsii.implements(cdk.ILocalBundling)
class _UvLocalBundling:
    def __init__(self, package: str) -> None:
        self._package = package

    def try_bundle(self, output_dir: str, *, image: Any = None, **_: Any) -> bool:
        if shutil.which("uv") is None:
            return False  # fall back to Docker
        lambda_bundle.bundle(self._package, Path(output_dir))
        return True


def python_app_code(package: str) -> lambda_.Code:
    return lambda_.Code.from_asset(
        str(REPO_ROOT),
        exclude=SOURCE_EXCLUDES,
        asset_hash_type=cdk.AssetHashType.OUTPUT,
        bundling=cdk.BundlingOptions(
            image=lambda_.Runtime.PYTHON_3_12.bundling_image,
            local=_UvLocalBundling(package),
            command=[
                "bash",
                "-c",
                "export UV_CACHE_DIR=/tmp/uv-cache PATH=/tmp/uv/bin:$PATH && "
                f"pip install --quiet --target /tmp/uv uv=={UV_VERSION} && "
                f"python infrastructure/lambda_bundle.py {package} /asset-output",
            ],
        ),
    )
