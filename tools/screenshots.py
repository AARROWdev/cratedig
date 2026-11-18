r"""Makes the README screenshots (docs\*.png) from a generated demo crate, offscreen: no window opens,
no real settings or cache are touched. Run: .venv-test\Scripts\python tools\screenshots.py"""
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TMP = tempfile.mkdtemp(prefix="cratedig-shots-")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_FONTDIR"] = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
os.environ["LOCALAPPDATA"] = os.path.join(TMP, "localappdata")
os.environ["PATH"] = os.path.join(ROOT, "build", "dist", "Cratedig", "lib") + os.pathsep + os.environ["PATH"]
sys.path.insert(0, ROOT)

from PySide6.QtCore import QEventLoop, QSettings, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import cratedig as cd  # noqa: E402
import themes  # noqa: E402

# The demo crate is shown on a temporary drive letter, so no real path or folder name appears in the shots.
DRIVE = next(f"{c}:" for c in "XYZWVUTS" if not os.path.exists(f"{c}:\\"))
CRATE = os.path.join(DRIVE + "\\", "Crates", "Friday set")
# (name, seconds, bpm, root Hz): made-up tracks; the audio is synthesized so the waveforms look like music
TRACKS = [("01 Night Drive.wav", 214, 174, 55), ("02 Glass Harbour.flac", 247, 172, 49),
          ("03 Low Orbit (VIP).wav", 198, 174, 41), ("04 Paper Lanterns.mp3", 263, 170, 58),
          ("05 Tidewater.flac", 231, 174, 46), ("06 Static Bloom.wav", 189, 175, 52),
          ("07 Afterglow Dub.mp3", 276, 170, 44), ("08 Northern Line.wav", 205, 174, 62),
          ("09 Slow Burn.aiff", 238, 172, 39), ("10 Halcyon Rooftops.flac", 252, 174, 55),
          ("11 Concrete Garden.wav", 221, 176, 47), ("12 Last Train Home.mp3", 290, 170, 50)]


def make_track(path, sec, bpm, f0):
    beat = 60 / bpm
    # intro, drop, breakdown, second drop, outro: the envelope gives the waveform its shape
    env = (f"(0.35+0.65*between(t,{sec * .18},{sec * .45})+0.65*between(t,{sec * .6},{sec * .88}))"
           f"*(1-0.75*between(t,{sec * .45},{sec * .6}))*min(1,t/4)*min(1,({sec}-t)/6)")
    kick = f"0.9*sin(2*PI*{f0}*t*(1+2*exp(-30*mod(t,{beat}))))*exp(-9*mod(t,{beat}))"
    bass = f"0.35*sin(2*PI*{f0 * 2}*t)*(0.6+0.4*sin(2*PI*t/{beat * 4}))"
    hats = f"0.12*(random(0)-0.5)*exp(-60*mod(t+{beat / 2},{beat / 2}))"
    pad = f"0.15*sin(2*PI*{f0 * 6}*t)*sin(2*PI*{f0 * 6.02}*t)"
    expr = f"({env})*({kick}+{bass}+{hats})+{pad}*(0.5+0.5*between(t,{sec * .45},{sec * .6}))"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"aevalsrc='{expr}|{expr}':s=22050:d={sec}", "-ar", "44100", path], check=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main():
    os.makedirs(os.path.join(TMP, "drive"))
    subprocess.run(["subst", DRIVE, os.path.join(TMP, "drive")], check=True)
    try:
        shots()
    finally:
        subprocess.run(["subst", DRIVE, "/d"])


def shots():
    os.makedirs(CRATE)
    for sub in ("Edits", "Stems"):
        os.makedirs(os.path.join(CRATE, sub))
    for name, sec, bpm, f0 in TRACKS:
        make_track(os.path.join(CRATE, name), sec, bpm, f0)
    ini = os.path.join(TMP, "cratedig.ini")
    cd.QSettings = lambda *a, **k: QSettings(ini, QSettings.IniFormat)
    real = cd.mpv.MPV
    cd.mpv.MPV = lambda *a, **k: real(*a, ao="null", vo="null", **k)

    app = QApplication([])
    app.setApplicationName(cd.APP)
    from PySide6.QtGui import QFont
    app.setFont(QFont("Segoe UI", 9))   # what Windows gives the real window; offscreen would pick any font
    out = os.path.join(ROOT, "docs")
    done = []
    for skin, mode, track, at, fname in (("Blue", "Classic", 2, 0.30, "main.png"),
                                         ("Ember", "Spectrogram", 6, 0.55, "spectrogram.png"),
                                         ("Neon", "Bars + Spectrum", 9, 0.25, "bars.png")):
        themes.apply(app, themes.get(skin))
        w = cd.Window(CRATE)
        w.set_skin(skin)
        w.wave.set_mode(mode)
        w.resize(1280, 760)
        w.show()
        w.hsplit.setSizes([250, 1030])
        w.tree.setRootIndex(w.fs.index(DRIVE + "\\"))   # only the demo drive in the folder tree
        w.tree.expandAll()
        w.list.header().resizeSection(0, 330)
        pump(1500)                     # lengths fill in
        path = os.path.join(CRATE, TRACKS[track][0])
        w.play_view(path)
        cache = os.path.join(os.environ["LOCALAPPDATA"], "Cratedig", "cache")
        t0 = time.monotonic()
        while time.monotonic() - t0 < 60:
            pump(200)
            ana = w.wave.analysis if hasattr(w.wave, "analysis") else None
            if os.path.isdir(cache) and any(f.endswith(".npz") and os.path.getsize(os.path.join(cache, f)) for f in os.listdir(cache)) \
                    and (ana is None or getattr(ana, "done", True)):
                break
        pump(1000)
        w.seek_to(TRACKS[track][1] * at)
        pump(2500)
        row = next(r for r in range(w.proxy.rowCount()) if w.entry_at(w.proxy.index(r, 0)).path == path)
        w.list.setCurrentIndex(w.proxy.index(row, 0))
        pump(300)
        w.grab().save(os.path.join(out, fname))
        print("saved", fname)
        done.append(fname)
        w.close()
        pump(300)


if __name__ == "__main__":
    main()
