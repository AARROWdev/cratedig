"""Test setup. The whole suite runs inside Windows Sandbox (tests/sandbox/run-tests.ps1). Off the Sandbox, only
the tests that don't open a window run, and settings, cache and log all go to temp folders, never the real ones."""
import gc
import os
import shutil
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))
# ffmpeg for the app and for making test media: the bundled one from the build
for d in (os.path.join(ROOT, "build", "dist", "Cratedig", "lib"), r"C:\Program Files\Cratedig\lib"):
    if os.path.isfile(os.path.join(d, "ffmpeg.exe")):
        os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
        break

# Off the Sandbox, CRATEDIG_OFFSCREEN=1 runs the window tests invisibly (no window on the PC owner's screen,
# no video output) for a quick check while developing. The real run is the Sandbox one.
OFFSCREEN = os.environ.get("CRATEDIG_OFFSCREEN") == "1"
if OFFSCREEN:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import cratedig as cd  # noqa: E402
import helpers as h  # noqa: E402

_RealMPV = cd.mpv.MPV


def pytest_configure(config):
    config.addinivalue_line("markers", "window: opens the real window and plays media: Sandbox only")
    config.addinivalue_line("markers", "big: tens of thousands of files: Sandbox only")


def pytest_collection_modifyitems(config, items):
    if h.IN_SANDBOX or OFFSCREEN:
        return
    skip = pytest.mark.skip(reason="runs only inside Windows Sandbox (tests/sandbox/run-tests.ps1)")
    for it in items:
        if "window" in it.keywords or "big" in it.keywords:
            it.add_marker(skip)


@pytest.fixture(scope="session", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setApplicationName(cd.APP)
    yield app


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Settings in an .ini, cache + error.log under tmp, a private single-instance name, silent audio."""
    ini = str(tmp_path / "cratedig.ini")
    monkeypatch.setattr(cd, "QSettings", lambda *a, **k: QSettings(ini, QSettings.IniFormat))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setattr(cd, "SERVER", f"Cratedig-test-{os.getpid()}-{id(tmp_path)}")
    extra = {"ao": "null"}
    if OFFSCREEN:
        extra["vo"] = "null"
    monkeypatch.setattr(cd.mpv, "MPV", lambda *a, **k: _RealMPV(*a, **extra, **k))
    return ini


@pytest.fixture(scope="session")
def media(tmp_path_factory):
    """The generated media folder and its ground truth {name: seconds or None}."""
    d = str(tmp_path_factory.mktemp("media") / "crate")
    truth = h.make_media(d)
    before = h.tree_hash(d)
    yield d, truth
    assert h.tree_hash(d) == before, "Cratedig changed a media file"   # plan row 19


@pytest.fixture
def make_window(qapp):
    made = []

    def make(start=None, size=(1300, 800)):
        w = cd.Window(start)
        w.resize(*size)
        w.show()
        h.pump(100)
        made.append(w)
        return w

    yield make
    for w in made:
        w.close()
        w.deleteLater()
    h.pump(100)
    gc.collect()


@pytest.fixture
def window(make_window, media):
    return make_window(media[0])


def copy_media(media, dest):
    shutil.copytree(media[0], dest)
    return dest
