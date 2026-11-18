"""Cratedig - file explorer + media player in one window."""
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata

HERE = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
LIB = os.path.join(HERE, "lib")
os.environ["PATH"] = LIB + os.pathsep + HERE + os.pathsep + os.environ.get("PATH", "")

import mpv  # noqa: E402
from PySide6.QtCore import (QAbstractTableModel, QDir, QFileInfo, QMimeData, QModelIndex, QObject,  # noqa: E402
                            QSettings, QSortFilterProxyModel, Qt, QTimer, QUrl, Signal)
from PySide6.QtNetwork import QLocalServer, QLocalSocket  # noqa: E402
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QShortcut  # noqa: E402
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QFileIconProvider,  # noqa: E402
                               QFileSystemModel, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMainWindow, QMenu, QPushButton, QSlider, QSplitter, QStyle,
                               QToolButton, QTreeView, QVBoxLayout, QWidget)

import playlists  # noqa: E402
import themes  # noqa: E402
from waveform import MODES, Analyzer, WaveView, find_ffmpeg  # noqa: E402

APP = "Cratedig"
VERSION = "1.2"

AUDIO = {"wav", "mp3", "flac", "aiff", "aif", "m4a", "aac", "ogg", "oga", "opus", "wma", "alac",
         "ape", "wv", "mka"}
VIDEO = {"mp4", "mkv", "mov", "avi", "webm", "wmv", "m4v", "flv", "mpg", "mpeg", "ts", "m2ts",
         "3gp", "vob", "ogv"}
MEDIA = AUDIO | VIDEO


def natural_key(s):
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))   # Åsgeir sorts with A
    return [int(t) if t.isdecimal() else t for t in re.split(r"(\d+)", s.casefold())]   # isdecimal: '²' isn't an int


try:   # Explorer's own name order ("Disc.mp3" before "Disc2.mp3", "Song - live" before "Song")
    import ctypes
    import functools
    _cmp = ctypes.windll.shlwapi.StrCmpLogicalW
    _cmp.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p)
    _cmp.restype = ctypes.c_int
    _logical = functools.cmp_to_key(_cmp)
except (ImportError, AttributeError, OSError):
    _logical = natural_key


def sort_key(name):
    # (Explorer order, then the exact name): "é.mp3" vs "e.mp3" never tie
    return (_logical(name), unicodedata.normalize("NFC", name).casefold())


def human_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def fmt_time(sec):
    if sec is None or sec < 0:
        return "0:00"
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DUR_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
FFMPEG = find_ffmpeg(HERE)   # absolute: a bare "ffmpeg" would run an ffmpeg.exe sitting in the media folder
WINDIR = os.environ.get("SystemRoot", r"C:\Windows")


def probe_duration(path):
    """Seconds, or -1 if unknown. Audio: mutagen (fast, headers only). Video and WAV go to ffmpeg:
    mutagen misreads MPEG video, non-PCM WAV and MP4s whose audio is shorter than the picture."""
    ext = os.path.splitext(path)[1][1:].lower()
    if ext in AUDIO and ext != "wav":
        try:
            import mutagen
            f = mutagen.File(path)
            if f is not None and getattr(f, "info", None) and getattr(f.info, "length", 0):
                return float(f.info.length)
        except Exception:
            pass
    if not FFMPEG:
        return -1.0
    try:
        r = subprocess.run([FFMPEG, "-hide_banner", "-nostdin", "-i", path], capture_output=True, text=True,
                           errors="replace", timeout=15, creationflags=NO_WINDOW)
        m = DUR_RE.search(r.stderr)
        if m:
            h, mi, s = m.groups()
            return int(h) * 3600 + int(mi) * 60 + float(s)
    except Exception:
        pass
    return -1.0


class DurationWorker(QObject):
    """Reads track lengths for one folder on a background thread; results arrive in batches."""
    found = Signal(int, list)   # generation, [(path, seconds)]
    finished = Signal(int)      # generation
    cache = {}                  # (path, size, mtime) -> seconds, shared across folders

    def __init__(self):
        super().__init__()
        self.gen = 0

    def start(self, entries):
        self.gen += 1
        gen = self.gen
        todo = [(e.path, e.size, e.mtime) for e in entries if e.media]
        threading.Thread(target=self.run, args=(gen, todo), daemon=True).start()

    def run(self, gen, todo):
        batch, last = [], time.monotonic()
        for key in todo:
            if gen != self.gen:
                return
            sec = self.cache.get(key)
            if sec is None:
                sec = probe_duration(key[0])
                if sec >= 0:   # a failure may be transient (locked file, slow share): Refresh retries it
                    self.cache[key] = sec
                if time.monotonic() - last > 0.25:   # only real probes flush: cache hits arrive as one batch
                    batch.append((key[0], sec))
                    self.found.emit(gen, batch)
                    batch, last = [], time.monotonic()
                    continue
            batch.append((key[0], sec))
        if gen == self.gen:
            if batch:
                self.found.emit(gen, batch)
            self.finished.emit(gen)


class PathEntry:
    """os.DirEntry look-alike for a path from a playlist (which may no longer exist)."""

    def __init__(self, path, dead=False):
        self.path = path
        self.name = os.path.basename(path.rstrip("/")) if "://" in path else os.path.basename(path)
        self.dead = dead or "://" in path

    def is_dir(self):
        return False

    def stat(self):
        if self.dead:
            raise FileNotFoundError(self.path)
        return os.stat(self.path)


class Entry:
    __slots__ = ("name", "path", "is_dir", "size", "mtime", "ext", "key", "dur", "fold", "missing", "why")

    def __init__(self, de):
        self.name = de.name
        self.path = de.path
        self.dur = None
        self.missing = False
        self.why = ""
        try:
            self.is_dir = de.is_dir()
            st = de.stat()
            self.size = 0 if self.is_dir else st.st_size
            self.mtime = st.st_mtime
        except (OSError, ValueError) as ex:   # ValueError: a NUL in a path from a damaged playlist
            self.is_dir, self.size, self.mtime = False, 0, 0
            self.missing = isinstance(de, PathEntry)
            if self.missing:
                self.why = ("stream, not a file" if "://" in de.path else
                            "drive or share not reachable" if de.dead else
                            "file not found" if isinstance(ex, FileNotFoundError) else
                            "no access" if isinstance(ex, PermissionError) else
                            "damaged playlist line" if isinstance(ex, ValueError) else
                            (ex.strerror or str(ex)))
        self.ext = "" if self.is_dir else os.path.splitext(de.name)[1][1:].lower()
        self.key = sort_key(de.name)
        self.fold = unicodedata.normalize("NFC", de.name).casefold()   # what the filter matches (Mac-copied names are NFD)

    @property
    def media(self):
        return not self.is_dir and not self.missing and self.ext in MEDIA

    @property
    def type_label(self):
        if self.is_dir:
            return "Folder"
        return f"{self.ext.upper()} file" if self.ext else "File"


class DirModel(QAbstractTableModel):
    COLS = ["Name", "Type", "Length", "Size", "Date modified"]
    ROWS_MIME = "application/x-cratedig-rows"
    edited = Signal()   # a playlist's rows changed (drop, reorder, remove): save it

    def __init__(self):
        super().__init__()
        self.entries = []
        self.rows = {}
        self.pl_mode = False
        self.grey = QColor("#7d8590")
        self.durs = DurationWorker()
        self.durs.found.connect(self.set_durations)
        self.playing = None
        self.accent = QColor("#2f9bff")
        self.icons = QFileIconProvider()
        self.icon_cache = {}
        self.bold = QFont()
        self.bold.setBold(True)

    def load(self, path):
        self.beginResetModel()
        items = []
        err = None
        try:
            with os.scandir(path) as it:
                for de in it:
                    try:
                        items.append(Entry(de))
                    except OSError:
                        pass
        except OSError as e:
            err = str(e)
        self.pl_mode = False
        self.set_entries(items)
        return err

    def load_playlist(self, paths):
        roots = dirs_alive({os.path.splitdrive(p)[0] + "\\" for p in paths if "://" not in p}, 2.0)
        self.beginResetModel()
        self.pl_mode = True
        self.set_entries([Entry(PathEntry(p, dead="://" not in p and not roots[os.path.splitdrive(p)[0] + "\\"]))
                          for p in paths])

    def set_entries(self, items, reset=False):
        if reset:
            self.beginResetModel()
        self.entries = items
        self.reindex()
        self.endResetModel()
        self.durs.start(items)

    def reindex(self):
        self.rows = {}
        for i, e in enumerate(self.entries):
            self.rows.setdefault(e.path, []).append(i)   # a playlist can hold the same file twice

    def paths(self):
        return [e.path for e in self.entries]

    # drag and drop: files drag out of any view as file URLs; a playlist view accepts files and reorders
    def flags(self, index):
        f = super().flags(index)
        if index.isValid() and not self.entries[index.row()].is_dir:
            f |= Qt.ItemIsDragEnabled
        if self.pl_mode:
            f |= Qt.ItemIsDropEnabled
        return f

    def mimeTypes(self):
        return ["text/uri-list", self.ROWS_MIME]

    def supportedDragActions(self):
        return Qt.CopyAction   # never Move: a drag must not delete anything, here or in Windows Explorer

    def supportedDropActions(self):
        return Qt.CopyAction

    def mimeData(self, indexes):
        rows = sorted({ix.row() for ix in indexes if ix.isValid() and not self.entries[ix.row()].is_dir})
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(self.entries[r].path) for r in rows])
        if self.pl_mode:
            md.setData(self.ROWS_MIME, ",".join(map(str, rows)).encode())
        return md

    def canDropMimeData(self, data, action, row, column, parent):
        if not self.pl_mode:
            return False
        return data.hasFormat(self.ROWS_MIME) or (action == Qt.CopyAction and data.hasUrls())

    def dropMimeData(self, data, action, row, column, parent):
        if not self.pl_mode:
            return False
        if row < 0:
            row = parent.row() if parent.isValid() else len(self.entries)
        if data.hasFormat(self.ROWS_MIME):   # reorder inside the playlist
            try:
                rows = [int(x) for x in bytes(data.data(self.ROWS_MIME)).decode().split(",") if x]
            except ValueError:
                return False
            rows = [r for r in rows if 0 <= r < len(self.entries)]
            if not rows:
                return False
            moving = [self.entries[r] for r in rows]
            keep = [e for i, e in enumerate(self.entries) if i not in set(rows)]
            at = row - sum(1 for r in rows if r < row)
            self.beginResetModel()
            self.entries = keep[:at] + moving + keep[at:]
            self.reindex()
            self.endResetModel()
            self.edited.emit()
            return False   # handled here; False so the view never removes the "moved" source rows
        if action != Qt.CopyAction:
            return False   # a Move (Shift-drag from Explorer) would let Explorer delete the originals
        files = [os.path.normpath(u.toLocalFile()) for u in data.urls() if u.isLocalFile()]
        self.insert_paths(row, files)
        return False   # added; but report "not dropped" so no drag source ever treats it as a move

    def insert_paths(self, row, files):
        files = [f for f in files if os.path.isfile(f) and os.path.splitext(f)[1][1:].lower() in MEDIA and encodable(f)]
        if not files:
            return 0
        row = max(0, min(row, len(self.entries)))
        new = [Entry(PathEntry(f)) for f in files]
        self.beginInsertRows(QModelIndex(), row, row + len(new) - 1)
        self.entries[row:row] = new
        self.reindex()
        self.endInsertRows()
        self.durs.start(self.entries)
        self.edited.emit()
        return len(new)

    def remove_rows(self, rows):
        rows = sorted({r for r in rows if 0 <= r < len(self.entries)}, reverse=True)
        if not rows:
            return
        self.beginResetModel()
        for r in rows:
            del self.entries[r]
        self.reindex()
        self.endResetModel()
        self.edited.emit()

    def set_durations(self, gen, batch):
        if gen != self.durs.gen:
            return
        lo, hi = None, None
        for path, sec in batch:
            for r in self.rows.get(path, ()):
                self.entries[r].dur = sec
                lo = r if lo is None else min(lo, r)
                hi = r if hi is None else max(hi, r)
        if lo is not None:
            self.dataChanged.emit(self.index(lo, 2), self.index(hi, 2))

    def icon_for(self, e):
        k = "<dir>" if e.is_dir else e.ext
        if k not in self.icon_cache:
            self.icon_cache[k] = self.icons.icon(QFileInfo(e.path))
        return self.icon_cache[k]

    def set_playing(self, path):
        if path == self.playing:
            return
        self.playing = path
        if self.entries:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.entries) - 1, len(self.COLS) - 1))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.entries)

    def columnCount(self, parent=QModelIndex()):
        return len(self.COLS)

    def headerData(self, section, orient, role=Qt.DisplayRole):
        if orient == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        e = self.entries[index.row()]
        c = index.column()
        if role == Qt.DisplayRole:
            if c == 0:
                return e.name
            if c == 1:
                return e.type_label
            if c == 2:
                return fmt_time(e.dur) if e.dur and e.dur > 0 else ""
            if c == 3:
                return "" if e.is_dir else human_size(e.size)
            if c == 4:
                try:
                    return time.strftime("%Y-%m-%d %H:%M", time.localtime(e.mtime)) if e.mtime else ""
                except (OSError, OverflowError, ValueError):   # before 1970 / far future on Windows
                    return ""
        elif role == Qt.DecorationRole and c == 0:
            return self.icon_for(e)
        elif role == Qt.TextAlignmentRole and c in (2, 3):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        elif role == Qt.ToolTipRole and c == 0:
            return e.path + (f"\n({e.why})" if e.missing else "")
        elif role == Qt.ForegroundRole and e.missing:
            return self.grey
        elif role in (Qt.FontRole, Qt.ForegroundRole) and self.playing and e.path == self.playing:
            return self.bold if role == Qt.FontRole else self.accent
        return None


class SortProxy(QSortFilterProxyModel):
    """Folders first in either direction, then by column, ties by natural name."""

    def lessThan(self, left, right):
        m = self.sourceModel()
        a, b = m.entries[left.row()], m.entries[right.row()]
        if a.is_dir != b.is_dir:
            return a.is_dir == (self.sortOrder() == Qt.AscendingOrder)
        c = left.column()
        ka = {1: a.ext, 2: max(a.dur or 0, 0), 3: a.size, 4: a.mtime}.get(c)   # failed probe (-1) sorts with blanks
        kb = {1: b.ext, 2: max(b.dur or 0, 0), 3: b.size, 4: b.mtime}.get(c)
        if ka is not None and ka != kb:
            return ka < kb
        return a.key < b.key

    text = ""   # raw filter text, casefolded (setFilterFixedString would hand back an escaped pattern)

    def filterAcceptsRow(self, row, parent):
        if not self.text:
            return True
        return self.text in self.sourceModel().entries[row].fold


def glyph(kind, color="#eef1f5", size=28):
    """Bright vector transport icons (the stock ones vanish on dark skins)."""
    s = size * 2
    pm = QPixmap(s, s)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    path = QPainterPath()
    if kind == "play":
        path.moveTo(s * .30, s * .20)
        path.lineTo(s * .80, s * .50)
        path.lineTo(s * .30, s * .80)
    elif kind == "pause":
        path.addRoundedRect(s * .26, s * .20, s * .16, s * .60, 3, 3)
        path.addRoundedRect(s * .58, s * .20, s * .16, s * .60, 3, 3)
    elif kind == "stop":
        path.addRoundedRect(s * .25, s * .25, s * .50, s * .50, 4, 4)
    elif kind == "next":
        path.moveTo(s * .22, s * .24)
        path.lineTo(s * .62, s * .50)
        path.lineTo(s * .22, s * .76)
        path.addRoundedRect(s * .66, s * .24, s * .11, s * .52, 2, 2)
    elif kind == "vol":
        path.moveTo(s * .14, s * .38)
        path.lineTo(s * .30, s * .38)
        path.lineTo(s * .52, s * .18)
        path.lineTo(s * .52, s * .82)
        path.lineTo(s * .30, s * .62)
        path.lineTo(s * .14, s * .62)
        path.closeSubpath()
        p.drawPath(path)
        path = QPainterPath()
        pen = p.pen()
        p.setPen(QPen(QColor(color), s * .06, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawArc(int(s * .42), int(s * .32), int(s * .24), int(s * .36), -50 * 16, 100 * 16)
        p.drawArc(int(s * .40), int(s * .20), int(s * .42), int(s * .60), -50 * 16, 100 * 16)
        p.setPen(pen)
    elif kind == "prev":
        path.moveTo(s * .78, s * .24)
        path.lineTo(s * .38, s * .50)
        path.lineTo(s * .78, s * .76)
        path.addRoundedRect(s * .23, s * .24, s * .11, s * .52, 2, 2)
    p.drawPath(path)
    p.end()
    pm.setDevicePixelRatio(2)
    return QIcon(pm)


def encodable(p):
    try:
        p.encode("utf-8")   # a lone surrogate in a name makes mpv's loadfile raise
        return True
    except UnicodeEncodeError:
        return False


def dirs_alive(paths, seconds):
    """{path: reachable} for many folders at once, all checked in parallel with one shared deadline."""
    res = {}
    threads = []
    for p in paths:
        t = threading.Thread(target=lambda p=p: res.__setitem__(p, os.path.isdir(p)), daemon=True)
        t.start()
        threads.append(t)
    end = time.monotonic() + seconds
    for t in threads:
        t.join(max(0.0, end - time.monotonic()))
    return {p: bool(res.get(p)) for p in paths}


def isdir_within(path, seconds):
    """os.path.isdir on a thread; False if it doesn't answer in time (offline network drive)."""
    res = []
    t = threading.Thread(target=lambda: res.append(os.path.isdir(path)), daemon=True)
    t.start()
    t.join(seconds)
    return bool(res and res[0])


class Window(QMainWindow):
    def __init__(self, start_arg=None):
        super().__init__()
        self.setWindowTitle(f"{APP} {VERSION}")
        self.settings = QSettings(APP, APP)
        self.cwd = None
        self.history, self.hist_pos = [], -1
        self.queue = []
        self.cur_path = None
        self.playlist = None     # name of the open playlist, or None in folder view
        self.compact_from = None  # (geometry, was_maximized) while compact
        self.theme = themes.get(self.settings.value("skin", themes.DEFAULT))

        # --- folder tree
        self.fs = QFileSystemModel()
        self.fs.setFilter(QDir.AllDirs | QDir.NoDotAndDotDot | QDir.Drives)
        self.fs.setRootPath("")
        self.tree = QTreeView()
        self.tree.setModel(self.fs)
        for col in (1, 2, 3):
            self.tree.hideColumn(col)
        self.tree.setHeaderHidden(True)
        self.tree.clicked.connect(lambda ix: self.navigate(self.fs.filePath(ix)))

        # --- file list
        self.model = DirModel()
        self.proxy = SortProxy()
        self.proxy.setSourceModel(self.model)
        self.list = QTreeView()
        self.list.setModel(self.proxy)
        self.list.setRootIsDecorated(False)
        self.list.setUniformRowHeights(True)
        self.list.setSortingEnabled(True)
        self.list.setAlternatingRowColors(True)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.context_menu)
        self.list.doubleClicked.connect(self.activate)
        self.list.setDragEnabled(True)
        self.list.setAcceptDrops(True)
        self.list.setDropIndicatorShown(True)
        self.list.setDragDropMode(QAbstractItemView.DragDrop)
        self.list.setDefaultDropAction(Qt.CopyAction)
        self.list.sortByColumn(0, Qt.AscendingOrder)
        self.model.edited.connect(self.playlist_edited)
        hdr = self.list.header()
        hdr.setSectionResizeMode(0, QHeaderView.Interactive)
        hdr.resizeSection(0, 420)
        hdr.resizeSection(1, 110)
        hdr.resizeSection(2, 70)
        hdr.resizeSection(3, 90)
        self.status_timer = QTimer(self, singleShot=True, interval=0, timeout=self.update_status)
        self.proxy.layoutChanged.connect(self.status_timer.start)   # coalesced: one count per burst of re-sorts
        self.model.durs.finished.connect(self.lengths_filled)
        self.queue_dir = None

        # --- toolbar row
        self.btn_back = self.tool(QStyle.SP_ArrowBack, "Back (Alt+Left)", self.go_back)
        self.btn_fwd = self.tool(QStyle.SP_ArrowForward, "Forward (Alt+Right)", self.go_fwd)
        self.btn_up = self.tool(QStyle.SP_ArrowUp, "Up (Backspace)", self.go_up)
        self.addr = QLineEdit()
        self.addr.returnPressed.connect(lambda: self.navigate(self.addr.text().strip().strip('"')))
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter (Ctrl+F)")
        self.filter.setClearButtonEnabled(True)
        self.filter.setFixedWidth(240)
        self.filter.textChanged.connect(self.apply_filter)
        top = QHBoxLayout()
        for w in (self.btn_back, self.btn_fwd, self.btn_up):
            top.addWidget(w)
        top.addWidget(self.addr, 1)
        top.addWidget(self.filter)

        # --- video pane
        self.video = QWidget()
        self.video.setAttribute(Qt.WA_DontCreateNativeAncestors)
        self.video.setAttribute(Qt.WA_NativeWindow)
        self.video.setStyleSheet("background:#000;")
        self.video.setMinimumHeight(160)
        self.vsplit = QSplitter(Qt.Vertical)
        self.vsplit.addWidget(self.video)
        self.vsplit.addWidget(self.list)
        self.vsplit.setSizes([420, 500])
        self.video.hide()

        # --- playlists panel (under the folder tree)
        self.pl_list = playlists.PlaylistList()
        self.pl_list.itemClicked.connect(lambda it: self.open_playlist(it.data(Qt.UserRole)))
        self.pl_list.itemChanged.connect(self.playlist_renamed)
        self.pl_list.filesDropped.connect(self.add_to_playlist)
        self.pl_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.pl_list.customContextMenuRequested.connect(self.playlist_menu)
        pl_head = QHBoxLayout()
        pl_head.setContentsMargins(4, 4, 4, 0)
        pl_title = QLabel("Playlists")
        pl_title.setObjectName("now")
        pl_head.addWidget(pl_title, 1)
        self.btn_new_pl = QToolButton()
        self.btn_new_pl.setText("+")
        self.btn_new_pl.setToolTip("New playlist (drag files from the list onto a playlist to add them)")
        self.btn_new_pl.setAutoRaise(True)
        self.btn_new_pl.clicked.connect(lambda: self.new_playlist())
        pl_head.addWidget(self.btn_new_pl)
        pl_panel = QWidget()
        pl_lay = QVBoxLayout(pl_panel)
        pl_lay.setContentsMargins(0, 0, 0, 0)
        pl_lay.setSpacing(2)
        pl_lay.addLayout(pl_head)
        pl_lay.addWidget(self.pl_list)
        self.left = QSplitter(Qt.Vertical)
        self.left.addWidget(self.tree)
        self.left.addWidget(pl_panel)
        self.left.setSizes([600, 220])
        self.pl_list.refresh()

        self.hsplit = QSplitter(Qt.Horizontal)
        self.hsplit.addWidget(self.left)
        self.hsplit.addWidget(self.vsplit)
        self.hsplit.setSizes([260, 1100])

        # --- player bar
        self.icons = {k: glyph(k) for k in ("play", "pause", "stop", "next", "prev")}
        self.btn_prev = self.tbtn(self.icons["prev"], "Previous (Ctrl+Left)", self.prev)
        self.btn_play = self.tbtn(self.icons["play"], "Play / Pause (Space)", self.play_pause)
        self.btn_next = self.tbtn(self.icons["next"], "Next (Ctrl+Right)", self.next)
        self.btn_stop = self.tbtn(self.icons["stop"], "Stop", self.stop)
        self.btn_play.setIconSize(self.btn_play.iconSize() * 1.25)
        self.btn_video = QToolButton()
        self.btn_video.setText("Video")
        self.btn_video.setCheckable(True)
        self.btn_video.setToolTip("Show / hide the video pane (V)")
        self.btn_video.toggled.connect(self.video_toggled)
        self.btn_full = QToolButton()
        self.btn_full.setText("Fullscreen")
        self.btn_full.setToolTip("Fullscreen video (F, Esc to exit)")
        self.btn_full.clicked.connect(self.toggle_full)
        self.btn_compact = QToolButton()
        self.btn_compact.setText("COMPACT")
        self.btn_compact.setToolTip("Small player without the explorer (Esc to come back)")
        self.btn_compact.clicked.connect(self.toggle_compact)
        self.full_hidden = None
        self.vdims = None        # (w, h) of the current video, rotation applied
        self.vdims_path = None
        self.now = QLabel("Nothing playing")
        self.now.setObjectName("now")
        self.t_pos = QLabel("0:00")
        self.t_dur = QLabel("0:00")
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setFixedWidth(110)
        self.vol.valueChanged.connect(self.set_volume)
        self.btn_mode = QPushButton("Classic")
        self.btn_mode.setObjectName("chip")
        self.btn_mode.setToolTip("Waveform view (W): Classic / Bars / Spectrum / Bars + Spectrum / Spectrogram / Stereo")
        self.btn_skin = QPushButton("Skin")
        self.btn_skin.setObjectName("chip")
        skin_menu = QMenu(self)
        for name in themes.THEMES:
            skin_menu.addAction(name, lambda n=name: self.set_skin(n))
        self.btn_skin.setMenu(skin_menu)

        row1 = QHBoxLayout()
        row1.addWidget(self.now, 1)
        row1.addWidget(self.btn_mode)
        row1.addWidget(self.btn_skin)
        row1.addWidget(self.btn_video)
        row1.addWidget(self.btn_full)
        row1.addWidget(self.btn_compact)
        row2 = QHBoxLayout()
        for b in (self.btn_prev, self.btn_play, self.btn_next, self.btn_stop):
            row2.addWidget(b)
        row2.addSpacing(10)
        row2.addWidget(self.t_pos)
        row2.addWidget(QLabel("/"))
        row2.addWidget(self.t_dur)
        row2.addStretch(1)
        vol_icon = QLabel()
        vol_icon.setPixmap(glyph("vol", "#c9ced6", 12).pixmap(22, 22))
        row2.addWidget(vol_icon)
        row2.addWidget(self.vol)
        bar = QWidget()
        bar.setObjectName("bar")
        bl = QVBoxLayout(bar)
        bl.setContentsMargins(10, 6, 10, 6)
        bl.setSpacing(4)
        bl.addLayout(row1)
        bl.addLayout(row2)
        self.bar = bar
        self.bar_layout = bl

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(6, 6, 6, 0)
        top.setContentsMargins(0, 0, 0, 0)
        self.topbar = QWidget()
        self.topbar.setLayout(top)
        lay.addWidget(self.topbar)
        self.main_layout = lay
        lay.addWidget(self.hsplit, 1)
        lay.addWidget(bar)
        self.setCentralWidget(central)

        # --- mpv
        self.player = mpv.MPV(wid=str(int(self.video.winId())), input_default_bindings=False,
                              input_vo_keyboard=False, osc=False, idle="yes", keep_open="no",
                              gapless_audio="weak", ytdl=False)
        self.wave = WaveView(self.player)
        self.wave.set_theme(self.theme)
        self.wave.seekRequested.connect(self.seek_to)
        self.wave.modeChanged.connect(self.mode_changed)
        self.bar_layout.insertWidget(1, self.wave)
        self.btn_mode.clicked.connect(self.wave.cycle)
        self.wave.set_mode(self.settings.value("wave_mode", MODES[0]))
        self.analyzer = Analyzer(HERE)
        self.analyzer.progress.connect(self.wave.set_analysis)
        self.model.accent = QColor(self.theme["accent"])

        # --- shortcuts
        self.list.installEventFilter(self)
        QShortcut(QKeySequence("Ctrl+F"), self, lambda: (self.filter.setFocus(), self.filter.selectAll()))
        QShortcut(QKeySequence("Alt+Left"), self, self.go_back)
        QShortcut(QKeySequence("Alt+Right"), self, self.go_fwd)
        QShortcut(QKeySequence("Ctrl+L"), self, lambda: (self.addr.setFocus(), self.addr.selectAll()))
        QShortcut(QKeySequence("Ctrl+Right"), self, self.next)
        QShortcut(QKeySequence("Ctrl+Left"), self, self.prev)
        QShortcut(QKeySequence("Escape"), self, self.escape)   # one Esc shortcut: two would cancel each other out
        QShortcut(QKeySequence("F"), self, self.toggle_full)
        QShortcut(QKeySequence("F11"), self, self.toggle_full)
        QShortcut(QKeySequence("Space"), self, self.play_pause)

        # --- restore
        geo = self.settings.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        else:
            self.resize(1400, 860)
        for key, sp in (("hsplit", self.hsplit), ("vsplit", self.vsplit), ("lsplit", self.left)):
            st = self.settings.value(key)
            if st:
                sp.restoreState(st)
        hs = self.settings.value("header5")   # 5 columns since Length was added; old 4-column state is ignored
        if hs:
            hdr.restoreState(hs)
        try:
            self.vol.setValue(int(self.settings.value("volume", 80)))
        except (TypeError, ValueError):
            self.vol.setValue(80)
        self.set_volume(self.vol.value())   # setValue(0) emits nothing on a fresh slider, and mpv starts at 100

        self.timer = QTimer(self, interval=200, timeout=self.poll)
        self.timer.start()
        self.show_media_buttons(None)

        start_file = None
        if start_arg and os.path.isfile(start_arg):
            start_file = os.path.abspath(start_arg)
            start_dir = os.path.dirname(start_file)
        elif start_arg and os.path.isdir(start_arg):
            start_dir = start_arg
        else:
            start_dir = self.settings.value("last_dir") or os.path.expanduser("~")
            if not isdir_within(start_dir, 2.0):   # an offline NAS would block startup for 20+ s
                start_dir = os.path.expanduser("~")
        self.navigate(start_dir)
        if start_file:
            self.play_view(start_file)

    def escape(self):
        if self.full_hidden is not None:
            self.toggle_full()
        elif self.compact_from is not None:
            self.toggle_compact()
        elif self.filter.hasFocus():
            self.filter.clear()
            self.list.setFocus()

    def open_remote(self, arg):
        """A second launch (e.g. double-clicking a file in Windows Explorer) hands its file here
        instead of starting another player."""
        if self.full_hidden is not None:
            self.toggle_full()
        if self.compact_from is not None and arg and os.path.isdir(arg):
            self.toggle_compact()   # a folder needs the explorer
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowMinimized)   # keeps "maximized"
        self.raise_()
        self.activateWindow()
        if arg and os.path.isfile(arg):
            path = os.path.abspath(arg)
            self.filter.clear()   # a filtered view might not contain the file
            self.navigate(os.path.dirname(path))
            self.play_view(path)
        elif arg and os.path.isdir(arg):
            self.navigate(arg)

    # ---------- helpers
    def tbtn(self, icon, tip, fn):
        b = QToolButton()
        b.setIcon(icon)
        b.setIconSize(b.iconSize() * 1.5)
        b.setToolTip(tip)
        b.setAutoRaise(True)
        b.clicked.connect(fn)
        return b

    def set_skin(self, name):
        self.theme = themes.get(name)
        themes.apply(QApplication.instance(), self.theme)
        self.wave.set_theme(self.theme)
        self.model.accent = QColor(self.theme["accent"])
        if self.model.entries:
            self.model.dataChanged.emit(self.model.index(0, 0), self.model.index(len(self.model.entries) - 1, 0))
        self.settings.setValue("skin", self.theme["name"])
        self.statusBar().showMessage(f"Skin: {self.theme['name']}", 3000)

    def mode_changed(self, mode):
        self.btn_mode.setText(mode)
        self.settings.setValue("wave_mode", mode)

    def tool(self, icon, tip, fn):
        b = QToolButton()
        b.setIcon(self.style().standardIcon(icon))
        b.setToolTip(tip)
        b.setAutoRaise(True)
        b.clicked.connect(fn)
        return b

    def entry_at(self, proxy_index):
        return self.model.entries[self.proxy.mapToSource(proxy_index).row()]

    def view_entries(self):
        return [self.entry_at(self.proxy.index(r, 0)) for r in range(self.proxy.rowCount())]

    # ---------- navigation
    def navigate(self, path, record=True):
        if not path or not os.path.isdir(path):
            self.statusBar().showMessage(f"Not a folder: {path}", 4000)
            return
        if len(path) == 2 and path[1] == ":":
            path += "\\"   # "C:" alone means "the current folder on C:" to Windows; the user means the drive
        path = os.path.normpath(os.path.abspath(path))
        self.leave_playlist()
        err = self.model.load(path)
        self.cwd = path
        self.addr.setText(path)
        if record:
            del self.history[self.hist_pos + 1:]
            if not self.history or self.history[-1] != path:
                self.history.append(path)
            self.hist_pos = len(self.history) - 1
        ix = self.fs.index(path)
        if ix.isValid():
            self.tree.setCurrentIndex(ix)
            self.tree.scrollTo(ix)
        self.list.scrollToTop()
        if self.proxy.rowCount():
            self.list.setCurrentIndex(self.proxy.index(0, 0))
        self.update_status()
        if err:
            self.statusBar().showMessage(err, 6000)

    def go_back(self):
        if self.hist_pos > 0:
            self.hist_pos -= 1
            self.navigate(self.history[self.hist_pos], record=False)

    def go_fwd(self):
        if self.hist_pos < len(self.history) - 1:
            self.hist_pos += 1
            self.navigate(self.history[self.hist_pos], record=False)

    def go_up(self):
        if self.playlist:
            self.navigate(self.cwd, record=False)   # Up from a playlist: back to the folder
            return
        if self.cwd:
            parent = os.path.dirname(self.cwd)   # cwd is normalized; at a drive root this is the root again
            if parent and parent != self.cwd:
                child = self.cwd
                self.navigate(parent)
                for r in range(self.proxy.rowCount()):
                    if os.path.normcase(self.entry_at(self.proxy.index(r, 0)).path) == os.path.normcase(child.rstrip("\\")):
                        self.list.setCurrentIndex(self.proxy.index(r, 0))
                        self.list.scrollTo(self.proxy.index(r, 0))
                        break

    def apply_filter(self, text):
        self.proxy.text = unicodedata.normalize("NFC", text).casefold()
        self.proxy.invalidateFilter()
        self.update_status()

    def update_status(self):
        ents = self.view_entries()
        media = sum(1 for e in ents if e.media)
        self.statusBar().showMessage(f"{len(ents)} items  ·  {media} playable")

    # ---------- list actions
    def activate(self, ix):
        self.open_entry(self.entry_at(ix))

    def open_entry(self, e):
        if e.missing:
            self.statusBar().showMessage(f"Can't open {e.path}: {e.why}", 6000)
        elif e.is_dir:
            self.navigate(e.path)
        elif e.media:
            self.play_view(e.path, e)
        else:
            os.startfile(e.path)

    def context_menu(self, pos):
        ix = self.list.indexAt(pos)
        m = QMenu(self)
        if ix.isValid():
            e = self.entry_at(ix)
            if e.media:
                m.addAction("Play from here", lambda: self.play_view(e.path, e))
            m.addAction("Open", lambda: self.open_entry(e))   # e, not ix: rows can re-sort while the menu is open
            m.addAction("Show in Explorer", lambda: subprocess.Popen(f'"{WINDIR}\\explorer.exe" /select,"{e.path}"'))
            m.addAction("Copy Full Path", lambda: QApplication.clipboard().setText(
                "\n".join(self.entry_at(i).path for i in self.list.selectionModel().selectedRows()) or e.path))
            m.addSeparator()
        if self.playlist:
            if ix.isValid():
                m.addAction("Remove from playlist", self.remove_selected)
            m.addAction("Play playlist", lambda: self.play_view(None))
            m.addAction("Refresh", lambda: self.open_playlist(self.playlist))
        else:
            m.addAction("Play all (sort order)", lambda: self.play_view(None))
            m.addAction("Refresh", lambda: self.navigate(self.cwd, record=False))
            sel = [self.entry_at(i).path for i in self.list.selectionModel().selectedRows()
                   if self.entry_at(i).media] or ([e.path] if ix.isValid() and e.media else [])
            names_ = playlists.names()
            if sel and names_:
                sub = m.addMenu("Add to playlist")
                for n in names_:
                    sub.addAction(n, lambda n=n: self.add_to_playlist(n, sel))
        m.exec(self.list.viewport().mapToGlobal(pos))

    def eventFilter(self, obj, ev):
        if obj is self.list and ev.type() == ev.Type.KeyPress:
            k = ev.key()
            if k in (Qt.Key_Return, Qt.Key_Enter):
                ix = self.list.currentIndex()
                if ix.isValid():
                    self.activate(ix)
                return True
            if k == Qt.Key_Backspace:
                self.go_up()
                return True
            if k == Qt.Key_Delete and self.playlist:
                self.remove_selected()
                return True
            if k == Qt.Key_Space and ev.modifiers() == Qt.NoModifier:   # Ctrl+Space toggles the selection
                self.play_pause()
                return True
            if k == Qt.Key_V:
                self.btn_video.toggle()
                return True
            if k == Qt.Key_W:
                self.wave.cycle()
                return True
            if k == Qt.Key_Right and ev.modifiers() == Qt.ShiftModifier:
                self.player.command("seek", 10)
                return True
            if k == Qt.Key_Left and ev.modifiers() == Qt.ShiftModifier:
                self.player.command("seek", -10)
                return True
        return super().eventFilter(obj, ev)

    # ---------- playback
    def play_view(self, start_path, entry=None):
        """Queue every playable file in the current view, in its current sort order. entry, when given, is the
        exact row to start from (a playlist can hold the same file twice)."""
        ents = [e for e in self.view_entries() if e.media and encodable(e.path)]
        paths = [e.path for e in ents]
        if not paths:
            self.statusBar().showMessage("Nothing playable in this view", 4000)
            return
        norm = [os.path.normcase(p) for p in paths]
        want = os.path.normcase(start_path) if start_path else None
        if want and want not in norm:   # never play a different file than the one asked for
            self.statusBar().showMessage(f"Can't play {os.path.basename(start_path)}", 6000)
            return
        same = [i for i, e in enumerate(ents) if e is entry]
        start = same[0] if same else (norm.index(want) if want else 0)
        self.queue = paths
        self.queue_dir = self.view_id()
        self.player.command("stop")
        for p in paths:
            self.player.command("loadfile", p, "append")
        self.player.playlist_pos = start
        self.player.pause = False
        if os.path.splitext(paths[start])[1][1:].lower() in VIDEO:
            self.btn_video.setChecked(True)

    def lengths_filled(self, gen):
        """Sorted by Length, a queue made before the lengths arrived is in the wrong order: once the
        folder's lengths are in, rebuild mpv's playlist around the playing track in the view's order."""
        if gen != self.model.durs.gen or self.proxy.sortColumn() != 2 or self.queue_dir != self.view_id():
            return
        try:
            idx = None if self.player.idle_active else self.player.playlist_pos
        except Exception:
            return
        if idx is None or not 0 <= idx < len(self.queue):
            return
        new = [e.path for e in self.view_entries() if e.media and encodable(e.path)]
        if new == self.queue or sorted(new) != sorted(self.queue):
            return
        cur = self.queue[idx]
        self.player.command("playlist-clear")   # keeps the playing entry, now at 0
        for p in new:
            if p != cur:
                self.player.command("loadfile", p, "append")
        k = new.index(cur)
        if k:
            self.player.command("playlist-move", 0, k + 1)
        self.queue = new

    def view_id(self):
        return ("playlist", self.playlist) if self.playlist else self.cwd

    # ---------- compact mode
    def show_media_buttons(self, path):
        video = bool(path) and os.path.splitext(path)[1][1:].lower() in VIDEO
        self.btn_video.setVisible(video)
        self.btn_full.setVisible(video)
        self.btn_compact.setVisible(not video or self.compact_from is not None)

    def toggle_compact(self):
        if self.compact_from is None:
            self.compact_from = (self.normalGeometry(), self.isMaximized())
            self.btn_video.setChecked(False)
            for w in (self.topbar, self.hsplit, self.statusBar()):
                w.hide()
            self.btn_compact.setText("FULL")
            self.btn_compact.setToolTip("Back to the full window (Esc)")
            self.showNormal()
            geo = self.settings.value("compact_geo")
            if geo:
                self.restoreGeometry(geo)
            else:
                self.resize(560, 10)   # the layout's minimum height wins
            self.setMinimumWidth(420)
        else:
            self.settings.setValue("compact_geo", self.saveGeometry())
            geo, was_max = self.compact_from
            self.compact_from = None
            self.setMinimumWidth(0)
            for w in (self.topbar, self.hsplit, self.statusBar()):
                w.show()
            self.btn_compact.setText("COMPACT")
            self.btn_compact.setToolTip("Small player without the explorer (Esc to come back)")
            self.setGeometry(geo)
            if was_max:
                self.showMaximized()
            self.show_media_buttons(self.cur_path)

    # ---------- playlists
    def leave_playlist(self):
        if not self.playlist:
            return
        self.playlist = None
        self.pl_list.clearSelection()
        self.list.setSortingEnabled(True)
        col, order = getattr(self, "folder_sort", (0, Qt.AscendingOrder))
        self.list.sortByColumn(col, order)

    def open_playlist(self, name):
        path = playlists.path_for(name)
        try:
            paths = playlists.read(path)
        except OSError as e:
            self.statusBar().showMessage(f"Can't open {name}: {e.strerror or e}", 8000)
            self.pl_list.refresh(select=self.playlist)
            if self.playlist is None:
                self.pl_list.setCurrentItem(None)
            return False
        if not self.playlist:
            self.folder_sort = (self.proxy.sortColumn(), self.proxy.sortOrder())
        self.playlist = name
        self.list.setSortingEnabled(False)
        self.proxy.sort(-1)   # playlist order
        self.model.load_playlist(paths)
        self.addr.setText(f"Playlist: {name}")
        it = self.pl_list.item_named(name)
        if it:
            self.pl_list.setCurrentItem(it)
        self.list.scrollToTop()
        self.update_status()
        return True

    def playlist_edited(self):
        if self.playlist:
            try:
                playlists.write(playlists.path_for(self.playlist), self.model.paths())
            except OSError as e:
                self.statusBar().showMessage(f"Couldn't save playlist: {e}", 8000)
            self.status_timer.start()

    def add_to_playlist(self, name, files):
        if self.playlist == name:
            n = self.model.insert_paths(len(self.model.entries), files)
        else:
            files = [f for f in files if os.path.splitext(f)[1][1:].lower() in MEDIA and encodable(f)]
            path = playlists.path_for(name)
            n = len(files)
            if n:
                try:
                    playlists.write(path, playlists.read(path) + files)
                except OSError as e:   # never write over a playlist that couldn't be read
                    self.statusBar().showMessage(f"Couldn't add to {name}: {e.strerror or e}", 8000)
                    return 0
        self.statusBar().showMessage(f"Added {n} to {name}" if n else "Only audio and video files can go in a playlist", 4000)
        return n

    def remove_selected(self):
        if self.playlist:
            self.model.remove_rows([self.proxy.mapToSource(i).row() for i in self.list.selectionModel().selectedRows()])

    def new_playlist(self, name="New playlist", edit=True):
        name = playlists.unique(playlists.clean_name(name) or "New playlist")
        try:
            playlists.write(playlists.path_for(name), [])
        except OSError as e:
            self.statusBar().showMessage(f"Couldn't create the playlist: {e.strerror or e}", 8000)
            return None
        self.pl_list.refresh(select=name)
        self.open_playlist(name)
        it = self.pl_list.item_named(name)
        if edit and it:
            self.pl_list.editItem(it)
        return name

    def playlist_renamed(self, item):
        old, new = item.data(Qt.UserRole), playlists.clean_name(item.text())
        self.rename_playlist(old, new)

    def rename_playlist(self, old, new):
        new = playlists.clean_name(new)
        src = playlists.path_for(old)
        if not new or new == old:
            self.pl_list.refresh(select=old)
            return old
        if os.path.exists(playlists.path_for(new)) and os.path.normcase(new) != os.path.normcase(old):
            self.statusBar().showMessage(f"A playlist called {new} already exists", 5000)
            self.pl_list.refresh(select=old)
            return old
        try:
            os.replace(src, playlists.path_for(new))
        except OSError as e:
            self.statusBar().showMessage(f"Couldn't rename: {e}", 6000)
            self.pl_list.refresh(select=old)
            return old
        if self.playlist == old:
            self.playlist = new
            self.addr.setText(f"Playlist: {new}")
        if self.queue_dir == ("playlist", old):
            self.queue_dir = ("playlist", new)
        self.pl_list.refresh(select=new)
        return new

    def duplicate_playlist(self, name):
        new = playlists.unique(f"{name} copy")
        try:
            playlists.write(playlists.path_for(new), playlists.read(playlists.path_for(name)))
        except OSError as e:
            self.statusBar().showMessage(f"Couldn't duplicate {name}: {e.strerror or e}", 8000)
            return None
        self.pl_list.refresh(select=new)
        return new

    def delete_playlist(self, name):
        if not playlists.recycle(playlists.path_for(name), int(self.winId())):
            self.statusBar().showMessage(f"{name} was not deleted", 6000)
            return False
        if self.playlist == name:
            self.leave_playlist()   # first, so no later edit can write the deleted playlist back
            back = self.cwd if self.cwd and isdir_within(self.cwd, 2.0) else os.path.expanduser("~")
            self.navigate(back, record=False)
        self.pl_list.refresh()
        self.statusBar().showMessage(f"{name} deleted", 4000)
        return True

    def export_playlist(self, name, target=None):
        if target is None:
            target, _ = QFileDialog.getSaveFileName(self, "Export playlist", os.path.join(
                os.path.expanduser("~"), name + ".m3u8"), "Playlist (*.m3u8)")
        if target:
            try:
                playlists.write(target, playlists.read(playlists.path_for(name)))
            except OSError as e:
                self.statusBar().showMessage(f"Couldn't export {name}: {e.strerror or e}", 8000)
                return None
            self.statusBar().showMessage(f"Exported {name} to {target}", 5000)
        return target

    def copy_playlist_files(self, name, dest=None):
        if dest is None:
            dest = QFileDialog.getExistingDirectory(self, f"Copy the files of {name} to")
        if not dest:
            return None
        if getattr(self, "copying", False):
            self.statusBar().showMessage("A copy is already running", 4000)
            return None
        try:
            paths = [p for p in playlists.read(playlists.path_for(name)) if "://" not in p]
        except OSError as e:
            self.statusBar().showMessage(f"Can't read {name}: {e.strerror or e}", 8000)
            return None
        self.copying = True
        self.statusBar().showMessage(f"Copying {len(paths)} files...")
        res = {}

        def work():
            res["r"] = playlists.copy_tracks(paths, dest)
        t = threading.Thread(target=work, daemon=True)
        t.start()
        try:
            while t.is_alive():   # keeps the window painting; self.copying blocks a second copy meanwhile
                QApplication.processEvents()
                t.join(0.05)
        finally:
            self.copying = False
        copied, missing, failed = res.get("r", (0, 0, len(paths)))
        msg = f"Copied {copied} file(s) to {dest}"
        if missing:
            msg += f", {missing} missing"
        if failed:
            msg += f", {failed} failed (disk full or no access?)"
        self.statusBar().showMessage(msg, 10000)
        return copied, missing, failed

    def play_playlist(self, name):
        if self.open_playlist(name):
            self.play_view(None)

    def playlist_menu(self, pos):
        it = self.pl_list.itemAt(pos)
        m = QMenu(self)
        if it:
            n = it.data(Qt.UserRole)
            m.addAction("Play", lambda: self.play_playlist(n))
            m.addAction("Rename", lambda: self.pl_list.editItem(it))
            m.addAction("Duplicate", lambda: self.duplicate_playlist(n))
            m.addAction("Export as .m3u8...", lambda: self.export_playlist(n))
            m.addAction("Copy files to folder...", lambda: self.copy_playlist_files(n))
            m.addSeparator()
            m.addAction("Delete (to Recycle Bin)", lambda: self.delete_playlist(n))
            m.addSeparator()
        m.addAction("New playlist", lambda: self.new_playlist())
        m.exec(self.pl_list.viewport().mapToGlobal(pos))

    def video_toggled(self, on):
        self.video.setVisible(on)
        if on:
            QTimer.singleShot(0, lambda: self.apply_video_layout(*(self.vdims or (16, 9))))

    def apply_video_layout(self, vw, vh):
        """Vertical video: tall column right of the list. Wide/square: pane above the list.
        The video widget only changes position inside the same splitter, so mpv's window handle survives."""
        if not self.video.isVisible() or self.full_hidden is not None:
            return
        sp = self.vsplit
        portrait = vh > vw * 1.15
        if portrait:
            if sp.orientation() != Qt.Horizontal:
                sp.setOrientation(Qt.Horizontal)
            sp.insertWidget(1, self.video)   # always: a restored splitter state can start in either order
            total = sum(sp.sizes()) or sp.width()
            want = int(sp.height() * vw / vh)
            size = max(200, min(want, int(total * 0.6)))
            sp.setSizes([total - size, size])
        else:
            if sp.orientation() != Qt.Vertical:
                sp.setOrientation(Qt.Vertical)
            sp.insertWidget(0, self.video)
            total = sum(sp.sizes()) or sp.height()
            want = int(sp.width() * vh / vw)
            size = max(160, min(want, int(total * 0.68)))
            sp.setSizes([size, total - size])

    def read_video_dims(self):
        try:
            vp = self.player.video_params
        except Exception:
            return None
        if not vp or not vp.get("dw") or not vp.get("dh"):
            return None
        w, h = int(vp["dw"]), int(vp["dh"])
        if int(vp.get("rotate") or 0) % 180 == 90:
            w, h = h, w
        return w, h

    def toggle_full(self):
        """Fullscreen keeps the same native video window (mpv draws into it), just hides the rest."""
        if self.full_hidden is not None:
            for w in self.full_hidden:
                w.show()
            self.full_hidden = None
            self.main_layout.setContentsMargins(6, 6, 6, 0)
            self.showMaximized() if self.was_max else self.showNormal()
            self.list.setFocus()
            if self.vdims:
                QTimer.singleShot(50, lambda: self.apply_video_layout(*self.vdims))
            return
        was_max = self.compact_from[1] if self.compact_from is not None else self.isMaximized()
        if self.compact_from is not None:
            self.toggle_compact()
        self.was_max = was_max
        if not self.btn_video.isChecked():
            self.btn_video.setChecked(True)
        self.full_hidden = [w for w in (self.topbar, self.left, self.list, self.bar, self.statusBar()) if w.isVisible()]
        for w in self.full_hidden:
            w.hide()
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.showFullScreen()
        self.setFocus()

    def play_pause(self):
        if self.player.idle_active:
            cur = self.list.currentIndex()
            e = self.entry_at(cur) if cur.isValid() else None
            self.play_view(e.path if e and e.media else None, e)
        else:
            self.player.pause = not self.player.pause

    def stop(self):
        self.player.command("stop")
        self.queue = []
        self.model.set_playing(None)

    def next(self):
        try:
            self.player.playlist_next()
        except SystemError:
            pass

    def prev(self):
        try:
            if (self.player.time_pos or 0) > 3:
                self.player.seek(0, "absolute")
            else:
                self.player.playlist_prev()
        except SystemError:
            pass

    def seek_to(self, sec):
        try:
            if not self.player.idle_active:
                self.player.seek(sec, "absolute")
        except SystemError:
            pass

    def set_volume(self, v):
        self.player.volume = v
        self.vol.setToolTip(f"Volume {v}%")

    def poll(self):
        p = self.player
        try:
            idle = p.idle_active
            pos = None if idle else p.time_pos
            dur = None if idle else p.duration
            paused = p.pause
            idx = None if idle else p.playlist_pos
        except Exception:
            return
        self.btn_play.setIcon(self.icons["play" if (idle or paused) else "pause"])
        path = self.queue[idx] if idx is not None and 0 <= idx < len(self.queue) else None
        self.model.set_playing(path)
        if path != self.cur_path:
            self.cur_path = path
            self.wave.set_track(path)
            self.show_media_buttons(path)
            if path:
                self.analyzer.request(path)
                if os.path.splitext(path)[1][1:].lower() in VIDEO:
                    if self.compact_from is not None:
                        self.toggle_compact()   # video needs the big window
                    if not self.btn_video.isChecked():
                        self.btn_video.setChecked(True)   # only on a new track, so V can still hide it
                elif self.btn_video.isChecked() and self.full_hidden is None:
                    self.btn_video.setChecked(False)   # audio: no empty black pane
        if path:
            name = os.path.basename(path)
            self.now.setText(f"{name}    ({idx + 1} / {len(self.queue)})")
            self.setWindowTitle(f"{name} - {APP}")
            if os.path.splitext(path)[1][1:].lower() in VIDEO:
                if self.vdims_path != path:
                    dims = self.read_video_dims()
                    if dims:
                        self.vdims, self.vdims_path = dims, path
                        self.apply_video_layout(*dims)
        else:
            self.now.setText("Nothing playing")
            self.setWindowTitle(f"{APP} {VERSION}")
        self.t_pos.setText(fmt_time(pos))
        self.t_dur.setText(fmt_time(dur))

    def closeEvent(self, ev):
        if self.full_hidden is not None:
            self.toggle_full()   # save the normal window, not the fullscreen one
        if self.compact_from is not None:
            self.toggle_compact()
        self.leave_playlist()   # save the folder view's sortable header, not the playlist's
        s = self.settings
        s.setValue("geometry", self.saveGeometry())
        s.setValue("hsplit", self.hsplit.saveState())
        s.setValue("vsplit", self.vsplit.saveState())
        s.setValue("lsplit", self.left.saveState())
        s.setValue("header5", self.list.header().saveState())
        s.setValue("volume", self.vol.value())
        if self.cwd:
            s.setValue("last_dir", self.cwd)
        self.timer.stop()
        self.wave.timer.stop()
        self.analyzer.job = None
        self.player.terminate()
        super().closeEvent(ev)


def install_error_log():
    """pythonw has no console, so unhandled errors go to %LOCALAPPDATA%\\Cratedig\\error.log."""
    import traceback
    d = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Cratedig")
    os.makedirs(d, exist_ok=True)
    log = os.path.join(d, "error.log")

    def hook(et, ev, tb):
        with open(log, "a", encoding="utf-8") as f:
            f.write(time.strftime("\n[%Y-%m-%d %H:%M:%S]\n") + "".join(traceback.format_exception(et, ev, tb)))
    sys.excepthook = hook


SERVER = f"{APP}-{os.environ.get('USERNAME', 'user')}"


def hand_off(arg):
    """If Cratedig is already running, pass it our file or folder and return True."""
    sock = QLocalSocket()
    sock.connectToServer(SERVER)
    if not sock.waitForConnected(500):
        return False
    try:
        import ctypes
        ctypes.windll.user32.AllowSetForegroundWindow(-1)   # let the running window come to the front
    except Exception:
        pass
    sock.write((os.path.abspath(arg) if arg else "").encode("utf-8", "surrogatepass") + b"\n")
    sock.flush()
    if sock.bytesToWrite():
        sock.waitForBytesWritten(5000)   # with nothing pending it would just sit out the timeout
    deadline = time.monotonic() + 5   # the window confirms it took the file
    while sock.bytesAvailable() < 2 and time.monotonic() < deadline and sock.state() == QLocalSocket.ConnectedState:
        sock.waitForReadyRead(100)
    ok = bytes(sock.readAll()).startswith(b"1")
    sock.disconnectFromServer()
    return ok


def serve(window):
    server = QLocalServer(window)
    QLocalServer.removeServer(SERVER)   # clears a stale name left by a crash
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)   # an elevated copy stays reachable
    server.listen(SERVER)

    def on_conn():
        conn = server.nextPendingConnection()
        buf = bytearray()

        def read():
            buf.extend(bytes(conn.readAll()))
            if b"\n" in buf:
                arg = buf.split(b"\n", 1)[0].decode("utf-8", "surrogatepass")
                conn.write(b"1\n")   # ack first: opening a big folder can take longer than the sender waits
                conn.flush()   # the sender disconnects once it has read this
                QTimer.singleShot(0, lambda: window.open_remote(arg))
        conn.readyRead.connect(read)
        conn.disconnected.connect(conn.deleteLater)
        if conn.bytesAvailable():
            read()
    server.newConnection.connect(on_conn)
    return server


def claim_instance(app):
    """Create the app mutexes (the uninstaller checks them too). False if another Cratedig holds them."""
    try:
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = ctypes.c_void_p
    except Exception:
        return True
    app.mutexes, first = [], True
    for n in ("CratedigAppMutex", "Global\\CratedigAppMutex"):
        h = k32.CreateMutexW(None, False, n)
        if n == "CratedigAppMutex" and (not h or ctypes.get_last_error() == 183):   # 183 exists; NULL: elevated owner
            first = False
        if h:
            app.mutexes.append(h)
    if not first:   # let go: an open handle would keep the mutex alive after its owner exits
        for h in app.mutexes:
            k32.CloseHandle(ctypes.c_void_p(h))
        app.mutexes = []
    return first


def main():
    install_error_log()
    app = QApplication(sys.argv)
    app.setApplicationName(APP)
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    # One player: the launch that creates the mutex builds the window. Every other launch, even one racing
    # it (3 files opened at once from Explorer), keeps handing off until that window acks (up to 30 s).
    if not claim_instance(app):
        # Keep handing off until a window takes the file. If the holder was a closing Cratedig, its mutex goes
        # away: then this launch becomes the window. 30 s covers a first window that is still starting up.
        deadline = time.monotonic() + 30
        while not hand_off(arg):
            if claim_instance(app):
                break
            if time.monotonic() > deadline:
                sys.exit(1)
            time.sleep(0.1)
        else:
            sys.exit(0)
    ico = os.path.join(HERE, "cratedig.ico")
    if os.path.isfile(ico):
        app.setWindowIcon(QIcon(ico))
    themes.apply(app, themes.get(QSettings(APP, APP).value("skin", themes.DEFAULT)))
    w = Window(arg)
    w.server = serve(w)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
