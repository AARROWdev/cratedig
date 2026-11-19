"""Plan B: browsing (rows 6-10)."""
import os
import subprocess
import time

import pytest

import cratedig as cd
import helpers as h

pytestmark = pytest.mark.window


def test_listing_matches_folder(window, media):
    """Row 6: every name, size and date matches the folder."""
    d = media[0]
    want = {de.name: de for de in os.scandir(d) if de.is_dir() or os.path.splitext(de.name)[1][1:].lower() in cd.MEDIA}
    assert "notes.txt" not in want and any(not n.endswith(".txt") for n in want)   # 1.2: only playable files are listed
    m = window.model
    assert {e.name for e in m.entries} == set(want)
    for i, e in enumerate(m.entries):
        st = want[e.name].stat()
        assert m.data(m.index(i, 3)) == ("" if e.is_dir else cd.human_size(st.st_size))
        assert m.data(m.index(i, 4)) == time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))


def test_folders_first_both_directions(make_window, tmp_path):
    d = str(tmp_path / "f")
    for n in ("b dir", "a dir", "z dir"):
        os.makedirs(os.path.join(d, n))
    for n in ("a.wav", "c.txt", "y.mp3"):
        open(os.path.join(d, n), "wb").close()
    w = make_window(d)
    for col in range(5):
        for order in (cd.Qt.AscendingOrder, cd.Qt.DescendingOrder):
            w.list.sortByColumn(col, order)
            dirs = [e.is_dir for e in w.view_entries()]
            assert dirs == sorted(dirs, reverse=True), (col, order)


def test_sort_every_column_and_natural(make_window, tmp_path):
    """Row 7: name (natural), type, size and date sort correctly."""
    d = str(tmp_path / "s")
    os.makedirs(d)
    spec = [("Track 10.wav", 300, 1000), ("Track 2.mp3", 100, 3000), ("track 1.flac", 200, 2000)]
    for n, size, mt in spec:
        p = os.path.join(d, n)
        with open(p, "wb") as f:
            f.write(b"x" * size)
        os.utime(p, (1_700_000_000 + mt, 1_700_000_000 + mt))
    w = make_window(d)
    w.list.sortByColumn(0, cd.Qt.AscendingOrder)
    assert h.names(w) == ["track 1.flac", "Track 2.mp3", "Track 10.wav"]
    w.list.sortByColumn(1, cd.Qt.AscendingOrder)
    assert h.names(w) == ["track 1.flac", "Track 2.mp3", "Track 10.wav"]   # flac < mp3 < wav
    w.list.sortByColumn(3, cd.Qt.AscendingOrder)
    assert h.names(w) == ["Track 2.mp3", "track 1.flac", "Track 10.wav"]
    w.list.sortByColumn(4, cd.Qt.DescendingOrder)
    assert h.names(w) == ["Track 2.mp3", "track 1.flac", "Track 10.wav"]


def test_sort_by_length(window):
    h.wait_until(lambda: h.lengths_done(window), 120, "lengths")
    window.list.sortByColumn(2, cd.Qt.AscendingOrder)
    durs = [e.dur or 0 for e in window.view_entries() if not e.is_dir]
    assert durs == sorted(durs)


def test_filter_and_escape(window):
    """Row 8: filter as you type, status counts, Esc clears."""
    window.filter.setText("TONE")
    h.pump(50)
    shown = h.names(window)
    assert shown and all("tone" in n for n in shown)
    assert window.statusBar().currentMessage().startswith(f"{len(shown)} items")
    window.filter.setFocus()
    from PySide6.QtTest import QTest
    QTest.keyClick(window.filter, cd.Qt.Key_Escape)
    h.pump(50)
    assert window.filter.text() == ""
    assert len(h.names(window)) == len(window.model.entries)


def test_unicode_and_odd_names(make_window, tmp_path):
    """Row 9: unicode, emoji, RTL and symbol names list and sort without trouble."""
    d = str(tmp_path / "u")
    os.makedirs(d)
    odd = ["日本語.wav", "عربي.mp3", "emoji 🎧.flac", "combining é.ogg", "100% & ; ' ok.wav", "CON_.wav"]
    for n in odd:
        open(os.path.join(d, n), "wb").close()
    w = make_window(d)
    assert sorted(h.names(w)) == sorted(odd)


def test_long_path(make_window, tmp_path):
    """Row 9: a folder deeper than 260 characters: listed, or a clean message. Never a crash."""
    base = str(tmp_path / "long")
    p = base
    while len(p) < 300:
        p = os.path.join(p, "x" * 40)
    os.makedirs(h.lp(p))
    with open(h.lp(os.path.join(p, "deep.wav")), "wb"):
        pass
    w = make_window(base)
    w.navigate(p)
    h.pump(100)
    assert w.cwd == os.path.normpath(p) and h.names(w) == ["deep.wav"] or w.statusBar().currentMessage()


@pytest.mark.skipif(not h.IN_SANDBOX, reason="changes folder permissions: Sandbox only")
def test_access_denied_folder(make_window, tmp_path):
    """Row 9: a folder the user can't read: a message, no crash, the app keeps working."""
    d = str(tmp_path / "denied")
    os.makedirs(d)
    subprocess.run(["icacls", d, "/deny", f"{os.environ['USERNAME']}:(RD)"], capture_output=True, check=True)
    try:
        w = make_window(str(tmp_path))
        w.navigate(d)
        h.pump(100)
        assert w.model.entries == []
        assert w.statusBar().currentMessage()
        w.navigate(str(tmp_path))
        assert "denied" in h.names(w)
    finally:
        subprocess.run(["icacls", d, "/remove:d", os.environ["USERNAME"]], capture_output=True)


@pytest.mark.big
def test_20000_files_no_freeze(make_window, tmp_path, monkeypatch):
    """Row 9: a folder with 20,000 files opens in under 2 s."""
    # 20,000 empty .mp3s: first visit probes like real ffmpeg (~50 ms each, lengths trickle in); the revisit below
    # covers the cached path, where every length is already known and arrives straight after the open
    monkeypatch.setattr(cd, "probe_duration", lambda p: time.sleep(0.05) or -1)
    monkeypatch.setattr(cd.DurationWorker, "cache", {})
    d = str(tmp_path / "big")
    os.makedirs(d)
    for i in range(20000):
        open(os.path.join(d, f"{i:05d}.mp3"), "wb").close()
    w = make_window(str(tmp_path))
    t = time.monotonic()
    w.navigate(d)
    h.pump(0)
    assert time.monotonic() - t < 2
    assert len(w.model.entries) == 20000
    # cached revisit: opens in time, and the 20,000 known lengths never freeze the window for long
    for e in w.model.entries:
        cd.DurationWorker.cache[(e.path, e.size, e.mtime)] = float((20000 - int(e.name[:5])) % 997)   # varied lengths
    w.navigate(str(tmp_path))
    h.pump(0)
    done = []
    w.model.durs.finished.connect(lambda g: g == w.model.durs.gen and done.append(g))   # only the revisit's worker
    t = time.monotonic()
    w.navigate(d)
    h.pump(0)
    assert time.monotonic() - t < 2
    worst, end = 0.0, time.monotonic() + 30
    while (not done or w.model.dur_timer.isActive()) and time.monotonic() < end:   # finished, and applied
        s = time.monotonic()
        h.pump(0)
        worst = max(worst, time.monotonic() - s)
    assert done, "lengths never finished"
    assert all(e.dur == float((20000 - int(e.name[:5])) % 997) for e in w.model.entries)
    assert worst < 1.0, worst   # the one length update, after the open: short, the window keeps responding
    # sorted by Length the same update re-sorts all 20,000 rows: slower, but never a hang (spec: 5 s)
    w.navigate(str(tmp_path))
    h.pump(0)
    w.list.sortByColumn(2, cd.Qt.AscendingOrder)
    done.clear()
    s = time.monotonic()
    w.navigate(d)
    h.pump(0)   # a cached folder's lengths (and the full re-sort) land in this first pass: time it
    worst, end = time.monotonic() - s, time.monotonic() + 30
    while (not done or w.model.dur_timer.isActive()) and time.monotonic() < end:
        s = time.monotonic()
        h.pump(0)
        worst = max(worst, time.monotonic() - s)
    assert done and worst < 5, worst
    assert all(e.dur == float((20000 - int(e.name[:5])) % 997) for e in w.model.entries)
    view = w.view_entries()
    durs = [e.dur for e in view]
    assert durs == sorted(durs) and [e.name for e in view] != sorted(e.name for e in view)   # really in Length order
    w.close()   # stops the length worker (closeEvent bumps its generation)


def test_back_forward_up_address(make_window, tmp_path):
    """Row 10: back, forward, up, the address bar, a bad path and a drive root."""
    a = str(tmp_path / "a")
    b = os.path.join(a, "b")
    os.makedirs(b)
    w = make_window(a)
    w.navigate(b)
    w.go_back()
    assert w.cwd == os.path.normpath(a)
    w.go_fwd()
    assert w.cwd == os.path.normpath(b)
    w.go_up()
    assert w.cwd == os.path.normpath(a)
    assert w.entry_at(w.list.currentIndex()).name == "b"
    w.addr.setText(b)
    w.addr.returnPressed.emit()
    assert w.cwd == os.path.normpath(b)
    w.addr.setText(r"Q:\no\such\folder")
    w.addr.returnPressed.emit()
    assert w.cwd == os.path.normpath(b) and "Not a folder" in w.statusBar().currentMessage()
    w.navigate("C:")
    assert w.cwd == "C:\\"
    w.go_up()
    assert w.cwd == "C:\\"
