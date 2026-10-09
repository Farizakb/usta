"""The image has what skills need, and works under the hardening flags (SPEC §10)."""

import json
import os
import subprocess

import pytest

pytestmark = pytest.mark.sandbox

IMAGE = os.environ.get("USTA_TEST_SANDBOX_IMAGE", "usta-sandbox:1")
RUNTIME = os.environ.get("USTA_TEST_SANDBOX_RUNTIME", "runsc")

PROBE = """
import json, os, sys
import babel, docx, matplotlib, openpyxl, pandas, pdfplumber, reportlab
import matplotlib.font_manager as fm
fonts = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
]
print(json.dumps({
    "python": sys.version_info[:2],
    "fonts": [os.path.exists(f) for f in fonts],
    "mpl_font": os.path.basename(fm.findfont("DejaVu Sans")),
    "uid": os.getuid(),
}))
"""


def test_image_has_python_libraries_and_fonts() -> None:
    proc = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--runtime",
            RUNTIME,
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "-i",
            IMAGE,
            "python",
            "-",
        ],
        input=PROBE,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    info = json.loads(proc.stdout.strip().splitlines()[-1])
    assert info["python"] == [3, 12]
    assert info["fonts"] == [True, True, True]
    assert info["mpl_font"] == "DejaVuSans.ttf"
    assert info["uid"] == os.getuid() != 0
