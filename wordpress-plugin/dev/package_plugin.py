"""Build the installable plugin zip: dist/org-chatbot-<version>.zip

    python wordpress-plugin/dev/package_plugin.py

Upload the zip in WordPress under Plugins > Add New > Upload Plugin. The zip
holds a single top-level org-chatbot/ folder with forward-slash paths, which is
what WordPress expects (PowerShell's Compress-Archive writes backslashes, which
break on Linux hosts). Only the plugin itself is packed; dev/ stays out.
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "wordpress-plugin" / "org-chatbot"
DIST = ROOT / "dist"
SKIP = {".DS_Store", "Thumbs.db", "desktop.ini"}


def plugin_version() -> str:
    header = (PLUGIN / "org-chatbot.php").read_text(encoding="utf-8")
    match = re.search(r"^\s*\*\s*Version:\s*(\S+)", header, re.MULTILINE)
    if not match:
        sys.exit("No 'Version:' line in org-chatbot.php")
    return match.group(1)


def main() -> int:
    version = plugin_version()
    constant = re.search(r"ORG_CHATBOT_VERSION',\s*'([^']+)'", (PLUGIN / "org-chatbot.php").read_text(encoding="utf-8"))
    stable = re.search(r"^Stable tag:\s*(\S+)", (PLUGIN / "readme.txt").read_text(encoding="utf-8"), re.MULTILINE)
    if not constant or constant.group(1) != version or not stable or stable.group(1) != version:
        sys.exit(f"Version mismatch: header {version}, ORG_CHATBOT_VERSION and readme.txt Stable tag must match")

    DIST.mkdir(exist_ok=True)
    target = DIST / f"org-chatbot-{version}.zip"
    files = sorted(p for p in PLUGIN.rglob("*") if p.is_file() and p.name not in SKIP)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, "org-chatbot/" + path.relative_to(PLUGIN).as_posix())
    print(f"{target.relative_to(ROOT)}  ({len(files)} files, {target.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
