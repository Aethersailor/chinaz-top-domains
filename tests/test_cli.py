from __future__ import annotations

import os
import subprocess
import sys


def test_help_uses_utf8_when_parent_encoding_is_cp1252() -> None:
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "cp1252"
    result = subprocess.run(
        [sys.executable, "-m", "chinaz_top_domains", "--help"],
        check=True,
        capture_output=True,
        env=environment,
    )

    output = result.stdout.decode("utf-8")
    assert "抓取 ChinaZ 网站总排名" in output
