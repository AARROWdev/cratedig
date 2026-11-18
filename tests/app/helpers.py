"""Shared helpers for the Cratedig tests: make test media with ffmpeg, drive the window, wait on mpv."""
import hashlib
import os
import subprocess
import time

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

IN_SANDBOX = os.environ.get("USERNAME", "").upper() == "WDAGUTILITYACCOUNT"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def lp(p):
    """Extended-length form so tests can create names Windows normally rewrites, and paths over 260."""
    if p.startswith("\\\\?\\"):
        return p
    return "\\\\?\\" + os.path.abspath(p)


def pump(ms=0):
    """Run the Qt event loop for ms milliseconds."""
    app = QApplication.instance()
    if ms <= 0:
        app.processEvents()
        return
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_until(fn, timeout, what):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if fn():
                return
        except Exception:
            pass
        pump(25)
    raise AssertionError(f"timed out after {timeout}s waiting for: {what}")


def ffmpeg(*args):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], capture_output=True,
                       text=True, creationflags=NO_WINDOW)
    assert r.returncode == 0, r.stderr


# ext -> (seconds, ffmpeg args before the output path). Every length is different, so sorting by Length is checkable.
AUDIO = {
    "wav": (5, ["-f", "lavfi", "-i", "sine=frequency=220:duration=5"]),
    "mp3": (7, ["-f", "lavfi", "-i", "sine=frequency=330:duration=7"]),
    "flac": (9, ["-f", "lavfi", "-i", "sine=frequency=440:duration=9"]),
    "aiff": (11, ["-f", "lavfi", "-i", "sine=frequency=550:duration=11"]),
    "m4a": (13, ["-f", "lavfi", "-i", "sine=frequency=660:duration=13", "-c:a", "aac"]),
    "ogg": (15, ["-f", "lavfi", "-i", "sine=frequency=770:duration=15", "-c:a", "libvorbis"]),
    "opus": (17, ["-f", "lavfi", "-i", "sine=frequency=880:duration=17", "-c:a", "libopus"]),
    "mka": (19, ["-f", "lavfi", "-i", "sine=frequency=990:duration=19"]),
    "wma": (21, ["-f", "lavfi", "-i", "sine=frequency=1100:duration=21", "-c:a", "wmav2"]),
}
VIDEO = {
    "mp4": (6, "640x360"),
    "mkv": (8, "640x360"),
    "mov": (10, "640x360"),
    "webm": (12, "320x180"),
    "avi": (14, "320x240"),
}


def make_media(d):
    """One file per audio/video type, plus portrait, no-audio, corrupt, empty and non-media files.
    Returns {filename: seconds or None}."""
    os.makedirs(d, exist_ok=True)
    truth = {}
    for ext, (sec, args) in AUDIO.items():
        ffmpeg(*args, os.path.join(d, f"tone {ext}.{ext}"))
        truth[f"tone {ext}.{ext}"] = sec
    for ext, (sec, size) in VIDEO.items():
        venc = ["-c:v", "libvpx-vp9", "-b:v", "200k"] if ext == "webm" else []
        aenc = ["-c:a", "libopus"] if ext == "webm" else []
        ffmpeg("-f", "lavfi", "-i", f"testsrc=duration={sec}:size={size}:rate=15",
               "-f", "lavfi", "-i", f"sine=duration={sec}", "-shortest", *venc, *aenc,
               os.path.join(d, f"clip {ext}.{ext}"))
        truth[f"clip {ext}.{ext}"] = sec
    ffmpeg("-f", "lavfi", "-i", "testsrc=duration=4:size=180x320:rate=15", "-f", "lavfi", "-i", "sine=duration=4",
           "-shortest", os.path.join(d, "portrait.mp4"))
    truth["portrait.mp4"] = 4
    ffmpeg("-f", "lavfi", "-i", "testsrc=duration=3:size=320x180:rate=15", os.path.join(d, "silent video.mp4"))
    truth["silent video.mp4"] = 3
    with open(os.path.join(d, "corrupt.mp3"), "wb") as f:
        f.write(os.urandom(50_000))
    truth["corrupt.mp3"] = None
    open(os.path.join(d, "empty.wav"), "wb").close()
    truth["empty.wav"] = None
    with open(os.path.join(d, "notes.txt"), "w") as f:
        f.write("not media")
    truth["notes.txt"] = None
    return truth


def tree_hash(root):
    """Hash of every file's bytes under root (to prove Cratedig never writes to media)."""
    out = {}
    for dp, _, files in os.walk(root):
        for n in files:
            p = os.path.join(dp, n)
            with open(lp(p), "rb") as f:
                out[os.path.relpath(p, root)] = hashlib.sha256(f.read()).hexdigest()
    return out


def names(window):
    """File names in the list, in view order."""
    return [e.name for e in window.view_entries()]


def lengths(window):
    m = window.model
    return {e.name: m.data(m.index(i, 2)) for i, e in enumerate(m.entries)}


def lengths_done(window):
    return all(e.dur is not None for e in window.model.entries if e.media)
