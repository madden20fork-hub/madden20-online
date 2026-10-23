"""Build Madden20Online-Setup.exe (one file) from this repo + a built patched shadps4.exe.

usage: python -I installer/build_exe.py --core path\to\shadps4.exe
Needs: pip install pyinstaller cryptography pillow
Output: dist/Madden20Online-Setup.exe"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUNTIME_TOOLS = ["muthead_scrape.py", "muthead_parse.py", "art_download.py", "art_shrink.py", "pack_art.py"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", required=True, help="patched shadps4.exe (madden20-core branch build)")
    a = ap.parse_args()
    pay = REPO / "build" / "payload"
    if pay.exists():
        shutil.rmtree(pay)
    (pay / "core").mkdir(parents=True)
    shutil.copy2(a.core, pay / "core" / "shadps4.exe")
    ign = shutil.ignore_patterns("__pycache__", "*.pyc", "logs", "certs")
    for sub in ("server", "mutdata", "modroot", "dump"):
        shutil.copytree(REPO / sub, pay / sub, ignore=ign)
    (pay / "tools").mkdir()
    for t in RUNTIME_TOOLS:
        shutil.copy2(REPO / "tools" / t, pay / "tools" / t)
    shutil.copytree(REPO / "installer" / "templates", pay / "templates")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed",
           "--name", "Madden20Online-Setup", "--icon", str(pay / "core" / "shadps4.exe"),
           "--add-data", f"{pay};payload",
           "--distpath", str(REPO / "dist"), "--workpath", str(REPO / "build" / "pyi"),
           "--specpath", str(REPO / "build"),
           str(REPO / "installer" / "madden20_online.py")]
    print(" ".join(cmd))
    sys.exit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
