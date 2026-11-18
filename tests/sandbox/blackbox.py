"""Black-box tests on the INSTALLED Cratedig.exe (run by inside.ps1, inside Windows Sandbox only).
    python blackbox.py all <Cratedig.exe>        single instance, DPI, title; results to C:\\out\\blackbox-results.txt
    python blackbox.py portable <Cratedig.exe>   the unzipped portable build opens, plays and closes
"""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes as w

import psutil

OUT = r"C:\out\blackbox-results.txt"
MEDIA = r"C:\bbmedia"
u32 = ctypes.windll.user32


def check(name, ok):
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(f"{'PASS' if ok else 'FAIL'}  {name}\n")
    return ok


def procs():
    return [p for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower() == "cratedig.exe"]


def kill_all():
    for p in procs():
        p.kill()
    psutil.wait_procs(procs(), timeout=10)


def titles(pid_set):
    out = []

    @ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    def cb(hwnd, _):
        pid = w.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pid_set and u32.IsWindowVisible(hwnd):
            n = u32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(hwnd, buf, n + 1)
            if buf.value:
                out.append(buf.value)
        return True
    u32.EnumWindows(cb, 0)
    return out


def wait(fn, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.25)
    return False


def make_media(exe):
    ff = os.path.join(os.path.dirname(exe), "lib", "ffmpeg.exe")
    os.makedirs(MEDIA, exist_ok=True)
    for i in range(1, 7):
        p = os.path.join(MEDIA, f"song {i}.mp3")
        if not os.path.exists(p):
            subprocess.run([ff, "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency={200 * i}:duration=60", p],
                           check=True)


def run_all(exe):
    make_media(exe)
    kill_all()

    first = subprocess.Popen([exe, os.path.join(MEDIA, "song 1.mp3")])
    up = wait(lambda: any("song 1.mp3" in t for t in titles({first.pid})), 30)
    check("BB opening a file plays it (title shows the song)", up)

    others = [subprocess.Popen([exe, os.path.join(MEDIA, f"song {i}.mp3")]) for i in range(2, 7)]
    exited = wait(lambda: all(p.poll() is not None for p in others), 20)
    check("BB 5 rapid launches all hand off and exit", exited and all(p.returncode == 0 for p in others))
    check("BB still exactly one Cratedig running", len(procs()) == 1)
    # the 5 launches race each other, so any of them may arrive last; a launch after they're done must win
    last = subprocess.Popen([exe, os.path.join(MEDIA, "song 4.mp3")])
    last.wait(20)
    check("BB the open window plays the file handed to it",
          wait(lambda: any("song 4.mp3" in t for t in titles({first.pid})), 20))
    kill_all()

    p = subprocess.Popen([exe])
    check("BB plain launch shows 'Cratedig 1.' in the title",
          wait(lambda: any(t.startswith("Cratedig 1.") for t in titles({p.pid})), 30))
    kill_all()

    for scale in ("1", "1.5", "2"):
        env = dict(os.environ, QT_SCALE_FACTOR=scale)
        p = subprocess.Popen([exe, os.path.join(MEDIA, "song 2.mp3")], env=env)
        ok = wait(lambda: any("song 2.mp3" in t for t in titles({p.pid})), 30) and p.poll() is None
        time.sleep(3)
        check(f"BB high DPI {int(float(scale) * 100)}%: opens, plays, stays up", ok and p.poll() is None)
        kill_all()
    return 0


def run_portable(exe):
    make_media(exe)
    kill_all()
    p = subprocess.Popen([exe, os.path.join(MEDIA, "song 3.mp3")])
    ok = wait(lambda: any("song 3.mp3" in t for t in titles({p.pid})), 30)
    time.sleep(3)
    ok = ok and p.poll() is None
    kill_all()
    return 0 if ok else 1


if __name__ == "__main__":
    if os.environ.get("USERNAME", "").upper() != "WDAGUTILITYACCOUNT":
        sys.exit("Sandbox only")
    cmd, exe = sys.argv[1], sys.argv[2]
    sys.exit(run_all(exe) if cmd == "all" else run_portable(exe))
