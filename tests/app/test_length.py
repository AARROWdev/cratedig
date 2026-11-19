"""Plan C: the Length column (rows 11-13)."""
import os
import shutil
import time

import pytest

import cratedig as cd
import helpers as h


def loaded(path):
    m = cd.DirModel()
    m.load(path)
    h.wait_until(lambda: all(e.dur is not None for e in m.entries if e.media), 120, "lengths")
    return m


def test_every_type_within_one_second(media):
    """Row 11: every supported audio/video type shows its real length (within 1 s)."""
    d, truth = media
    m = loaded(d)
    for e in m.entries:
        want = truth.get(e.name)
        if want is None:
            continue
        assert e.dur is not None and abs(e.dur - want) <= 1, f"{e.name}: {e.dur} vs {want}"
        assert m.data(m.index(m.rows[e.path][0], 2)) == cd.fmt_time(e.dur)


def test_broken_and_non_media_are_blank(media):
    """Row 12: corrupt, 0-byte and non-media files: blank, no crash."""
    m = loaded(media[0])
    shown = {e.name: m.data(m.index(i, 2)) for i, e in enumerate(m.entries)}
    for n in ("corrupt.mp3", "empty.wav"):
        assert shown[n] == "", n
    assert "notes.txt" not in shown   # 1.2: non-media files are not listed at all


def test_length_sort(media):
    """Lengths sort numerically (folders first, then shortest to longest)."""
    m = loaded(media[0])
    p = cd.SortProxy()
    p.setSourceModel(m)
    p.sort(2, cd.Qt.AscendingOrder)
    durs = [m.entries[p.mapToSource(p.index(r, 0)).row()].dur or 0 for r in range(p.rowCount())]
    assert durs == sorted(durs)


def test_cache_reused(media, monkeypatch):
    """A second visit doesn't probe again (only files whose first probe failed are retried)."""
    m = loaded(media[0])
    failed = {e.path for e in m.entries if e.media and e.dur is not None and e.dur < 0}
    calls = []
    monkeypatch.setattr(cd, "probe_duration", lambda p: calls.append(p) or 1.0)
    loaded(media[0])
    assert set(calls) == failed


def test_changed_file_is_probed_again(media, tmp_path):
    """A file replaced with a different length shows the new length, not the cached one."""
    d = str(tmp_path / "c")
    os.makedirs(d)
    p = os.path.join(d, "x.wav")
    shutil.copy(os.path.join(media[0], "tone wav.wav"), p)
    assert abs(loaded(d).entries[0].dur - 5) <= 1
    shutil.copy(os.path.join(media[0], "tone aiff.aiff"), p)   # 11 s, different size
    os.utime(p, (time.time() + 5, time.time() + 5))
    assert abs(loaded(d).entries[0].dur - 11) <= 1


@pytest.mark.big
def test_2000_files_stay_responsive(media, tmp_path):
    """Row 13: 2,000 files; the event loop never stalls while lengths fill in."""
    d = str(tmp_path / "many")
    os.makedirs(d)
    src = os.path.join(media[0], "tone mp3.mp3")
    for i in range(2000):
        shutil.copy(src, os.path.join(d, f"{i:04d}.mp3"))
    m = cd.DirModel()
    t = time.monotonic()
    m.load(d)
    assert time.monotonic() - t < 2
    worst, last = 0, time.monotonic()
    end = time.monotonic() + 300
    while any(e.dur is None for e in m.entries) and time.monotonic() < end:
        h.pump(20)
        now = time.monotonic()
        worst, last = max(worst, now - last), now
    assert all(e.dur and abs(e.dur - 7) <= 1 for e in m.entries)
    assert worst < 2, f"event loop stalled {worst:.1f}s"


def test_switching_folders_mid_fill_no_stale_values(media, tmp_path):
    """Row 13: leave a folder before its lengths finish; the new folder never gets the old folder's values."""
    a = str(tmp_path / "a")
    os.makedirs(a)
    for i in range(300):
        shutil.copy(os.path.join(media[0], "tone flac.flac"), os.path.join(a, f"{i:03d}.flac"))
    b = str(tmp_path / "b")
    os.makedirs(b)
    for i in range(300):   # same names, different length
        shutil.copy(os.path.join(media[0], "tone wav.wav"), os.path.join(b, f"{i:03d}.flac"))
    m = cd.DirModel()
    m.load(a)
    h.pump(50)
    m.load(b)
    h.wait_until(lambda: all(e.dur is not None for e in m.entries), 120, "lengths of b")
    h.pump(500)   # let any late batches from folder a arrive
    assert all(abs(e.dur - 5) <= 1 for e in m.entries), "a value from the old folder leaked in"
