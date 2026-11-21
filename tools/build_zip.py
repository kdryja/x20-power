#!/usr/bin/env python3
"""Build the plugin ZIP for Decky's "Install Plugin from ZIP File" / "Install Plugin from URL".

Decky expects exactly one top-level folder holding plugin.json, and extracts that folder into
~/homebrew/plugins/ under the same name. The folder is called x20-power, so an install from the ZIP
replaces an install.sh install in place and keeps ~/homebrew/settings/x20-power.

Usage: python3 tools/build_zip.py [OUT_DIR]   (default: build/)
Writes OUT_DIR/x20-power.zip and OUT_DIR/x20-power.zip.sha256. Entries are sorted and carry the
last commit's timestamp, so the same commit always gives the same ZIP.
"""
import hashlib
import os
import subprocess
import sys
import time
import zipfile

NAME = "x20-power"
FILES = ["plugin.json", "package.json", "main.py", "dist/index.js", "LICENSE", "README.md"]

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(root, "build"))
os.makedirs(out, exist_ok=True)

try:
    stamp = int(subprocess.run(["git", "-C", root, "log", "-1", "--format=%ct"],
                               capture_output=True, text=True, check=True).stdout)
except (OSError, subprocess.CalledProcessError, ValueError):
    stamp = int(time.time())
date_time = time.gmtime(max(stamp, 315532800))[:6]  # ZIP can't store dates before 1980

zip_path = os.path.join(out, f"{NAME}.zip")
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for rel in sorted(FILES):
        info = zipfile.ZipInfo(f"{NAME}/{rel}", date_time)
        info.external_attr = 0o100644 << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        with open(os.path.join(root, rel), "rb") as f:
            z.writestr(info, f.read())

digest = hashlib.sha256(open(zip_path, "rb").read()).hexdigest()
with open(zip_path + ".sha256", "w") as f:
    f.write(f"{digest}  {NAME}.zip\n")
print(f"{zip_path}\nsha256 {digest}")
