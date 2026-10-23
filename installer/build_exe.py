"""Build Madden20Online-Setup.exe (one file) from this repo + a built patched shadps4.exe.

usage: python -I installer/build_exe.py --core path\to\shadps4.exe
Needs: pip install pyinstaller cryptography pillow; VS 2022 (its redist folder supplies the VC++ runtime DLLs)
Output: dist/Madden20Online-Setup.exe"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUNTIME_TOOLS = ["muthead_scrape.py", "muthead_parse.py", "art_download.py", "art_shrink.py", "pack_art.py"]
# shadps4.exe (clang-cl, /MD) imports these; Microsoft allows app-local redistribution of them.
CRT_DLLS = ["msvcp140.dll", "msvcp140_atomic_wait.dll", "vcruntime140.dll", "vcruntime140_1.dll"]


def default_crt_dir():
    base = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\2022")
    hits = sorted(base.glob(r"*\VC\Redist\MSVC\*\x64\Microsoft.VC143.CRT"))
    return str(hits[-1]) if hits else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", required=True, help="patched shadps4.exe (emulator/ build)")
    ap.add_argument("--crt", default=default_crt_dir(),
                    help="VS redist Microsoft.VC143.CRT folder (x64) holding the runtime DLLs shadps4.exe imports")
    a = ap.parse_args()
    pay = REPO / "build" / "payload"
    if pay.exists():
        shutil.rmtree(pay)
    (pay / "core").mkdir(parents=True)
    shutil.copy2(a.core, pay / "core" / "shadps4.exe")
    for dll in CRT_DLLS:                                  # app-local VC++ runtime: clean Windows installs lack it
        shutil.copy2(Path(a.crt) / dll, pay / "core" / dll)
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
