"""Plan D: playback (rows 14-19)."""
import os
import shutil

import pytest

import cratedig as cd
import helpers as h
from waveform import MODES

pytestmark = pytest.mark.window


def playing(w):
    return w.cur_path


def wait_playing(w, path, timeout=20):
    h.wait_until(lambda: w.cur_path and os.path.normcase(w.cur_path) == os.path.normcase(path), timeout,
                 f"playing {os.path.basename(path)}")
    h.wait_until(lambda: (w.player.time_pos or 0) > 0.2, timeout, "time advancing")


def audio_dir(media, tmp_path, names):
    d = str(tmp_path / "q")
    os.makedirs(d)
    for n in names:
        shutil.copy(os.path.join(media[0], n), d)
    return d


def test_plays_view_in_sort_order(make_window, media, tmp_path):
    """Row 14: double-click queues the whole view from there, in the current sort order."""
    d = audio_dir(media, tmp_path, ["tone wav.wav", "tone mp3.mp3", "tone flac.flac", "notes.txt"])
    w = make_window(d)
    w.list.sortByColumn(0, cd.Qt.DescendingOrder)
    order = [e.path for e in w.view_entries() if e.media]
    assert [os.path.basename(p) for p in order] == ["tone wav.wav", "tone mp3.mp3", "tone flac.flac"]
    w.play_view(order[1])
    wait_playing(w, order[1])
    assert w.queue == order
    w.next()
    wait_playing(w, order[2])
    w.prev()
    wait_playing(w, order[1])


def test_seek_volume_pause_stop(make_window, media, tmp_path):
    d = audio_dir(media, tmp_path, ["tone opus.opus"])
    w = make_window(d)
    p = os.path.join(d, "tone opus.opus")
    w.play_view(p)
    wait_playing(w, p)
    w.seek_to(10)
    h.wait_until(lambda: (w.player.time_pos or 0) >= 9.5, 10, "seek")
    w.vol.setValue(35)
    assert w.player.volume == 35
    w.play_pause()
    h.wait_until(lambda: w.player.pause, 5, "paused")
    t = w.player.time_pos
    h.pump(500)
    assert abs(w.player.time_pos - t) < 0.05
    w.play_pause()
    h.wait_until(lambda: not w.player.pause, 5, "resumed")
    w.stop()
    h.wait_until(lambda: w.player.idle_active, 5, "stopped")
    h.pump(400)
    assert w.cur_path is None and w.now.text() == "Nothing playing"


def test_corrupt_file_is_skipped(make_window, media, tmp_path):
    """Row 15: a corrupt file in the queue is skipped, the next one plays, no crash."""
    d = audio_dir(media, tmp_path, ["corrupt.mp3", "empty.wav", "tone wav.wav"])
    w = make_window(d)
    w.list.sortByColumn(0, cd.Qt.AscendingOrder)
    w.play_view(os.path.join(d, "corrupt.mp3"))
    wait_playing(w, os.path.join(d, "tone wav.wav"), timeout=30)


def test_end_of_queue_goes_idle(make_window, media, tmp_path):
    d = audio_dir(media, tmp_path, ["tone wav.wav"])
    w = make_window(d)
    w.play_view(None)
    h.wait_until(lambda: w.cur_path, 10, "start")
    w.seek_to(4.5)
    h.wait_until(lambda: w.player.idle_active and w.cur_path is None, 20, "idle after the last track")


def launch_hand_off(path):
    """A second launch: a separate process sends its file to this test's window, like Explorer would."""
    import subprocess
    import sys
    code = "import sys; sys.path.insert(0, %r); import cratedig as cd; cd.SERVER = %r; print(cd.hand_off(%r))" % (
        cd.HERE, cd.SERVER, path)
    return subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)


def test_single_instance_hand_off(make_window, media, tmp_path):
    """Row 16: a second launch hands its file to the open window, which plays it."""
    d = audio_dir(media, tmp_path, ["tone wav.wav", "tone mp3.mp3"])
    w = make_window(d)
    w.server = cd.serve(w)
    target = os.path.join(d, "tone mp3.mp3")
    p = launch_hand_off(target)
    wait_playing(w, target, 40)
    h.wait_until(lambda: p.poll() is not None, 30, "hand-off returns")   # pump: the window acks from its event loop
    assert p.stdout.read().strip() == "True"
    ps = [launch_hand_off(os.path.join(d, "tone wav.wav")) for _ in range(5)]   # five rapid launches
    h.wait_until(lambda: all(x.poll() is not None for x in ps), 60, "all hand-offs return")
    assert [x.stdout.read().strip() for x in ps] == ["True"] * 5
    wait_playing(w, os.path.join(d, "tone wav.wav"))
    w.server.close()


def test_hand_off_without_a_window_returns_false():
    assert cd.hand_off(None) is False


def video_layout(w):
    return w.vsplit.orientation()


def test_video_layout_landscape_and_portrait(make_window, media, tmp_path):
    """Row 17: landscape plays above the list, portrait in a column on the right."""
    d = audio_dir(media, tmp_path, ["clip mp4.mp4", "portrait.mp4"])
    w = make_window(d, size=(1400, 900))
    land, port = os.path.join(d, "clip mp4.mp4"), os.path.join(d, "portrait.mp4")
    w.play_view(land)
    wait_playing(w, land)
    h.wait_until(lambda: w.vdims_path == land, 10, "landscape dims")
    assert w.btn_video.isChecked() and w.video.isVisible()
    assert video_layout(w) == cd.Qt.Vertical and w.vsplit.widget(0) is w.video
    w.play_view(port)
    wait_playing(w, port)
    h.wait_until(lambda: w.vdims_path == port, 10, "portrait dims")
    assert video_layout(w) == cd.Qt.Horizontal and w.vsplit.widget(1) is w.video


def test_fullscreen_in_and_out(make_window, media, tmp_path):
    d = audio_dir(media, tmp_path, ["clip mkv.mkv"])
    w = make_window(d)
    w.play_view(os.path.join(d, "clip mkv.mkv"))
    wait_playing(w, os.path.join(d, "clip mkv.mkv"))
    w.toggle_full()
    h.pump(200)
    assert w.full_hidden is not None and not w.list.isVisible()
    w.toggle_full()
    h.pump(200)
    assert w.full_hidden is None and w.list.isVisible() and w.bar.isVisible()


def test_video_without_audio(make_window, media, tmp_path):
    d = audio_dir(media, tmp_path, ["silent video.mp4"])
    w = make_window(d)
    w.play_view(os.path.join(d, "silent video.mp4"))
    wait_playing(w, os.path.join(d, "silent video.mp4"))
    for _ in MODES:
        w.wave.cycle()
        w.wave.grab()


@pytest.mark.parametrize("name", ["tone flac.flac", "clip webm.webm", "silent video.mp4"])
def test_every_waveform_view_paints(make_window, media, tmp_path, name):
    """Row 18: all 6 views paint on audio, video and no-audio files, before and after the analysis."""
    d = audio_dir(media, tmp_path, [name])
    w = make_window(d)
    p = os.path.join(d, name)
    w.play_view(p)
    wait_playing(w, p)
    for mode in MODES:
        w.wave.set_mode(mode)
        w.wave.grab()
    h.pump(3000)
    for mode in MODES:
        w.wave.set_mode(mode)
        w.wave.grab()


def test_waveform_cache_reused(make_window, media, tmp_path, monkeypatch):
    """Row 18: the second play of a track uses the cached analysis (ffmpeg isn't run again)."""
    import subprocess
    import waveform
    d = audio_dir(media, tmp_path, ["tone aiff.aiff"])
    p = os.path.join(d, "tone aiff.aiff")
    w = make_window(d)
    w.play_view(p)
    wait_playing(w, p)
    cache = waveform.cache_dir()
    h.wait_until(lambda: any(f.endswith(".npz") for f in os.listdir(cache)), 60, "analysis cached")
    w.stop()
    runs = []
    real = subprocess.Popen
    monkeypatch.setattr(waveform.subprocess, "Popen", lambda *a, **k: runs.append(a) or real(*a, **k))
    w.play_view(p)
    wait_playing(w, p)
    h.pump(1500)
    assert runs == []
