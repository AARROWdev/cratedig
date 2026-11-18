"""Regression tests for review pass 1 (findings F1-F30)."""
import os
import subprocess
import sys
import time

import pytest

import cratedig as cd
import helpers as h


# ---------- no window needed

def test_f9_f13_natural_key_superscripts_and_accents():
    cd.natural_key("Area 51²")           # raised ValueError
    cd.natural_key("Track ① intro")
    names = ["Zaz", "Åsgeir", "abba", "Émile"]
    assert sorted(names, key=cd.natural_key) == ["abba", "Åsgeir", "Émile", "Zaz"]


def test_f1_ffmpeg_is_absolute():
    assert cd.FFMPEG is None or os.path.isabs(cd.FFMPEG)


def test_f6_wav_and_video_skip_mutagen(monkeypatch, tmp_path):
    calls = []
    import mutagen
    monkeypatch.setattr(mutagen, "File", lambda p: calls.append(p))
    for n in ("a.wav", "b.mpg", "c.mp4"):
        p = tmp_path / n
        p.write_bytes(b"")
        cd.probe_duration(str(p))
    assert calls == []


def test_f22_failed_probe_not_cached(monkeypatch, tmp_path):
    w = cd.DurationWorker()
    monkeypatch.setattr(cd, "probe_duration", lambda p: -1.0)
    key = (str(tmp_path / "x.mp3"), 1, 1)
    w.gen = 1
    w.run(1, [key])
    assert key not in cd.DurationWorker.cache


def test_f5_cache_hits_arrive_as_one_batch(monkeypatch):
    w = cd.DurationWorker()
    keys = [(f"k{i}.mp3", 1, 1) for i in range(5000)]
    for k in keys:
        cd.DurationWorker.cache[k] = 1.0
    got = []
    w.found.connect(lambda g, b: got.append(len(b)))
    w.gen = 1
    w.run(1, keys)
    assert got == [5000]


def test_f12_isdir_within_times_out():
    t = time.monotonic()
    assert cd.isdir_within(os.path.expanduser("~"), 2.0)
    assert not cd.isdir_within(r"Z:\definitely\not\here", 2.0)
    assert time.monotonic() - t < 4.5


def test_f11_encodable():
    assert cd.encodable("normal.wav")
    assert not cd.encodable("bad\udc80.wav")


def test_f16_hand_off_false_without_server():
    assert cd.hand_off(None) is False


@pytest.mark.window   # holds the real app mutex for a few seconds: not on a PC in use
def test_f2_second_claim_loses(qapp, monkeypatch):
    """The first launch owns the mutex; a racing second launch must not build a window."""
    code = ("import sys; sys.path.insert(0, %r); import cratedig as cd; from PySide6.QtCore import QCoreApplication;"
            "app = QCoreApplication([]); print(cd.claim_instance(app)") % cd.HERE
    first = subprocess.Popen([sys.executable, "-c", code + ", flush=True); import sys; sys.stdin.readline()"],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert first.stdout.readline().strip() == "True"   # waits for the first process to hold the mutex
    second = subprocess.run([sys.executable, "-c", code + ")"], capture_output=True, text=True, timeout=120)
    first.communicate("\n", timeout=60)
    assert second.stdout.strip().endswith("False")


# ---------- with the window (Sandbox, or CRATEDIG_OFFSCREEN=1)

@pytest.mark.window
def test_f4_filter_spaces_punctuation_accents(make_window, tmp_path):
    d = str(tmp_path / "f")
    os.makedirs(d)
    for n in ("Track 2.mp3", "café.wav", "x.mp3", "Track 20.mp3"):
        open(os.path.join(d, n), "wb").close()
    w = make_window(d)
    for text, want in (("Track 2", {"Track 2.mp3", "Track 20.mp3"}), (".mp3", {"Track 2.mp3", "Track 20.mp3", "x.mp3"}),
                       ("café", {"café.wav"}), ("CAFÉ", {"café.wav"})):
        w.filter.setText(text)
        h.pump(50)
        assert {e.name for e in w.view_entries()} == want, text


@pytest.mark.window
def test_f10_pre_1970_date_shows_blank(make_window, tmp_path):
    d = str(tmp_path / "old")
    os.makedirs(d)
    p = os.path.join(d, "old.mp3")
    open(p, "wb").close()
    os.utime(p, (-86400 * 400, -86400 * 400))
    w = make_window(d)
    m = w.model
    assert m.data(m.index(0, 4)) == ""


@pytest.mark.window
def test_f14_open_remote_clears_filter(window, media):
    d, truth = media
    target = sorted(n for n, v in truth.items() if v)[-1]
    window.filter.setText("zzz-nothing")
    h.pump(50)
    window.open_remote(os.path.join(d, target).upper())   # different case, same file
    h.wait_until(lambda: window.cur_path, 10, "playback starts")
    assert os.path.normcase(window.cur_path) == os.path.normcase(os.path.join(d, target))
    assert window.filter.text() == ""


@pytest.mark.window
def test_f7_length_sort_queue_matches_view(make_window, media, monkeypatch):
    d = media[0]
    cd.DurationWorker.cache.clear()
    w = make_window(d)
    w.list.sortByColumn(2, cd.Qt.AscendingOrder)
    first = next(e.path for e in w.view_entries() if e.media)
    w.navigate(d, record=False)       # lengths start over
    w.play_view(first)
    h.wait_until(lambda: h.lengths_done(w), 60, "lengths filled")
    h.pump(300)
    view = [e.path for e in w.view_entries() if e.media and cd.encodable(e.path)]
    assert w.queue == view
    assert [w.player.playlist[i]["filename"] for i in range(len(view))] == [os.path.normpath(p) for p in view] or \
        [os.path.normcase(x["filename"]) for x in w.player.playlist] == [os.path.normcase(p) for p in view]


@pytest.mark.window
def test_f17_saved_volume_zero_is_silent(make_window, media, isolated):
    from PySide6.QtCore import QSettings
    QSettings(isolated, QSettings.IniFormat).setValue("volume", 0)
    w = make_window(media[0])
    assert w.vol.value() == 0
    assert int(w.player.volume) == 0


@pytest.mark.window
def test_f27_backspace_at_root_keeps_forward_history(make_window, tmp_path):
    w = make_window(str(tmp_path))
    root = os.path.splitdrive(str(tmp_path))[0] + "\\"
    w.navigate(root)
    w.navigate(str(tmp_path))
    w.go_back()
    hist = list(w.history)
    w.go_up()
    assert w.history == hist and w.cwd == root


# ---------- pass 2

@pytest.mark.window   # holds the real app mutex for a moment
def test_p2_1_mutex_free_after_holder_exits(qapp):
    """A launch that lost the claim lets go of its handle, so it can claim once the old window has exited."""
    code = ("import sys; sys.path.insert(0, %r); import cratedig as cd; from PySide6.QtCore import QCoreApplication;"
            "app = QCoreApplication([]); print(cd.claim_instance(app), flush=True); sys.stdin.readline()") % cd.HERE
    first = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert first.stdout.readline().strip() == "True"
    assert cd.claim_instance(qapp) is False
    first.communicate("\n", timeout=60)
    assert cd.claim_instance(qapp) is True
    for hd in qapp.mutexes:
        import ctypes
        ctypes.WinDLL("kernel32").CloseHandle(ctypes.c_void_p(hd))
    qapp.mutexes = []


def test_p2_4_sort_tiebreak():
    assert cd.sort_key("é.mp3") != cd.sort_key("e.mp3")


@pytest.mark.window
def test_p2_4_filter_matches_nfd_names(make_window, tmp_path):
    import unicodedata
    d = str(tmp_path / "nfd")
    os.makedirs(d)
    open(os.path.join(d, unicodedata.normalize("NFD", "café.wav")), "wb").close()
    w = make_window(d)
    w.filter.setText(unicodedata.normalize("NFC", "café"))
    h.pump(50)
    assert len(w.view_entries()) == 1


@pytest.mark.window
def test_p2_2_unplayable_start_plays_nothing(make_window, tmp_path, media):
    d = str(tmp_path / "p")
    os.makedirs(d)
    import shutil
    shutil.copy(os.path.join(media[0], "tone wav.wav"), os.path.join(d, "a.wav"))
    open(os.path.join(d, "song.mid"), "wb").close()
    w = make_window(d)
    w.play_view(os.path.join(d, "song.mid"))
    h.pump(500)
    assert w.queue == [] and "Can't play" in w.statusBar().currentMessage()
