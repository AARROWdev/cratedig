"""Plan E: robustness (rows 20-24)."""
import os
import random
import shutil
import sys
import time

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest

import cratedig as cd
import helpers as h

pytestmark = pytest.mark.window

KEYS = [cd.Qt.Key_Down, cd.Qt.Key_Up, cd.Qt.Key_Return, cd.Qt.Key_Backspace, cd.Qt.Key_Space, cd.Qt.Key_W,
        cd.Qt.Key_V, cd.Qt.Key_Home, cd.Qt.Key_End, cd.Qt.Key_PageDown, cd.Qt.Key_Tab]


def monkey(w, root, steps, seed):
    """Random clicks and keys all over the window. Fails if one step takes 2 s or more."""
    rnd = random.Random(seed)
    worst = 0
    for i in range(steps):
        t = time.monotonic()
        r = rnd.random()
        if w.cwd and not os.path.normcase(w.cwd).startswith(os.path.normcase(root)):
            w.navigate(root)   # keep the monkey inside the test folder
        if r < 0.45:
            QTest.keyClick(w.list, rnd.choice(KEYS), cd.Qt.ShiftModifier if rnd.random() < 0.1 else cd.Qt.NoModifier)
        elif r < 0.7:
            vp = w.list.viewport()
            QTest.mouseClick(vp, cd.Qt.LeftButton, pos=QPoint(rnd.randrange(vp.width()), rnd.randrange(vp.height())))
        elif r < 0.8:
            wv = w.wave
            QTest.mouseClick(wv, cd.Qt.LeftButton, pos=QPoint(rnd.randrange(max(1, wv.width())), wv.height() // 2))
        elif r < 0.9:
            rnd.choice([w.btn_next, w.btn_prev, w.btn_play, w.btn_stop, w.btn_mode]).click()
        elif r < 0.95:
            w.list.sortByColumn(rnd.randrange(5), rnd.choice([cd.Qt.AscendingOrder, cd.Qt.DescendingOrder]))
        else:
            w.filter.setText(rnd.choice(["", "tone", "clip", "zzz", ""]))
        h.pump(5)
        worst = max(worst, time.monotonic() - t)
        assert worst < 2, f"step {i} took {worst:.1f}s"
    return worst


@pytest.mark.big
def test_monkey_4500_steps(make_window, media, tmp_path):
    """Row 20: 4,500 random steps during playback; no crash, the window never stalls 2 s."""
    root = str(tmp_path / "m")
    shutil.copytree(media[0], os.path.join(root, "crate"))
    os.makedirs(os.path.join(root, "empty folder"))
    w = make_window(root)
    w.navigate(os.path.join(root, "crate"))
    w.play_view(None)
    monkey(w, root, 4500, 1)
    if w.full_hidden is not None:
        w.toggle_full()


def test_monkey_short(make_window, media, tmp_path):
    root = str(tmp_path / "m")
    shutil.copytree(media[0], os.path.join(root, "crate"))
    w = make_window(os.path.join(root, "crate"))
    w.play_view(None)
    monkey(w, root, 300, 2)
    if w.full_hidden is not None:
        w.toggle_full()


def test_folder_deleted_while_shown_and_playing(make_window, media, tmp_path):
    """Row 21: the folder vanishes while it's shown and a file from it plays: no crash, clean refresh."""
    d = str(tmp_path / "gone")
    shutil.copytree(media[0], d)
    w = make_window(d)
    w.play_view(os.path.join(d, "tone flac.flac"))
    h.wait_until(lambda: w.cur_path, 20, "playing")
    h.wait_until(lambda: h.lengths_done(w), 60, "lengths filled")   # a probe holds its file open, so rmtree would fail
    w.stop()
    h.pump(300)
    shutil.rmtree(d)
    w.navigate(d, record=False)       # Refresh
    h.pump(100)
    assert "Not a folder" in w.statusBar().currentMessage()
    idx = w.list.currentIndex()
    if idx.isValid():
        w.activate(idx)               # opening a row whose file is gone
    w.play_pause()
    w.go_up()
    h.pump(500)
    assert w.cwd == os.path.normpath(str(tmp_path))


def test_folder_renamed_under_the_list(make_window, media, tmp_path):
    d = str(tmp_path / "before")
    shutil.copytree(media[0], d)
    w = make_window(d)
    h.wait_until(lambda: h.lengths_done(w), 120, "lengths")   # Windows can't rename a folder while a file in it is open
    os.rename(d, str(tmp_path / "after"))
    w.play_view(os.path.join(d, "tone wav.wav"))   # paths that no longer exist
    h.pump(2000)
    w.go_up()
    assert "after" in h.names(w)


def test_corrupt_settings_still_open(make_window, isolated, media):
    """Row 22: garbage geometry/splitter/header state and a deleted last folder: the app still opens."""
    from PySide6.QtCore import QSettings
    s = QSettings(isolated, QSettings.IniFormat)
    for k in ("geometry", "hsplit", "vsplit", "header5"):
        s.setValue(k, b"\x00garbage\xff" * 10)
    s.setValue("last_dir", r"C:\this\folder\was\deleted")
    s.setValue("volume", "loud")
    s.setValue("skin", "No Such Skin")
    s.setValue("wave_mode", "No Such Mode")
    s.sync()
    w = make_window()
    assert w.cwd and os.path.isdir(w.cwd)


@pytest.mark.parametrize("size", [(320, 240), (3800, 2100)])
def test_tiny_and_huge_window(make_window, media, size):
    """Row 23: tiny and huge window sizes, while playing."""
    w = make_window(media[0], size=size)
    w.play_view(os.path.join(media[0], "tone wav.wav"))
    h.wait_until(lambda: w.cur_path, 20, "playing")
    for _ in range(6):
        w.wave.cycle()
        w.grab()


def test_keyboard_only(make_window, media, tmp_path):
    """Row 23: everything reachable from the keyboard: arrows, Enter into a folder and onto a file,
    Backspace up, Space pause, Ctrl+F filter, Esc."""
    root = str(tmp_path / "k")
    shutil.copytree(media[0], os.path.join(root, "crate"))
    w = make_window(root)
    w.list.setFocus()
    QTest.keyClick(w.list, cd.Qt.Key_Return)                  # into "crate"
    assert os.path.basename(w.cwd) == "crate"
    w.list.sortByColumn(0, cd.Qt.AscendingOrder)
    target = next(i for i, e in enumerate(w.view_entries()) if e.name == "tone wav.wav")
    w.list.setCurrentIndex(w.proxy.index(target, 0))
    QTest.keyClick(w.list, cd.Qt.Key_Return)
    h.wait_until(lambda: w.cur_path and w.cur_path.endswith("tone wav.wav"), 20, "Enter plays")
    QTest.keyClick(w.list, cd.Qt.Key_Space)
    h.wait_until(lambda: w.player.pause, 5, "Space pauses")
    QTest.keyClick(w.list, cd.Qt.Key_Backspace)
    assert os.path.normcase(w.cwd) == os.path.normcase(root)
    QTest.keyClick(w, cd.Qt.Key_F, cd.Qt.ControlModifier)
    h.pump(50)
    assert w.filter.hasFocus()
    QTest.keyClicks(w.filter, "cr")
    QTest.keyClick(w.filter, cd.Qt.Key_Escape)
    assert w.filter.text() == ""


def test_error_log(tmp_path, monkeypatch):
    """Row 24: an unhandled exception is written to error.log and doesn't end the app."""
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    cd.install_error_log()
    try:
        raise RuntimeError("forced test error")
    except RuntimeError:
        sys.excepthook(*sys.exc_info())
    log = os.path.join(os.environ["LOCALAPPDATA"], "Cratedig", "error.log")
    with open(log, encoding="utf-8") as f:
        assert "forced test error" in f.read()
