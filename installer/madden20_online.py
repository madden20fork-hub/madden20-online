"""Madden 20 Online - installer + launcher in one executable.

First run (no settings.json next to the exe): setup window. It asks for an already-extracted Madden NFL 20 PS4 game
folder (CUSA13265, version 01.00), installs the patched shadPS4 build, the local Blaze/HTTP servers and the data
tables into an install folder, generates a TLS certificate and creates a desktop shortcut. The game files
themselves are never modified.

Installed (settings.json next to the exe): launcher window. "Download card data" (once) scrapes the MUT 20 card
catalog + card art from Muthead; "Play" starts both local servers, runs the game, and stops the servers when the
game exits.

Internal modes (the exe re-invokes itself):
  --serve http|blaze     run server/http_server.py or server/blaze_server.py with this exe's bundled Python
  --tool NAME [ARGS..]   run tools/NAME.py (card scraper / parser / art tools)
"""
import hashlib
import json
import os
import runpy
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

APP = "Madden 20 Online"
EXE_NAME = "Madden20Online.exe"
TITLE_ID = "CUSA13265"
APP_VER = "01.00"
EBOOT_MD5 = "c973befec7acd462d31d084743d1b513"      # US base game 01.00 (the build every fix was made against)
BLAZE_PORT, HTTPS_PORTS, PLAIN_PORT = 10041, (42230, 443), 42240
NO_WINDOW = 0x08000000                                 # CREATE_NO_WINDOW


def _bundle_imports():
    """Never called. Lists the modules the server and tools need so PyInstaller bundles them: those .py files run
    from the install folder with this exe's interpreter."""
    import concurrent.futures  # noqa: F401
    import datetime  # noqa: F401
    import html  # noqa: F401
    import http.server  # noqa: F401
    import importlib  # noqa: F401
    import ipaddress  # noqa: F401
    import itertools  # noqa: F401
    import random  # noqa: F401
    import re  # noqa: F401
    import socketserver  # noqa: F401
    import ssl  # noqa: F401
    import traceback  # noqa: F401
    import urllib.request  # noqa: F401
    import argparse  # noqa: F401
    import io  # noqa: F401
    from cryptography import x509  # noqa: F401
    from cryptography.hazmat.primitives import hashes, serialization  # noqa: F401
    from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: F401
    from cryptography.x509.oid import NameOID  # noqa: F401
    from PIL import Image, ImageDraw, ImageFilter  # noqa: F401


# ---------------------------------------------------------------- paths
def frozen():
    return getattr(sys, "frozen", False)


def exe_dir():
    return Path(sys.executable).parent if frozen() else Path(__file__).resolve().parent


def install_root():
    """Install folder for --serve/--tool children (MADDEN_ROOT, set by the parent), else the exe's folder."""
    return Path(os.environ.get("MADDEN_ROOT") or exe_dir())


def payload_dir():
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent / "build"))
    return base / "payload"


def self_cmd(*args):
    return [sys.executable, *args] if frozen() else [sys.executable, str(Path(__file__).resolve()), *args]


def ansi_safe(path):
    """shadPS4 takes paths through narrow (ANSI code page) APIs - argv for -g, getenv for the mod root, fopen for the
    flags. A character outside this PC's code page cannot reach it intact (mbcs strict = no best-fit guessing)."""
    try:
        str(path).encode("mbcs", errors="strict")
        return True
    except UnicodeEncodeError:
        return False


def default_install_dir():
    home = Path(os.path.expandvars(r"%USERPROFILE%"))
    if ansi_safe(home):
        return home / "Madden20Online"
    return Path(os.environ.get("SystemDrive", "C:") + "\\") / "Madden20Online"


def check_install_dir(path):
    """-> error message, or None if the folder can be created and written and the emulator can take its path."""
    p = Path(path)
    if not str(path).strip() or not p.is_absolute():
        return "Pick a full install folder path (for example C:\\Madden20Online)."
    if not ansi_safe(p):
        return (f"The install folder path has characters this PC's language setting can't pass to the emulator:\n{p}\n"
                "Pick a folder whose path uses only plain letters, e.g. C:\\Madden20Online.")
    try:
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".write_test"
        probe.write_text("ok")
        probe.unlink()
    except OSError as e:
        return f"Can't write to {p} ({e.strerror}). Pick a folder you own, e.g. C:\\Madden20Online (not Program Files)."
    return None


def load_settings(d):
    p = Path(d) / "settings.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def save_settings(d, s):
    (Path(d) / "settings.json").write_text(json.dumps(s, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- internal modes
def serve(which):
    root = install_root()
    srv = root / "server"
    os.chdir(srv)
    sys.path.insert(0, str(srv))
    script = {"http": "http_server.py", "blaze": "blaze_server.py"}[which]
    args = {"http": [str(p) for p in HTTPS_PORTS] + ["--plain", str(PLAIN_PORT)], "blaze": [str(BLAZE_PORT)]}[which]
    sys.argv = [script, *args]
    runpy.run_path(str(srv / script), run_name="__main__")


def tool(name, args):
    root = install_root()
    for sub in ("tools", "server"):
        sys.path.insert(0, str(root / sub))
    path = root / "tools" / f"{name}.py"
    if name == "make_cert":
        path = root / "server" / "make_cert.py"
        os.chdir(root / "server")
    sys.argv = [str(path), *args]
    runpy.run_path(str(path), run_name="__main__")


# ---------------------------------------------------------------- game folder check
def read_sfo(path):
    d = Path(path).read_bytes()
    _magic, _ver, kt, dt, n = struct.unpack_from("<IIIII", d, 0)
    out = {}
    for i in range(n):
        ko, fmt, ln, _mx, do = struct.unpack_from("<HHIII", d, 20 + i * 16)
        k = d[kt + ko:d.index(b"\0", kt + ko)].decode()
        v = d[dt + do:dt + do + ln]
        out[k] = v.rstrip(b"\0").decode(errors="replace") if fmt in (0x0204, 0x0004) else int.from_bytes(v[:4], "little")
    return out


def check_game(folder):
    """-> (ok, message, eboot_path). Accepts the folder that holds eboot.bin (or a parent with uroot/)."""
    f = Path(folder)
    for cand in (f, f / "uroot"):
        if (cand / "eboot.bin").exists() and (cand / "sce_sys" / "param.sfo").exists():
            f = cand
            break
    else:
        return False, "No eboot.bin + sce_sys\\param.sfo found. Pick the extracted CUSA13265 game folder.", None
    if not ansi_safe(f):
        return False, (f"The game folder path has characters this PC's language setting can't pass to the emulator:\n"
                       f"{f}\nMove or rename it so the path uses only plain letters, e.g. E:\\Games\\CUSA13265."), None
    sfo = read_sfo(f / "sce_sys" / "param.sfo")
    if sfo.get("TITLE_ID") != TITLE_ID:
        return False, f"This is {sfo.get('TITLE_ID')} ({sfo.get('TITLE')}), not Madden NFL 20 ({TITLE_ID}).", None
    warn = ""
    if sfo.get("APP_VER") != APP_VER:
        warn = f"\nWarning: game version {sfo.get('APP_VER')}; this release was built for {APP_VER} (no update)."
    md5 = hashlib.md5((f / "eboot.bin").read_bytes()).hexdigest()
    if md5 != EBOOT_MD5:
        warn += "\nWarning: eboot.bin differs from the tested 01.00 build - it may not work."
    return True, f"Madden NFL 20 {sfo.get('APP_VER')} found.{warn}", f / "eboot.bin"


# ---------------------------------------------------------------- install steps
def write_emulator_config(install, fullscreen):
    user = install / "core" / "user"
    (user / "custom_configs").mkdir(parents=True, exist_ok=True)
    tmpl = json.loads((payload_dir() / "templates" / "config.json").read_text(encoding="utf-8"))
    tmpl["GPU"]["full_screen"] = bool(fullscreen)
    (user / "config.json").write_text(json.dumps(tmpl, indent=4), encoding="utf-8")
    shutil.copy2(payload_dir() / "templates" / "CUSA13265.json", user / "custom_configs" / "CUSA13265.json")


def make_shortcut(target, name):
    """Desktop shortcut. The Desktop comes from the shell (it may be redirected to OneDrive); paths are passed as
    PowerShell single-quoted strings, where a ' is written ''."""
    def q(s):
        return "'" + str(s).replace("'", "''") + "'"
    ps = (f"$d=[Environment]::GetFolderPath('Desktop');"
          f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d {q(name + '.lnk')}));"
          f"$s.TargetPath={q(target)};$s.WorkingDirectory={q(target.parent)};$s.IconLocation={q(f'{target},0')};"
          f"$s.Save()")
    return subprocess.run(["powershell", "-NoProfile", "-Command", ps], creationflags=NO_WINDOW,
                          check=False).returncode == 0


def run_logged(cmd, log, cwd=None, env=None):
    env = dict(env or os.environ, MADDEN_ROOT=str(Path(cwd).resolve()) if cwd else os.environ.get("MADDEN_ROOT", ""))
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace", creationflags=NO_WINDOW, bufsize=1)
    for line in p.stdout:
        log(line.rstrip())
    return p.wait()


def download_cards(install, with_art, log):
    """Scrape the MUT 20 catalog from Muthead (resumable cache in mutdata/raw), parse it, then optionally the art."""
    log("Downloading the MUT 20 card catalog from Muthead (about 3,800 pages; resumes if interrupted)...")
    if run_logged(self_cmd("--tool", "muthead_scrape"), log, cwd=install) != 0:
        return False
    if run_logged(self_cmd("--tool", "muthead_parse"), log, cwd=install) != 0:
        return False
    if with_art:
        log("Downloading card art (~1 GB)...")
        if run_logged(self_cmd("--tool", "art_download"), log, cwd=install) != 0:
            return False
        run_logged(self_cmd("--tool", "art_shrink"), log, cwd=install)
        run_logged(self_cmd("--tool", "pack_art"), log, cwd=install)
    return (install / "mutdata" / "cards.json").exists()


def install(install_dir, game_eboot, fullscreen, with_art, shortcut, log, done):
    try:
        install = Path(install_dir)
        err = check_install_dir(install)
        if err:
            raise RuntimeError(err)
        log(f"Installing to {install}")
        pl = payload_dir()
        for sub in ("core", "server", "tools", "mutdata", "modroot", "dump", "docs"):
            if (pl / sub).exists():
                shutil.copytree(pl / sub, install / sub, dirs_exist_ok=True)
        (install / "server" / "logs").mkdir(exist_ok=True)
        write_emulator_config(install, fullscreen)
        if frozen():
            shutil.copy2(sys.executable, install / EXE_NAME)
        s = {"game_eboot": str(game_eboot), "fullscreen": bool(fullscreen), "cards_ready": False}
        save_settings(install, s)
        log("Generating a local TLS certificate...")
        if run_logged(self_cmd("--tool", "make_cert"), log, cwd=install) != 0 or                 not (install / "server" / "certs" / "ea.crt").exists():
            raise RuntimeError("certificate generation failed")
        if shortcut and frozen():
            log("Desktop shortcut created." if make_shortcut(install / EXE_NAME, APP) else
                f"Could not create the desktop shortcut - start {install / EXE_NAME} directly.")
        log("Installed. Open the launcher and click 'Download card data' once before playing Ultimate Team.")
        done(True, install)
    except Exception as e:  # noqa: BLE001
        log(f"ERROR: {e}")
        done(False, None)


# ---------------------------------------------------------------- play
def port_free(port, host="0.0.0.0"):
    s = socket.socket()
    try:
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def play(install, log):
    install = Path(install)
    s = load_settings(install)
    eboot = Path(s["game_eboot"])
    if not eboot.exists():
        log(f"Game not found at {eboot}. Connect that drive, or click 'Game folder...' and pick the game again.")
        return
    if not ansi_safe(install):
        log(f"The install folder path ({install}) can't be passed to the emulator on this PC. Reinstall to a plain "
            "path such as C:\\Madden20Online.")
        return
    if not (install / "mutdata" / "cards.json").exists():
        log("Card data missing - click 'Download card data' first.")
        return
    busy = [p for p in (*HTTPS_PORTS, PLAIN_PORT, BLAZE_PORT) if not port_free(p)]
    if busy:
        log(f"Ports in use: {busy}. Close whatever uses them (another server copy, IIS/VMware on 443) and retry.")
        return
    env = dict(os.environ, MADDEN_PLATFORM="ps4", MADDEN_VERBOSE="0", MADDEN_ROOT=str(install))
    logs = install / "server" / "logs"
    logs.mkdir(exist_ok=True)
    srv = []
    for which in ("http", "blaze"):
        out = open(logs / f"{which}_console.log", "w", encoding="utf-8")
        srv.append(subprocess.Popen(self_cmd("--serve", which), cwd=install, env=env, stdout=out,
                                    stderr=subprocess.STDOUT, creationflags=NO_WINDOW))
    time.sleep(2)
    if any(p.poll() is not None for p in srv):
        log("A server failed to start - see server\\logs\\*_console.log")
        for p in srv:
            p.kill()
        return
    log("Servers running. Starting Madden NFL 20...")
    genv = dict(os.environ, NBA2K14_MOD_ROOT=str(install / "modroot"))
    core = install / "core"
    game = subprocess.Popen([str(core / "shadps4.exe"), "-g", s["game_eboot"], "-f",
                             "true" if s.get("fullscreen", True) else "false"], cwd=core, env=genv)
    game.wait()
    log(f"Game closed (exit {game.returncode}). Stopping servers.")
    for p in srv:
        p.terminate()


# ---------------------------------------------------------------- UI
class Window(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP)
        self.geometry("720x520")
        self.minsize(600, 420)
        self.text = tk.Text(self, height=14, wrap="word", state="disabled")
        self.installed = load_settings(exe_dir())
        if self.installed:
            self.build_launcher()
        else:
            self.build_setup()

    def log(self, msg):
        def w():
            self.text.configure(state="normal")
            self.text.insert("end", msg + "\n")
            self.text.see("end")
            self.text.configure(state="disabled")
        self.after(0, w)

    # ---- setup
    def build_setup(self):
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=f"{APP} - setup", font=("Segoe UI", 14, "bold")).grid(row=0, column=0, columnspan=3,
                                                                              sticky="w")
        ttk.Label(f, text="You need your own extracted Madden NFL 20 PS4 game (CUSA13265, version 01.00). "
                          "The game files are not modified.", wraplength=660).grid(row=1, column=0, columnspan=3,
                                                                                     sticky="w", pady=(4, 10))
        self.game = tk.StringVar()
        self.dest = tk.StringVar(value=str(default_install_dir()))
        self.full = tk.BooleanVar(value=True)
        self.art = tk.BooleanVar(value=True)
        self.lnk = tk.BooleanVar(value=True)
        for r, (label, var, pick) in enumerate((("Madden 20 game folder", self.game, self.pick_game),
                                                ("Install folder", self.dest, self.pick_dest)), start=2):
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w")
            ttk.Entry(f, textvariable=var, width=60).grid(row=r, column=1, sticky="we", padx=6)
            ttk.Button(f, text="Browse...", command=pick).grid(row=r, column=2)
        ttk.Checkbutton(f, text="Play fullscreen", variable=self.full).grid(row=5, column=1, sticky="w",
                                                                             pady=(8, 0))
        ttk.Checkbutton(f, text="Desktop shortcut", variable=self.lnk).grid(row=6, column=1, sticky="w")
        self.go = ttk.Button(f, text="Install", command=self.do_install)
        self.go.grid(row=7, column=1, sticky="w", pady=8)
        self.text.pack(in_=f, fill="both", expand=True) if False else self.text.grid(
            in_=f, row=8, column=0, columnspan=3, sticky="nsew")
        f.columnconfigure(1, weight=1)
        f.rowconfigure(8, weight=1)

    def pick_game(self):
        d = filedialog.askdirectory(title="Extracted Madden NFL 20 folder (contains eboot.bin)")
        if d:
            self.game.set(d)
            ok, msg, _ = check_game(d)
            self.log(msg)

    def pick_dest(self):
        d = filedialog.askdirectory(title="Install folder")
        if d:
            self.dest.set(str(Path(d) / "Madden20Online") if not d.lower().endswith("madden20online") else d)

    def do_install(self):
        ok, msg, eboot = check_game(self.game.get())
        self.log(msg)
        if not ok:
            messagebox.showerror(APP, msg)
            return
        err = check_install_dir(self.dest.get())
        if err:
            self.log(err)
            messagebox.showerror(APP, err)
            return
        self.go.configure(state="disabled")

        def done(success, where):
            def ui():
                if success:
                    messagebox.showinfo(APP, f"Installed. Launch '{APP}' from the desktop shortcut or "
                                             f"{Path(where) / EXE_NAME}.")
                self.go.configure(state="normal")
            self.after(0, ui)

        threading.Thread(target=install, args=(self.dest.get(), eboot, self.full.get(), self.art.get(),
                                               self.lnk.get(), self.log, done), daemon=True).start()

    # ---- launcher
    def build_launcher(self):
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text=APP, font=("Segoe UI", 14, "bold")).pack(anchor="w")
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=8)
        self.playb = ttk.Button(bar, text="Play", command=self.do_play)
        self.playb.pack(side="left")
        ttk.Button(bar, text="Download card data", command=self.do_cards).pack(side="left", padx=6)
        self.art = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="incl. card art (~1 GB)", variable=self.art).pack(side="left")
        self.full = tk.BooleanVar(value=self.installed.get("fullscreen", True))
        ttk.Checkbutton(bar, text="Fullscreen", variable=self.full, command=self.save_full).pack(side="left", padx=6)
        ttk.Button(bar, text="Open install folder", command=lambda: os.startfile(exe_dir())).pack(side="right")
        ttk.Button(bar, text="Game folder...", command=self.change_game).pack(side="right", padx=6)
        self.text.pack(in_=f, fill="both", expand=True)
        if not (exe_dir() / "mutdata" / "cards.json").exists():
            self.log("Card data not downloaded yet - click 'Download card data' (needed once).")
        else:
            self.log("Ready. Click Play.")

    def change_game(self):
        """Re-point the install at the game (moved folder, new drive letter)."""
        d = filedialog.askdirectory(title="Extracted Madden NFL 20 folder (contains eboot.bin)")
        if not d:
            return
        ok, msg, eboot = check_game(d)
        self.log(msg)
        if not ok:
            messagebox.showerror(APP, msg)
            return
        s = load_settings(exe_dir())
        s["game_eboot"] = str(eboot)
        save_settings(exe_dir(), s)
        self.log(f"Game folder set to {eboot.parent}.")

    def save_full(self):
        s = load_settings(exe_dir())
        s["fullscreen"] = bool(self.full.get())
        save_settings(exe_dir(), s)

    def do_play(self):
        self.playb.configure(state="disabled")

        def run():
            play(exe_dir(), self.log)
            self.after(0, lambda: self.playb.configure(state="normal"))
        threading.Thread(target=run, daemon=True).start()

    def do_cards(self):
        def run():
            ok = download_cards(exe_dir(), bool(self.art.get()), self.log)
            s = load_settings(exe_dir())
            s["cards_ready"] = ok
            save_settings(exe_dir(), s)
            self.log("Card data ready." if ok else "Card download incomplete - run it again to resume.")
        threading.Thread(target=run, daemon=True).start()


def main():
    if sys.stdout is None or sys.stderr is None:     # windowed exe started without console/redirect
        f = open(exe_dir() / "launcher.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f
    for stream in (sys.stdout, sys.stderr):            # logs/pipes are UTF-8 whatever the PC's code page is
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) >= 3 and sys.argv[1] == "--serve":
        serve(sys.argv[2])
        return
    if len(sys.argv) >= 3 and sys.argv[1] == "--tool":
        tool(sys.argv[2], sys.argv[3:])
        return
    if len(sys.argv) >= 4 and sys.argv[1] == "--install":       # unattended: --install GAME_FOLDER INSTALL_FOLDER
        ok, msg, eboot = check_game(sys.argv[2])
        print(msg, flush=True)
        if not ok:
            sys.exit(1)
        res = {}
        install(sys.argv[3], eboot, True, False, False, lambda m: print(m, flush=True),
                lambda success, where: res.update(ok=success))
        sys.exit(0 if res.get("ok") else 1)
    if len(sys.argv) >= 2 and sys.argv[1] == "--play":            # no window: servers + game, then exit
        play(exe_dir(), lambda m: print(m, flush=True))
        return
    if len(sys.argv) >= 2 and sys.argv[1] == "--download-cards":  # unattended card data into this install
        art = "--no-art" not in sys.argv
        ok = download_cards(exe_dir(), art, lambda m: print(m, flush=True))
        s = load_settings(exe_dir()) or {}
        s["cards_ready"] = ok
        save_settings(exe_dir(), s)
        sys.exit(0 if ok else 1)
    Window().mainloop()


if __name__ == "__main__":
    main()
