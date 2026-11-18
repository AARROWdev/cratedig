"""Playlists: one UTF-8 .m3u8 per playlist in Music\\Cratedig Playlists. Pure file helpers + the side panel."""
import os
import re
import shutil

from PySide6.QtCore import QStandardPaths, Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem

EXT = ".m3u8"
BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(10)), *(f"lpt{i}" for i in range(10))}

DIR = None   # tests point this at a temp folder


def folder():
    music = QStandardPaths.writableLocation(QStandardPaths.MusicLocation) or os.path.join(os.path.expanduser("~"), "Music")
    d = DIR or os.path.join(music, "Cratedig Playlists")
    os.makedirs(d, exist_ok=True)
    return d


def clean_name(name):
    """A safe file name for a playlist, or "" if nothing usable is left."""
    name = BAD.sub("", name or "").strip().rstrip(". ")
    if name.casefold() in RESERVED:
        return ""
    return name[:120]


def path_for(name):
    return os.path.join(folder(), name + EXT)


def names():
    try:
        return sorted((f[:-len(EXT)] for f in os.listdir(folder()) if f.lower().endswith(EXT)), key=str.casefold)
    except OSError:
        return []


def unique(base):
    n, i = base, 2
    while os.path.exists(path_for(n)):
        n = f"{base} ({i})"
        i += 1
    return n


def read(path):
    """Absolute paths (and URL lines, kept as they are), in order. Relative entries are resolved against the
    playlist's folder. Raises OSError if the file can't be read: callers must not write over a playlist they
    couldn't read, or a locked or offline file would come back empty."""
    base = os.path.dirname(path)
    with open(path, "rb") as f:
        raw = f.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("mbcs", "replace")   # an older ANSI .m3u from another player
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "\x00" in line:
            continue
        if "://" in line:
            out.append(line)   # a stream URL: shown as missing, written back unchanged
            continue
        p = line if os.path.isabs(line) else os.path.join(base, line)
        out.append(os.path.normpath(p))
    return out


def write(path, paths):
    """Atomic: a crash mid-write never leaves a half playlist."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("#EXTM3U\n")
        for p in paths:
            f.write(p.encode("utf-8", "replace").decode("utf-8") + "\n")
    os.replace(tmp, path)


def recycle(path):
    """Send a file to the Recycle Bin (never a permanent delete). True on success."""
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]
    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 4, 0x10, 0x40, 0x400
    FOF_WANTNUKEWARNING = 0x4000   # where there's no Recycle Bin, Windows asks before deleting for good
    op = SHFILEOPSTRUCTW(None, FO_DELETE, os.path.abspath(path) + "\0", None,
                         FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI | FOF_WANTNUKEWARNING,
                         False, None, None)
    return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0 and not op.fAnyOperationsAborted \
        and not os.path.exists(path)


def copy_tracks(paths, dest):
    """Copy the files that exist into dest. Never overwrites: each target is created exclusively, so a file
    that appears meanwhile gets " (2)" instead. A failed copy leaves nothing behind.
    Returns (copied, missing, failed)."""
    copied = missing = failed = 0
    for p in paths:
        if not os.path.isfile(p):
            missing += 1
            continue
        stem, ext = os.path.splitext(os.path.basename(p))
        target, i = os.path.join(dest, stem + ext), 2
        out = None
        try:
            while out is None:
                try:
                    out = open(target, "xb")
                except FileExistsError:
                    target = os.path.join(dest, f"{stem} ({i}){ext}")
                    i += 1
            with out, open(p, "rb") as src:
                shutil.copyfileobj(src, out, 1 << 20)
            shutil.copystat(p, target)
            copied += 1
        except OSError:
            failed += 1
            if out is not None:
                try:
                    os.remove(target)
                except OSError:
                    pass
    return copied, missing, failed


class PlaylistList(QListWidget):
    """The side panel. Files dropped on a playlist are added to it."""
    filesDropped = Signal(str, list)   # playlist name, paths

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)
        self.setEditTriggers(QAbstractItemView.EditKeyPressed)

    def refresh(self, select=None):
        cur = select or (self.currentItem().data(Qt.UserRole) if self.currentItem() else None)
        self.blockSignals(True)
        self.clear()
        for n in names():
            it = QListWidgetItem(n)
            it.setData(Qt.UserRole, n)
            it.setFlags(it.flags() | Qt.ItemIsEditable)
            self.addItem(it)
            if n == cur:
                self.setCurrentItem(it)
        self.blockSignals(False)

    def item_named(self, name):
        for i in range(self.count()):
            if self.item(i).data(Qt.UserRole) == name:
                return self.item(i)
        return None

    def _files(self, ev):
        md = ev.mimeData()
        if not md.hasUrls():
            return []
        return [os.path.normpath(u.toLocalFile()) for u in md.urls() if u.isLocalFile() and os.path.isfile(u.toLocalFile())]

    def dragEnterEvent(self, ev):
        if self._files(ev):
            ev.setDropAction(Qt.CopyAction)
            ev.accept()
        else:
            ev.ignore()

    def dragMoveEvent(self, ev):
        it = self.itemAt(ev.position().toPoint())
        if it and self._files(ev):
            ev.setDropAction(Qt.CopyAction)
            ev.accept()
        else:
            ev.ignore()

    def dropEvent(self, ev):
        it = self.itemAt(ev.position().toPoint())
        files = self._files(ev)
        if it and files:
            ev.setDropAction(Qt.CopyAction)
            ev.accept()
            self.filesDropped.emit(it.data(Qt.UserRole), files)
        else:
            ev.ignore()
