"""Fails if data, model weights, secrets or signed documents are tracked by Git or would be picked up by `git add`.

See docs/DATA_GOVERNANCE.md §4.
"""

import fnmatch
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_PATTERNS = [
    "data/*",
    "*.dcm",
    "*.nii",
    "*.nii.gz",
    "*.pt",
    "*.pth",
    "*.ckpt",
    "*.safetensors",
    "*.onnx",
    "*.h5",
    ".env",
    ".env.*",
    "*.key",
    "*.pem",
    "*.log",
    "*.pdf",
]
ALLOWED = {"data/README.md"}


def committable_files() -> list[str]:
    """Files already tracked, plus untracked files that `git add -A` would include."""
    if shutil.which("git") is None or not (REPO_ROOT / ".git").exists():
        pytest.skip("not a git repository")
    output = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line for line in output.splitlines() if line]


def is_forbidden(path: str) -> bool:
    if path in ALLOWED:
        return False
    name = Path(path).name
    return any(fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(name, pattern) for pattern in FORBIDDEN_PATTERNS)


@pytest.mark.parametrize(
    "path, forbidden",
    [
        ("data/raw/HAM10000/ISIC_0024306.jpg", True),
        ("data/synthetic/lab_reports/syn_0001_complete.png", True),
        ("data/README.md", False),
        ("models/skin/best.pt", True),
        ("scan.dcm", True),
        (".env", True),
        ("TAF-J26-IT-445.pdf", True),
        ("lumi/main.py", False),
    ],
)
def test_forbidden_pattern_rules(path, forbidden):
    assert is_forbidden(path) is forbidden


def test_no_forbidden_files_can_be_committed():
    offenders = [path for path in committable_files() if is_forbidden(path)]
    assert offenders == [], f"These files must not be committed (docs/DATA_GOVERNANCE.md §4): {offenders}"
