"""Cratedig v0.1 - file explorer + media player in one window."""
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
LIB = os.path.join(HERE, "lib")
os.environ["PATH"] = LIB + os.pathsep + HERE + os.pathsep + os.environ.get("PATH", "")

import mpv  # noqa: E402
from PySide6.QtCore import (QAbstractTableModel, QDir, QFileInfo, QModelIndex, QSettings,  # noqa: E402
                            QSortFilterProxyModel, Qt, QTimer)
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QShortcut  # noqa: E402
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFileIconProvider,  # noqa: E402
                               QFileSystemModel, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMainWindow, QMenu, QPushButton, QSlider, QSplitter, QStyle,
                               QToolButton, QTreeView, QVBoxLayout, QWidget)

import themes  # noqa: E402
from waveform import MODES, Analyzer, WaveView  # noqa: E402

APP = "Cratedig"
VERSION = "1.0"

AUDIO = {"wav", "mp3", "flac", "aiff", "aif", "m4a", "aac", "ogg", "oga", "opus", "wma", "alac",
         "ape", "wv", "mka", "mid", "midi"}
VIDEO = {"mp4", "mkv", "mov", "avi", "webm", "wmv", "m4v", "flv", "mpg", "mpeg", "ts", "m2ts",
         "3gp", "vob", "ogv"}
MEDIA = AUDIO | VIDEO


def natural_key(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s.casefold())]


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


class Entry:
    __slots__ = ("name", "path", "is_dir", "size", "mtime", "ext", "key")

    def __init__(self, de):
        self.name = de.name
        self.path = de.path
        try:
            self.is_dir = de.is_dir()
            st = de.stat()
            self.size = 0 if self.is_dir else st.st_size
            self.mtime = st.st_mtime
        except OSError:
            self.is_dir, self.size, self.mtime = False, 0, 0
        self.ext = "" if self.is_dir else os.path.splitext(de.name)[1][1:].lower()
        self.key = natural_key(de.name)

    @property
    def media(self):
        return not self.is_dir and self.ext in MEDIA

    @property
    def type_label(self):
        if self.is_dir:
            return "Folder"
        return f"{self.ext.upper()} file" if self.ext else "File"


class DirModel(QAbstractTableModel):
    COLS = ["Name", "Type", "Size", "Date modified"]

    def __init__(self):
        super().__init__()
        self.entries = []
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
        self.entries = items
        self.endResetModel()
        return err

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
                return "" if e.is_dir else human_size(e.size)
            if c == 3:
                return time.strftime("%Y-%m-%d %H:%M", time.localtime(e.mtime)) if e.mtime else ""
        elif role == Qt.DecorationRole and c == 0:
            return self.icon_for(e)
        elif role == Qt.TextAlignmentRole and c == 2:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        elif role == Qt.ToolTipRole and c == 0:
            return e.path
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
        ka = {1: a.ext, 2: a.size, 3: a.mtime}.get(c)
        kb = {1: b.ext, 2: b.size, 3: b.mtime}.get(c)
        if ka is not None and ka != kb:
            return ka < kb
        return a.key < b.key

    def filterAcceptsRow(self, row, parent):
        text = self.filterRegularExpression().pattern()
        if not text:
            return True
        return text.casefold() in self.sourceModel().entries[row].name.casefold()


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


class Window(QMainWindow):
    def __init__(self, start_arg=None):
        super().__init__()
        self.setWindowTitle(f"{APP} {VERSION}")
        self.settings = QSettings(APP, APP)
        self.cwd = None
        self.history, self.hist_pos = [], -1
        self.queue = []
        self.cur_path = None
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
        self.list.sortByColumn(0, Qt.AscendingOrder)
        hdr = self.list.header()
        hdr.setSectionResizeMode(0, QHeaderView.Interactive)
        hdr.resizeSection(0, 420)
        hdr.resizeSection(1, 110)
        hdr.resizeSection(2, 90)
        self.proxy.layoutChanged.connect(self.update_status)

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

        self.hsplit = QSplitter(Qt.Horizontal)
        self.hsplit.addWidget(self.tree)
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
        QShortcut(QKeySequence("Escape"), self.filter, lambda: (self.filter.clear(), self.list.setFocus()),
                  context=Qt.WidgetShortcut)
        QShortcut(QKeySequence("Escape"), self, lambda: self.full_hidden is not None and self.toggle_full())
        QShortcut(QKeySequence("F"), self, self.toggle_full)
        QShortcut(QKeySequence("F11"), self, self.toggle_full)
        QShortcut(QKeySequence("Space"), self, self.play_pause)

        # --- restore
        geo = self.settings.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        else:
            self.resize(1400, 860)
        for key, sp in (("hsplit", self.hsplit), ("vsplit", self.vsplit)):
            st = self.settings.value(key)
            if st:
                sp.restoreState(st)
        hs = self.settings.value("header")
        if hs:
            hdr.restoreState(hs)
        self.vol.setValue(int(self.settings.value("volume", 80)))

        self.timer = QTimer(self, interval=200, timeout=self.poll)
        self.timer.start()

        start_file = None
        if start_arg and os.path.isfile(start_arg):
            start_file = os.path.abspath(start_arg)
            start_dir = os.path.dirname(start_file)
        elif start_arg and os.path.isdir(start_arg):
            start_dir = start_arg
        else:
            start_dir = self.settings.value("last_dir") or os.path.expanduser("~")
            if not os.path.isdir(start_dir):
                start_dir = os.path.expanduser("~")
        self.navigate(start_dir)
        if start_file:
            self.play_view(start_file)

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
        path = os.path.normpath(os.path.abspath(path))
        if len(path) == 2 and path[1] == ":":
            path += "\\"
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
        if self.cwd:
            parent = os.path.dirname(self.cwd.rstrip("\\/"))
            if parent and parent != self.cwd:
                child = self.cwd
                self.navigate(parent)
                for r in range(self.proxy.rowCount()):
                    if os.path.normcase(self.entry_at(self.proxy.index(r, 0)).path) == os.path.normcase(child.rstrip("\\")):
                        self.list.setCurrentIndex(self.proxy.index(r, 0))
                        self.list.scrollTo(self.proxy.index(r, 0))
                        break

    def apply_filter(self, text):
        self.proxy.setFilterFixedString(text)
        self.update_status()

    def update_status(self):
        ents = self.view_entries()
        media = sum(1 for e in ents if e.media)
        self.statusBar().showMessage(f"{len(ents)} items  ·  {media} playable")

    # ---------- list actions
    def activate(self, ix):
        e = self.entry_at(ix)
        if e.is_dir:
            self.navigate(e.path)
        elif e.media:
            self.play_view(e.path)
        else:
            os.startfile(e.path)

    def context_menu(self, pos):
        ix = self.list.indexAt(pos)
        m = QMenu(self)
        if ix.isValid():
            e = self.entry_at(ix)
            if e.media:
                m.addAction("Play from here", lambda: self.play_view(e.path))
            m.addAction("Open", lambda: self.activate(ix))
            m.addAction("Show in Explorer", lambda: subprocess.Popen(["explorer", "/select,", e.path]))
            m.addAction("Copy Full Path", lambda: QApplication.clipboard().setText(
                "\n".join(self.entry_at(i).path for i in self.list.selectionModel().selectedRows()) or e.path))
            m.addSeparator()
        m.addAction("Play all (sort order)", lambda: self.play_view(None))
        m.addAction("Refresh", lambda: self.navigate(self.cwd, record=False))
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
            if k == Qt.Key_Space:
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
    def play_view(self, start_path):
        """Queue every playable file in the current view, in its current sort order."""
        paths = [e.path for e in self.view_entries() if e.media]
        if not paths:
            self.statusBar().showMessage("Nothing playable in this view", 4000)
            return
        start = paths.index(start_path) if start_path in paths else 0
        self.queue = paths
        self.player.command("stop")
        for p in paths:
            self.player.command("loadfile", p, "append")
        self.player.playlist_pos = start
        self.player.pause = False
        if os.path.splitext(paths[start])[1][1:].lower() in VIDEO:
            self.btn_video.setChecked(True)

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
                sp.insertWidget(1, self.video)
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
        if not self.btn_video.isChecked():
            self.btn_video.setChecked(True)
        self.was_max = self.isMaximized()
        self.full_hidden = [w for w in (self.topbar, self.tree, self.list, self.bar, self.statusBar()) if w.isVisible()]
        for w in self.full_hidden:
            w.hide()
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.showFullScreen()
        self.setFocus()

    def play_pause(self):
        if self.player.idle_active:
            cur = self.list.currentIndex()
            e = self.entry_at(cur) if cur.isValid() else None
            self.play_view(e.path if e and e.media else None)
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
            if path:
                self.analyzer.request(path)
        if path:
            name = os.path.basename(path)
            self.now.setText(f"{name}    ({idx + 1} / {len(self.queue)})")
            self.setWindowTitle(f"{name} - {APP}")
            if os.path.splitext(path)[1][1:].lower() in VIDEO:
                if not self.btn_video.isChecked():
                    self.btn_video.setChecked(True)
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
        s = self.settings
        s.setValue("geometry", self.saveGeometry())
        s.setValue("hsplit", self.hsplit.saveState())
        s.setValue("vsplit", self.vsplit.saveState())
        s.setValue("header", self.list.header().saveState())
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


def main():
    install_error_log()
    app = QApplication(sys.argv)
    app.setApplicationName(APP)
    themes.apply(app, themes.get(QSettings(APP, APP).value("skin", themes.DEFAULT)))
    w = Window(sys.argv[1] if len(sys.argv) > 1 else None)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
