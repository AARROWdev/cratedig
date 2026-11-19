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
    m.dropMimeData(urls(*files, d), Qt.CopyAction, -1, 0, QModelIndex())   # the folder is ignored
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
    assert w.copy_playlist_files("Usb", dest) == (2, 1, 0)
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


# ---------- 1.2 review pass 1 (V1-V4, v5-v14)

def test_v1_move_drop_from_outside_is_refused(make_window, media, tmp_path):
    """Shift-drag from Explorer is a Move: refusing it is what stops Explorer deleting the originals."""
    d = crate(media, tmp_path)
    w = make_window(d)
    w.new_playlist("Mv", edit=False)
    f = os.path.join(d, "tone wav.wav")
    m = w.model
    assert not m.canDropMimeData(urls(f), Qt.MoveAction, -1, 0, QModelIndex())
    assert not m.dropMimeData(urls(f), Qt.MoveAction, -1, 0, QModelIndex())
    assert m.paths() == []
    assert not m.dropMimeData(urls(f), Qt.CopyAction, -1, 0, QModelIndex())   # added, but never reported as dropped
    assert m.paths() == [f] and os.path.isfile(f)


def test_v1_move_drop_event_on_the_view(make_window, media, tmp_path):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QDropEvent
    d = crate(media, tmp_path)
    w = make_window(d)
    w.new_playlist("Ev", edit=False)
    f = os.path.join(d, "tone mp3.mp3")
    ev = QDropEvent(QPointF(10, 10), Qt.MoveAction, urls(f), Qt.LeftButton, Qt.ShiftModifier)
    from PySide6.QtWidgets import QApplication
    QApplication.sendEvent(w.list.viewport(), ev)
    assert not (ev.isAccepted() and ev.dropAction() == Qt.MoveAction)
    assert os.path.isfile(f)


def test_v2_unreadable_playlist_is_never_written(make_window, media, tmp_path):
    d = crate(media, tmp_path)
    w = make_window(d)
    os.makedirs(pl.path_for("Locked"))   # can't be read as a file
    w.pl_list.refresh()
    assert w.add_to_playlist("Locked", [os.path.join(d, "tone wav.wav")]) == 0
    assert os.path.isdir(pl.path_for("Locked"))
    assert w.open_playlist("Locked") is False and w.playlist is None
    assert w.duplicate_playlist("Locked") is None
    assert w.export_playlist("Locked", str(tmp_path / "x.m3u8")) is None
    with pytest.raises(OSError):
        pl.read(str(tmp_path / "nope.m3u8"))


def test_v4_dead_drive_doesnt_stat_each_track(make_window, media, tmp_path, monkeypatch):
    import time
    d = crate(media, tmp_path)
    w = make_window(d)
    drive = next(c for c in "QXYZWV" if not os.path.exists(c + ":\\"))
    dead = [os.path.join(drive + ":\\", "nas", f"track{i}.mp3") for i in range(500)]
    a = os.path.join(d, "tone wav.wav")
    pl.write(pl.path_for("Nas"), dead + [a])
    stats = []
    real_stat = cd.PathEntry.stat
    monkeypatch.setattr(cd.PathEntry, "stat", lambda self: (None if self.dead else stats.append(self.path)) or real_stat(self))   # a real os.stat
    w.pl_list.refresh()
    t = time.monotonic()
    w.open_playlist("Nas")
    assert time.monotonic() - t < 5
    assert all(e.missing and e.why == "drive or share not reachable" for e in w.model.entries[:500])
    assert not w.model.entries[500].missing
    assert not [p for p in stats if p.startswith(drive + ":")]   # no per-track stat on a dead drive (V4)


def test_w2_offline_roots_share_one_deadline(monkeypatch):
    import threading
    import time
    gate = threading.Event()
    monkeypatch.setattr(cd.os.path, "isdir", lambda p: gate.wait(10) and False)
    t = time.monotonic()
    got = cd.dirs_alive({"A:\\", "B:\\", "C:\\"}, 1.0)
    gate.set()
    assert time.monotonic() - t < 2.0 and got == {"A:\\": False, "B:\\": False, "C:\\": False}


def test_v5_w1_encodings_urls_and_file_lines_kept(make_window, media, tmp_path):
    d = crate(media, tmp_path)
    w = make_window(d)
    url = "http://radio.example/stream.mp3"
    song = "C:\\Música\\canción\u2028x.mp3"   # a real U+2028 inside the name
    a = os.path.join(d, "tone wav.wav")
    with open(pl.path_for("U16"), "wb") as f:   # UTF-16 with BOM (W1)
        f.write(("#EXTM3U\n" + url + "\n" + song + "\n" + QUrl.fromLocalFile(a).toString() + "\n").encode("utf-16"))
    w.pl_list.refresh()
    assert w.open_playlist("U16")
    w.add_to_playlist("U16", [os.path.join(d, "tone mp3.mp3")])
    got = pl.read(pl.path_for("U16"))
    assert got[0] == url and got[1] == os.path.normpath(song) and got[2] == QUrl.fromLocalFile(a).toString()   # file: kept verbatim
    ansi = r"C:\Música\canción.mp3".encode("cp1252")
    raw = b"#EXTM3U\n" + ansi + b"\n"
    with open(pl.path_for("Ansi"), "wb") as f:   # not UTF-8: refused, never rewritten (W1)
        f.write(raw)
    w.pl_list.refresh()
    assert w.open_playlist("Ansi") is False
    assert w.add_to_playlist("Ansi", [a]) == 0
    assert open(pl.path_for("Ansi"), "rb").read() == raw


def test_v6_close_in_playlist_keeps_folder_sorting(make_window, media, tmp_path):
    d = crate(media, tmp_path)
    w = make_window(d)
    w.new_playlist("S", edit=False)
    w.close()
    w2 = make_window(d)
    assert w2.list.isSortingEnabled() and w2.proxy.sortColumn() >= 0


def test_v7_v12_copy_guard_and_failures(make_window, media, tmp_path):
    d = crate(media, tmp_path)
    w = make_window(d)
    a = os.path.join(d, "tone mp3.mp3")
    pl.write(pl.path_for("C"), [a])
    w.copying = True
    assert w.copy_playlist_files("C", str(tmp_path)) is None   # second copy refused
    w.copying = False
    assert pl.copy_tracks([a], str(tmp_path / "no" / "such")) == (0, 0, 1)
    assert not os.path.exists(str(tmp_path / "no"))


def test_v8_duplicate_row_plays_that_row(make_window, media, tmp_path):
    d = crate(media, tmp_path)
    w = make_window(d)
    a, b = os.path.join(d, "tone wav.wav"), os.path.join(d, "tone mp3.mp3")
    pl.write(pl.path_for("Dup"), [a, b, a])
    w.pl_list.refresh()
    w.open_playlist("Dup")
    w.open_entry(w.model.entries[2])
    h.wait_until(lambda: w.cur_path, 20, "playing")
    h.pump(300)
    assert w.player.playlist_pos == 2


def test_v10_play_on_unreadable_playlist_plays_nothing(make_window, media, tmp_path):
    d = crate(media, tmp_path)
    w = make_window(d)   # the folder view behind it has playable files
    os.makedirs(pl.path_for("Bad"))
    w.pl_list.refresh()
    w.play_playlist("Bad")
    h.pump(300)
    assert w.queue == []


def test_v3_v9_delete_lands_in_recycle_bin(make_window, media, tmp_path):
    if not h.IN_SANDBOX:
        pytest.skip("uses the real Recycle Bin: Sandbox only")
    import subprocess
    d = crate(media, tmp_path)
    w = make_window(d)
    w.new_playlist("BinMe", edit=False)
    shutil.rmtree(d)   # the folder behind the open playlist is gone (v9)
    assert w.delete_playlist("BinMe")
    assert w.playlist is None and not os.path.exists(pl.path_for("BinMe"))
    names = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "(New-Object -ComObject Shell.Application).NameSpace(10).Items() | ForEach-Object { $_.Name }"],
                           capture_output=True, text=True).stdout
    assert "BinMe" in names
    w.model.edited.emit()   # a late edit must not write the deleted playlist back
    assert not os.path.exists(pl.path_for("BinMe"))



def test_w3_failed_write_leaves_no_tmp(tmp_path):
    target = str(tmp_path / "x.m3u8")
    os.makedirs(target)   # os.replace onto a folder fails
    with pytest.raises(OSError):
        pl.write(target, ["C:\\a.mp3"])
    assert not os.path.exists(target + ".tmp")


def test_w5_space_starts_the_selected_duplicate(make_window, media, tmp_path):
    d = crate(media, tmp_path)
    w = make_window(d)
    a, b = os.path.join(d, "tone wav.wav"), os.path.join(d, "tone mp3.mp3")
    pl.write(pl.path_for("D2"), [a, b, a])
    w.pl_list.refresh()
    w.open_playlist("D2")
    w.list.setCurrentIndex(w.proxy.index(2, 0))
    w.play_pause()
    h.wait_until(lambda: w.cur_path, 20, "playing")
    h.pump(300)
    assert w.player.playlist_pos == 2


def test_w7_copystat_failure_keeps_the_copy(tmp_path, monkeypatch):
    src = tmp_path / "a.mp3"
    src.write_bytes(b"x" * 1000)
    dest = tmp_path / "out"
    dest.mkdir()
    def boom(*a, **k):
        raise PermissionError("no utime")
    monkeypatch.setattr(pl.shutil, "copystat", boom)
    assert pl.copy_tracks([str(src)], str(dest)) == (1, 0, 0)
    assert (dest / "a.mp3").read_bytes() == b"x" * 1000


# ---------- 1.2 review pass 3 (X1-X5)

@pytest.mark.parametrize("enc", ["utf-16-le", "utf-32"])
def test_x1_bomless_utf16_and_utf32_are_refused(tmp_path, enc):
    p = str(tmp_path / "x.m3u8")
    raw = "#EXTM3U\nC:\\a.mp3\n".encode(enc)
    with open(p, "wb") as f:
        f.write(raw)
    with pytest.raises(OSError):
        pl.read(p)


def test_x2_unencoded_file_url_kept_verbatim(tmp_path):
    p = str(tmp_path / "x.m3u8")
    lines = ["file:///D:/Music/Track #1.mp3", "file:///D:/a?b.mp3"]
    with open(p, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n" + "\n".join(lines) + "\n")
    assert pl.read(p) == lines


def test_x4_cr_only_line_endings(tmp_path):
    p = str(tmp_path / "x.m3u8")
    with open(p, "wb") as f:
        f.write(b"#EXTM3U\rC:\\a.mp3\rC:\\b.mp3\r")
    assert pl.read(p) == ["C:\\a.mp3", "C:\\b.mp3"]


def test_x3_failed_open_in_folder_view_selects_nothing(make_window, media, tmp_path):
    d = crate(media, tmp_path)
    w = make_window(d)
    os.makedirs(pl.path_for("Broken"))
    w.pl_list.refresh()
    w.pl_list.setCurrentItem(w.pl_list.item_named("Broken"))
    assert w.open_playlist("Broken") is False
    assert w.pl_list.currentItem() is None


def test_x5_no_access_is_not_called_missing(monkeypatch, tmp_path):
    def denied(self):
        raise PermissionError("denied")
    monkeypatch.setattr(cd.PathEntry, "stat", denied)
    e = cd.Entry(cd.PathEntry(str(tmp_path / "a.mp3")))
    assert e.missing and e.why == "no access"


# ---------- 1.2 review pass 4 (Y1-Y3, flags)

def test_z_file_links_always_kept_verbatim(tmp_path):
    """Z1-Z4: no file: line is ever converted, so none can come back changed (NUL, newline, localhost,
    file://D:/, folders and roots included)."""
    p = str(tmp_path / "x.m3u8")
    lines = ["file:///D:/Music/a%20b.mp3", "file:/C:/Music/a.mp3", "file://nas/music/a.mp3", "file:rel.mp3",
             "file:///D:/Music/Track #1.mp3", "file:///D:/x%AB.mp3", "file:///D:/a?b.mp3", "file:///D:/a%00b.mp3",
             "file:///D:/a%0Ab.mp3", "file://localhost/C:/Music/a.mp3", "file://D:/Music/a.mp3", "file:///D:/Music/",
             "file:///", "FILE:///D:/x.mp3"]
    with open(p, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n" + "\n".join(lines) + "\n")
    got = pl.read(p)
    assert got == lines
    pl.write(p, got)
    assert open(p, "rb").read() == ("#EXTM3U\n" + "\n".join(lines) + "\n").encode()   # byte for byte


def test_y2_file_lines_never_touch_the_disk(tmp_path, monkeypatch):
    p = str(tmp_path / "x.m3u8")
    with open(p, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\nfile://deadnas/music/a.mp3\nfile:///D:/Track #1.mp3\n")
    calls = []
    monkeypatch.setattr(pl.os.path, "isfile", lambda q: calls.append(q) or False)
    monkeypatch.setattr(pl.os.path, "exists", lambda q: calls.append(q) or False)
    monkeypatch.setattr(pl.os, "stat", lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(OSError()))
    for line in pl.read(p) + ["file:///D:/Music/a%20b.mp3", "file://nas/music/a.mp3"]:
        pl.local_path(line)
    assert calls == []


def test_y3_unreadable_file_link_is_labelled(tmp_path):
    e = cd.Entry(cd.PathEntry("file:///D:/Track #1.mp3"))
    assert e.missing and e.why == "file link Cratedig can't read"


def test_flags_drag_and_drop():
    m = cd.DirModel()
    class DE:
        def __init__(self, name, d):
            self.name, self.path, self._d = name, "C:\\x\\" + name, d
        def is_dir(self):
            return self._d
        def stat(self):
            return os.stat_result((0,) * 10)
    m.beginResetModel()
    m.set_entries([cd.Entry(DE("f.mp3", False)), cd.Entry(DE("sub", True))])
    f, d = m.flags(m.index(0, 0)), m.flags(m.index(1, 0))
    assert f & Qt.ItemIsDragEnabled and not d & Qt.ItemIsDragEnabled
    assert f & Qt.ItemIsSelectable and f & Qt.ItemIsEnabled
    assert not m.flags(QModelIndex()) & Qt.ItemIsDropEnabled
    m.pl_mode = True
    assert m.flags(QModelIndex()) & Qt.ItemIsDropEnabled and m.flags(m.index(0, 0)) & Qt.ItemIsDropEnabled



def test_z5_link_rows_drag_no_urls(make_window, media, tmp_path):
    d = crate(media, tmp_path)
    w = make_window(d)
    a = os.path.join(d, "tone wav.wav")
    pl.write(pl.path_for("Z5"), ["file:///D:/Track #1.mp3", a, os.path.join(d, "gone.mp3")])
    w.pl_list.refresh()
    w.open_playlist("Z5")
    m = w.model
    md = m.mimeData([m.index(r, 0) for r in range(3)])
    assert [os.path.normpath(u.toLocalFile()) for u in md.urls()] == [a, os.path.join(d, "gone.mp3")]   # a missing file still drags (AA3)
    assert bytes(md.data(m.ROWS_MIME)) == b"0,1,2"   # reordering still moves every row


# ---------- 1.2 review pass 6 (AA1-AA3)

def test_aa1_wellformed_file_link_plays_and_saves_unchanged(make_window, media, tmp_path):
    d = crate(media, tmp_path)
    w = make_window(d)
    a = os.path.join(d, "tone mp3.mp3")
    link = QUrl.fromLocalFile(a).toString(QUrl.FullyEncoded)   # file:///C:/.../tone%20mp3.mp3, as VLC writes it
    assert "%20" in link and pl.local_path(link) == os.path.normpath(a)
    with open(pl.path_for("Vlc"), "w", encoding="utf-8", newline="\n") as f:
        f.write("#EXTM3U\n" + link + "\n")
    w.pl_list.refresh()
    assert w.open_playlist("Vlc")
    e = w.model.entries[0]
    assert e.path == os.path.normpath(a) and e.name == "tone mp3.mp3" and not e.missing and e.media
    w.add_to_playlist("Vlc", [os.path.join(d, "tone wav.wav")])
    assert pl.read(pl.path_for("Vlc"))[0] == link   # saved back exactly as written
    w.duplicate_playlist("Vlc")
    assert pl.read(pl.path_for("Vlc copy"))[0] == link
    w.open_playlist("Vlc")
    w.play_view(None)
    wait_playing(w, os.path.normpath(a))
    assert w.queue[0] == os.path.normpath(a)


def test_aa1_local_path_strict():
    assert pl.local_path("file:///D:/Music/a%20b.mp3") == "D:\\Music\\a b.mp3"
    assert pl.local_path("file://nas/music/a.mp3") == "\\\\nas\\music\\a.mp3"
    for bad in ["file:rel.mp3", "file:/C:/a.mp3", "file:///D:/Track #1.mp3", "file:///D:/a?b.mp3", "file:///D:/a%00b.mp3",
                "file:///D:/a%0Ab.mp3", "file://localhost/C:/a.mp3", "file://D:/a.mp3", "file:///D:/Music/", "file:///",
                "file:///D:/x%AB.mp3", "http://x/a.mp3", "D:\\a.mp3"]:
        assert pl.local_path(bad) is None, bad


def test_aa2_copy_counts_unresolvable_links_as_missing(make_window, media, tmp_path):
    d = crate(media, tmp_path)
    w = make_window(d)
    a = os.path.join(d, "tone mp3.mp3")
    good = QUrl.fromLocalFile(os.path.join(d, "tone wav.wav")).toString(QUrl.FullyEncoded)
    with open(pl.path_for("Mix"), "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n" + a + "\n" + good + "\nfile:///D:/Track #1.mp3\nhttp://radio.example/s.mp3\n")
    out = tmp_path / "out"
    out.mkdir()
    assert w.copy_playlist_files("Mix", str(out)) == (2, 2, 0)
    assert sorted(os.listdir(out)) == ["tone mp3.mp3", "tone wav.wav"]


def test_aa3_dead_and_no_access_rows_still_drag(monkeypatch, tmp_path):
    m = cd.DirModel()
    gone = str(tmp_path / "asleep.mp3")
    locked = str(tmp_path / "locked.mp3")
    def denied(self):
        raise PermissionError("denied")
    m.beginResetModel()
    m.pl_mode = True
    rows = [cd.Entry(cd.PathEntry(gone, dead=True))]
    monkeypatch.setattr(cd.PathEntry, "stat", denied)
    rows += [cd.Entry(cd.PathEntry(locked)), cd.Entry(cd.PathEntry("file:///D:/Track #1.mp3")),
             cd.Entry(cd.PathEntry("http://radio.example/s.mp3"))]
    m.set_entries(rows)
    assert all(e.missing for e in m.entries)
    md = m.mimeData([m.index(r, 0) for r in range(4)])
    assert [os.path.normpath(u.toLocalFile()) for u in md.urls()] == [gone, locked]   # links drag no URL
    assert bytes(md.data(m.ROWS_MIME)) == b"0,1,2,3"   # every row still reorders


# ---------- 1.2 review pass 7 (BB1-BB2)

def test_bb1_drag_over_panel_never_touches_the_disk(monkeypatch):
    calls = []
    monkeypatch.setattr(pl.os.path, "isfile", lambda q: calls.append(q) or False)
    monkeypatch.setattr(pl.os, "stat", lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(OSError()))
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(r"\\deadhost\share\a.mp3")])
    class Ev:
        def mimeData(self):
            return md
    assert pl.PlaylistList()._files(Ev()) == [r"\\deadhost\share\a.mp3"]
    assert calls == []


def test_bb1_drop_leaves_out_files_on_dead_shares(make_window, media, tmp_path, monkeypatch):
    d = crate(media, tmp_path)
    w = make_window(d)
    a = os.path.join(d, "tone mp3.mp3")
    dead = r"\\deadhost\share\b.mp3"
    seen = []
    monkeypatch.setattr(cd, "dirs_alive", lambda roots, s: seen.append(set(roots)) or {r: not r.startswith("\\\\") for r in roots})
    real_isfile = os.path.isfile
    monkeypatch.setattr(cd.os.path, "isfile", lambda q: (_ for _ in ()).throw(AssertionError("stat " + q)) if q == dead else real_isfile(q))
    w.new_playlist("Nas", edit=False)
    w.leave_playlist()
    assert w.add_to_playlist("Nas", [dead, a]) == 1   # closed playlist
    assert pl.read(pl.path_for("Nas")) == [a]
    w.open_playlist("Nas")
    assert w.add_to_playlist("Nas", [dead, a]) == 1   # open playlist: insert_paths
    assert [e.path for e in w.model.entries] == [a, a]
    assert any(r.lower().startswith(r"\\deadhost") for s in seen for r in s)   # checked with the deadline


def test_bb2_dot_segments_and_trailing_space_not_converted():
    for bad in ["file:///D:/Music/.", "file:///D:/Music/..", "file:///D:/Music/%2E%2E", "file:///D:/x/../a.mp3",
                "file://nas/share/.", "file:///D:/a.mp3%20", "file:///D:/a.mp3."]:
        assert pl.local_path(bad) is None, bad
    assert pl.local_path("file:///D:/Mu.sic/a%20b.mp3") == r"D:\Mu.sic\a b.mp3"
    assert pl.resolve("http://x/a.mp3") is None and pl.resolve(r"D:\a.mp3") == r"D:\a.mp3"
