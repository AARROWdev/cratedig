"""Cratedig 1.2: compact mode + playlists (written spec)."""
import os
import shutil

import pytest
from PySide6.QtCore import QMimeData, QModelIndex, Qt, QUrl

import cratedig as cd
import helpers as h
import playlists as pl

pytestmark = pytest.mark.window


def crate(media, tmp_path, names=("tone wav.wav", "tone mp3.mp3", "tone flac.flac", "clip mp4.mp4")):
    d = str(tmp_path / "crate")
    os.makedirs(d, exist_ok=True)
    for n in names:
        shutil.copy(os.path.join(media[0], n), os.path.join(d, n))
    return d


def wait_playing(w, path, timeout=20):
    h.wait_until(lambda: w.cur_path and os.path.normcase(w.cur_path) == os.path.normcase(path), timeout,
                 f"playing {os.path.basename(path)}")


def urls(*paths):
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(p) for p in paths])
    return md


# ---------- compact mode

def test_buttons_follow_track_type(make_window, media, tmp_path):
    d = crate(media, tmp_path)
    w = make_window(d)
    assert w.btn_compact.isVisibleTo(w) and not w.btn_video.isVisibleTo(w) and not w.btn_full.isVisibleTo(w)
    w.play_view(os.path.join(d, "clip mp4.mp4"))
    wait_playing(w, os.path.join(d, "clip mp4.mp4"))
    h.pump(300)
    assert w.btn_video.isVisibleTo(w) and w.btn_full.isVisibleTo(w) and not w.btn_compact.isVisibleTo(w)
    w.play_view(os.path.join(d, "tone mp3.mp3"))
    wait_playing(w, os.path.join(d, "tone mp3.mp3"))
    h.pump(300)
    assert w.btn_compact.isVisibleTo(w) and not w.btn_video.isVisibleTo(w)
    assert not w.video.isVisibleTo(w)   # no empty black pane for audio


def test_compact_and_back(make_window, media, tmp_path):
    d = crate(media, tmp_path)
    w = make_window(d, size=(1300, 800))
    w.play_view(os.path.join(d, "tone wav.wav"))
    wait_playing(w, os.path.join(d, "tone wav.wav"))
    before = w.geometry()
    w.toggle_compact()
    h.pump(200)
    assert not w.hsplit.isVisible() and not w.topbar.isVisible()
    assert w.wave.isVisible() and w.btn_play.isVisible() and w.vol.isVisible()
    assert w.width() < 800 and w.btn_compact.text() == "FULL"
    w.escape()   # Esc comes back
    h.pump(200)
    assert w.hsplit.isVisible() and w.topbar.isVisible() and w.btn_compact.text() == "COMPACT"
    assert w.geometry().size() == before.size()


def test_compact_remembers_its_size(make_window, media, tmp_path):
    d = crate(media, tmp_path)
    w = make_window(d)
    w.toggle_compact()
    h.pump(100)
    w.resize(640, w.height())
    h.pump(100)
    w.toggle_compact()
    w.toggle_compact()
    h.pump(100)
    assert w.width() == 640


def test_video_leaves_compact(make_window, media, tmp_path):
    d = crate(media, tmp_path)
    w = make_window(d)
    w.toggle_compact()
    w.play_view(os.path.join(d, "clip mp4.mp4"))
    wait_playing(w, os.path.join(d, "clip mp4.mp4"))
    h.pump(300)
    assert w.compact_from is None and w.hsplit.isVisible()


def test_close_while_compact_saves_full_window(make_window, media, tmp_path, isolated):
    from PySide6.QtCore import QSettings
    d = crate(media, tmp_path)
    w = make_window(d, size=(1200, 760))
    w.toggle_compact()
    h.pump(100)
    w.close()
    w2 = make_window(d)
    h.pump(100)
    assert w2.hsplit.isVisible() and w2.width() >= 1000


# ---------- playlists

def test_new_add_open_order(make_window, media, tmp_path):
    d = crate(media, tmp_path)
    w = make_window(d)
    name = w.new_playlist("Friday", edit=False)
    assert name == "Friday" and os.path.isfile(pl.path_for("Friday"))
    w.navigate(d)
    a, b = os.path.join(d, "tone mp3.mp3"), os.path.join(d, "tone wav.wav")
    w.add_to_playlist("Friday", [b, a, os.path.join(d, "nope.txt")])
    assert pl.read(pl.path_for("Friday")) == [b, a]
    w.open_playlist("Friday")
    assert [e.path for e in w.view_entries()] == [b, a]   # playlist order, not sorted
    assert w.addr.text() == "Playlist: Friday"
    w.play_view(None)
    wait_playing(w, b)
    assert w.queue == [b, a]


def test_drop_into_open_playlist_and_reorder(make_window, media, tmp_path):
    d = crate(media, tmp_path)
    w = make_window(d)
    w.new_playlist("Set", edit=False)
    files = [os.path.join(d, n) for n in ("tone wav.wav", "tone mp3.mp3", "tone flac.flac")]
    m = w.model
    assert m.dropMimeData(urls(*files, d), Qt.CopyAction, -1, 0, QModelIndex())   # the folder is ignored
    assert m.paths() == files
    md = QMimeData()
    md.setData(m.ROWS_MIME, b"2")          # flac to the top
    m.dropMimeData(md, Qt.CopyAction, 0, 0, QModelIndex())
    assert m.paths() == [files[2], files[0], files[1]]
    assert pl.read(pl.path_for("Set")) == m.paths()   # saved on every change


def test_drag_out_is_copy_only_and_files_only(make_window, media, tmp_path):
    d = crate(media, tmp_path)
    os.makedirs(os.path.join(d, "sub"))
    w = make_window(d)
    m = w.model
    assert m.supportedDragActions() == Qt.CopyAction
    md = m.mimeData([m.index(r, 0) for r in range(m.rowCount())])
    got = sorted(os.path.normpath(u.toLocalFile()) for u in md.urls())
    assert got == sorted(os.path.join(d, n) for n in os.listdir(d) if os.path.isfile(os.path.join(d, n)))
    assert not m.dropMimeData(urls(os.path.join(d, "tone wav.wav")), Qt.CopyAction, -1, 0, QModelIndex())  # folder view


def test_remove_keeps_file(make_window, media, tmp_path):
    d = crate(media, tmp_path)
    w = make_window(d)
    f = os.path.join(d, "tone mp3.mp3")
    w.new_playlist("R", edit=False)
    w.add_to_playlist("R", [f])
    w.list.selectAll()
    w.remove_selected()
    assert pl.read(pl.path_for("R")) == [] and os.path.isfile(f)


def test_same_file_twice(make_window, media, tmp_path):
    d = crate(media, tmp_path)
    w = make_window(d)
    f = os.path.join(d, "tone wav.wav")
    w.new_playlist("Twice", edit=False)
    w.add_to_playlist("Twice", [f, f])
    h.wait_until(lambda: all(e.dur and e.dur > 0 for e in w.model.entries), 30, "both lengths")


def test_missing_file_greyed_and_skipped(make_window, media, tmp_path):
    d = crate(media, tmp_path)
    w = make_window(d)
    gone = os.path.join(d, "gone.mp3")
    a = os.path.join(d, "tone wav.wav")
    pl.write(pl.path_for("Holes"), [gone, a])
    w.pl_list.refresh()
    w.open_playlist("Holes")
    m = w.model
    assert m.entries[0].missing and m.data(m.index(0, 0), Qt.ForegroundRole) == m.grey
    w.open_entry(m.entries[0])
    assert "not found" in w.statusBar().currentMessage()
    w.play_view(None)
    wait_playing(w, a)
    assert w.queue == [a]


def test_rename_duplicate_export_names(make_window, media, tmp_path):
    d = crate(media, tmp_path)
    w = make_window(d)
    f = os.path.join(d, "tone mp3.mp3")
    w.new_playlist("Old", edit=False)
    w.add_to_playlist("Old", [f])
    assert w.rename_playlist("Old", "New: one?") == "New one"
    assert w.playlist == "New one" and not os.path.exists(pl.path_for("Old"))
    assert w.rename_playlist("New one", "CON") == "New one"   # reserved name refused
    assert w.duplicate_playlist("New one") == "New one copy"
    assert pl.read(pl.path_for("New one copy")) == [f]
    out = str(tmp_path / "out.m3u8")
    w.export_playlist("New one", out)
    assert pl.read(out) == [f]
    w.new_playlist("Other", edit=False)
    assert w.rename_playlist("Other", "New one") == "Other"   # no clobbering another playlist


def test_inline_rename_from_panel(make_window, media, tmp_path):
    d = crate(media, tmp_path)
    w = make_window(d)
    w.new_playlist("A", edit=False)
    it = w.pl_list.item_named("A")
    it.setText("B")   # what finishing an inline edit does
    h.pump(50)
    assert os.path.isfile(pl.path_for("B")) and not os.path.exists(pl.path_for("A"))


def test_copy_files_never_overwrites(make_window, media, tmp_path):
    d = crate(media, tmp_path)
    w = make_window(d)
    a = os.path.join(d, "tone mp3.mp3")
    pl.write(pl.path_for("Usb"), [a, a, os.path.join(d, "gone.wav")])
    dest = str(tmp_path / "usb")
    os.makedirs(dest)
    with open(os.path.join(dest, "tone mp3.mp3"), "wb") as f:
        f.write(b"keep me")
    assert w.copy_playlist_files("Usb", dest) == (2, 1)
    assert open(os.path.join(dest, "tone mp3.mp3"), "rb").read() == b"keep me"
    assert sorted(os.listdir(dest)) == ["tone mp3 (2).mp3", "tone mp3 (3).mp3", "tone mp3.mp3"]


def test_navigate_leaves_playlist_and_restores_sort(make_window, media, tmp_path):
    d = crate(media, tmp_path)
    w = make_window(d)
    w.list.sortByColumn(3, Qt.DescendingOrder)
    w.new_playlist("P", edit=False)
    assert w.playlist == "P"
    w.go_up()   # Backspace from a playlist: back to the folder
    assert w.playlist is None and w.cwd == os.path.normpath(d)
    assert w.proxy.sortColumn() == 3 and w.proxy.sortOrder() == Qt.DescendingOrder


def test_drop_on_panel_adds(make_window, media, tmp_path):
    d = crate(media, tmp_path)
    w = make_window(d)
    w.new_playlist("Drop", edit=False)
    w.navigate(d)
    f = os.path.join(d, "tone flac.flac")
    w.pl_list.filesDropped.emit("Drop", [f])
    assert pl.read(pl.path_for("Drop")) == [f]


def test_delete_goes_to_recycle_bin(make_window, media, tmp_path):
    if not h.IN_SANDBOX:
        pytest.skip("uses the real Recycle Bin: Sandbox only")
    d = crate(media, tmp_path)
    w = make_window(d)
    w.new_playlist("Bye", edit=False)
    assert w.delete_playlist("Bye")
    assert not os.path.exists(pl.path_for("Bye")) and w.playlist is None
    assert w.pl_list.item_named("Bye") is None


def test_corrupt_playlist_file(make_window, media, tmp_path):
    d = crate(media, tmp_path)
    w = make_window(d)
    with open(pl.path_for("Junk"), "wb") as f:
        f.write(b"\xff\xfe\x00garbage\n#EXTINF:1,x\n\n relative.mp3\n")
    w.pl_list.refresh()
    w.open_playlist("Junk")   # no crash; unreadable lines become missing rows
    assert all(e.missing for e in w.model.entries)
