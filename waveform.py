"""Cratedig waveform engine + views.

Analysis: ffmpeg decodes to 22050 Hz stereo s16 in a background thread, streamed in chunks.
Per 512-sample block (~23 ms) it keeps per-channel min/max peaks and one log-frequency
spectrum column (uint8). The spectrum columns drive both the spectrogram and the live
spectrum bars, so every view comes from one cached analysis.
"""
import hashlib
import os
import shutil
import subprocess
import threading
import time

import numpy as np
from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QToolTip, QWidget

RATE = 22050
BLOCK = 512
NFFT = 2048
FPS_BLOCKS = RATE / BLOCK  # spectrum columns per second
CACHE_VER = 2
COMBO = "Bars + Spectrum"
MODES = ["Classic", "Bars", "Spectrum", COMBO, "Spectrogram", "Stereo"]
LIVE = ("Spectrum", COMBO)

UNPLAYED = QColor("#5b5f69")

_freqs = np.fft.rfftfreq(NFFT, 1 / RATE)
_edges = np.unique(np.searchsorted(_freqs, np.geomspace(30, RATE / 2, 97)))
_edges = _edges[_edges < len(_freqs)]
NBANDS = len(_edges)
_tilt = np.linspace(-0.02, 0.10, NBANDS).astype(np.float32)  # lift highs a touch so hats show
_win = np.hanning(NFFT).astype(np.float32)
_norm = NFFT / 4  # hann-windowed full-scale sine peak


def find_ffmpeg(here):
    for p in (os.path.join(here, "lib", "ffmpeg.exe"), os.path.join(here, "ffmpeg.exe")):
        if os.path.isfile(p):
            return p
    return shutil.which("ffmpeg")


def cache_dir():
    d = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Cratedig", "cache")
    os.makedirs(d, exist_ok=True)
    return d


def cache_key(path):
    st = os.stat(path)
    raw = f"{CACHE_VER}|{os.path.normcase(os.path.abspath(path))}|{st.st_size}|{st.st_mtime_ns}"
    return hashlib.sha1(raw.encode("utf-8", "surrogatepass")).hexdigest()


class Analysis:
    """peaks: (n, 2ch, 2[min,max]) float32 -1..1; rms: (n, 2ch) float32 0..1; spec: (n, NBANDS) uint8."""

    def __init__(self, peaks, rms, spec, done):
        self.peaks, self.rms, self.spec, self.done = peaks, rms, spec, done

    @property
    def blocks(self):
        return len(self.peaks)


class Analyzer(QObject):
    progress = Signal(str, object)  # path, Analysis

    def __init__(self, here):
        super().__init__()
        self.ffmpeg = find_ffmpeg(here)
        self.job = None
        self.proc = None
        self.lock = threading.Lock()

    def request(self, path):
        with self.lock:
            self.job = path
            if self.proc and self.proc.poll() is None:
                self.proc.kill()
        threading.Thread(target=self._run, args=(path,), daemon=True).start()

    def _current(self, path):
        return self.job == path

    def _run(self, path):
        try:
            key = cache_key(path)
        except OSError:
            return
        cf = os.path.join(cache_dir(), key + ".npz")
        if os.path.isfile(cf):
            try:
                z = np.load(cf)
                self.progress.emit(path, Analysis(z["peaks"].astype(np.float32) / 32767,
                                                  z["rms"].astype(np.float32) / 32767, z["spec"], True))
                return
            except Exception:
                pass
        if not self.ffmpeg:
            return
        cmd = [self.ffmpeg, "-v", "quiet", "-nostdin", "-i", path, "-vn", "-ac", "2", "-ar", str(RATE),
               "-f", "s16le", "-"]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=flags)
        with self.lock:
            if not self._current(path):
                proc.kill()
                return
            self.proc = proc
        peaks, rmss, specs = [], [], []
        pend = np.empty((0, 2), np.int16)
        tail = np.zeros(NFFT - BLOCK, np.float32)
        leftover = b""
        last_emit = time.time()
        chunk = RATE * 4 * 5  # 5 s
        while True:
            data = proc.stdout.read(chunk)
            if not self._current(path):
                proc.kill()
                return
            if not data:
                break
            data = leftover + data
            cut = len(data) - len(data) % 4
            leftover = data[cut:]
            a = np.frombuffer(data[:cut], np.int16).reshape(-1, 2)
            pend = np.concatenate([pend, a])
            n = len(pend) // BLOCK * BLOCK
            if not n:
                continue
            blk, pend = pend[:n], pend[n:]
            nb = n // BLOCK
            b = blk.reshape(nb, BLOCK, 2)
            peaks.append(np.stack([b.min(1), b.max(1)], -1))
            rmss.append(np.sqrt((b.astype(np.float32) ** 2).mean(1)).astype(np.int16))
            mono = blk.astype(np.float32).mean(1) / 32768
            seq = np.concatenate([tail, mono])
            frames = np.lib.stride_tricks.sliding_window_view(seq, NFFT)[::BLOCK][:nb]
            tail = seq[-(NFFT - BLOCK):]
            mag = np.abs(np.fft.rfft(frames * _win, axis=1)) / _norm
            band = np.maximum.reduceat(mag, _edges, axis=1)
            db = 20 * np.log10(band + 1e-9)
            specs.append(np.clip((db + 90) * (255 / 90), 0, 255).astype(np.uint8))
            if time.time() - last_emit > 0.6:
                last_emit = time.time()
                self.progress.emit(path, self._pack(peaks, rmss, specs, False))
        proc.wait()
        if not self._current(path):
            return
        if not peaks:
            self.progress.emit(path, Analysis(np.zeros((0, 2, 2), np.float32), np.zeros((0, 2), np.float32),
                                              np.zeros((0, NBANDS), np.uint8), True))
            return
        res = self._pack(peaks, rmss, specs, True)
        self.progress.emit(path, res)
        try:
            pk = np.concatenate(peaks)
            np.savez_compressed(cf, peaks=pk, rms=np.concatenate(rmss), spec=res.spec)
        except Exception:
            pass

    @staticmethod
    def _pack(peaks, rmss, specs, done):
        return Analysis(np.concatenate(peaks).astype(np.float32) / 32767,
                        np.concatenate(rmss).astype(np.float32) / 32767, np.concatenate(specs), done)



class WaveView(QWidget):
    seekRequested = Signal(float)  # seconds
    modeChanged = Signal(str)

    def __init__(self, player):
        super().__init__()
        self.player = player
        self.mode = MODES[0]
        self.path = None
        self.ana = None
        self.pos = 0.0
        self.dur = 0.0
        self.cache_pix = None  # (key, played_pixmap, unplayed_pixmap)
        self.spec_smooth = np.zeros(NBANDS, np.float32)
        self.spec_peak = np.zeros(NBANDS, np.float32)
        self.dragging = False
        self.setMinimumHeight(90)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.t = None
        self.timer = QTimer(self, interval=33, timeout=self.tick)
        self.timer.start()

    # ---------- state
    def set_theme(self, t):
        self.t = t
        self.accent = QColor(t["accent"])
        self.cache_pix = None
        self.update()

    def set_mode(self, mode):
        self.mode = mode if mode in MODES else MODES[0]
        self.setMinimumHeight(180 if self.mode == COMBO else 110)
        self.cache_pix = None
        self.modeChanged.emit(self.mode)
        self.update()

    def cycle(self):
        self.set_mode(MODES[(MODES.index(self.mode) + 1) % len(MODES)])

    def set_track(self, path):
        if path != self.path:
            self.path = path
            self.ana = None
            self.cache_pix = None
            self.update()

    def set_analysis(self, path, ana):
        if path == self.path:
            self.ana = ana
            self.cache_pix = None
            self.update()

    def tick(self):
        p = self.player
        try:
            if p.idle_active:
                pos, dur = 0.0, 0.0
            else:
                pos, dur = p.time_pos or 0.0, p.duration or 0.0
            paused = p.pause
        except Exception:
            return
        changed = abs(pos - self.pos) > 1e-3 or dur != self.dur
        self.pos, self.dur = pos, dur
        if self.mode in LIVE:
            self._spectrum_step(paused)
            self.update()
        elif changed and not self.dragging:
            self.update()

    def total_blocks(self):
        if self.dur:
            return max(int(self.dur * FPS_BLOCKS), self.ana.blocks if self.ana else 1)
        return self.ana.blocks if self.ana else 1

    # ---------- mouse
    def _sec_at(self, x):
        return max(0.0, min(1.0, x / max(1, self.width()))) * self.dur

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.dur:
            self.dragging = True
            self.pos = self._sec_at(e.position().x())
            self.update()

    def mouseMoveEvent(self, e):
        if self.dur:
            s = self._sec_at(e.position().x())
            QToolTip.showText(e.globalPosition().toPoint(), _fmt(s), self)
            if self.dragging:
                self.pos = s
                self.update()

    def mouseReleaseEvent(self, e):
        if self.dragging:
            self.dragging = False
            self.seekRequested.emit(self._sec_at(e.position().x()))

    def resizeEvent(self, e):
        self.cache_pix = None
        super().resizeEvent(e)

    # ---------- column reduction
    def _columns(self, ncols):
        """Per-column (n, 2ch, 2) min/max over the total timeline; missing tail = 0."""
        tot = self.total_blocks()
        pk = self.ana.peaks
        idx = np.linspace(0, tot, ncols + 1).astype(np.int64)
        idx = np.minimum(idx, len(pk))
        out = np.zeros((ncols, 2, 2), np.float32)
        rms = np.zeros((ncols, 2), np.float32)
        valid = idx[:-1] < len(pk)  # reduceat: an empty segment yields its single start block
        if valid.any():
            starts = idx[:-1][valid]
            out[valid, :, 0] = np.minimum.reduceat(pk[:, :, 0], starts, axis=0)
            out[valid, :, 1] = np.maximum.reduceat(pk[:, :, 1], starts, axis=0)
            rms[valid] = np.maximum.reduceat(self.ana.rms, starts, axis=0)
        return out, rms

    # ---------- painting
    def paintEvent(self, _):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing, True)
        qp.fillRect(self.rect(), QColor(self.t["bg"]))
        w, h = self.width(), self.height()
        frac = (self.pos / self.dur) if self.dur else 0.0
        px = frac * w
        if self.mode == "Spectrum":
            self._paint_spectrum(qp, w, h, frac)
        elif self.mode == COMBO:
            sh = int(h * 0.58)
            self._paint_spectrum(qp, w, sh, frac, strip=False)
            qp.fillRect(QRectF(0, sh, w, 1), QColor(255, 255, 255, 18))
            self._paint_wave(qp, sh + 4, w, h - sh - 4, "Bars", px)
        else:
            self._paint_wave(qp, 0, w, h, self.mode, px)
        qp.end()

    def _paint_wave(self, qp, top, w, h, mode, px):
        if not self.ana or not self.ana.blocks:
            qp.setPen(QPen(UNPLAYED, 1))
            qp.drawLine(QPointF(0, top + h / 2), QPointF(w, top + h / 2))
            if self.dur:
                qp.setPen(QPen(self.accent, 2))
                qp.drawLine(QPointF(0, top + h / 2), QPointF(px, top + h / 2))
                qp.setPen(QPen(QColor("#ffffff"), 1.5))
                qp.drawLine(QPointF(px, top), QPointF(px, top + h))
            label = ""
            if self.path:
                label = "no audio" if (self.ana and self.ana.done) else "analyzing…"
            qp.setPen(QColor("#8a8d96"))
            qp.drawText(QRectF(0, top, w, h).adjusted(0, 0, 0, -h * 0.25), Qt.AlignCenter, label)
            return
        key = (mode, w, h, self.ana.blocks, self.ana.done, self.t["name"])
        if not self.cache_pix or self.cache_pix[0] != key:
            self.cache_pix = (key,) + self._render(w, h, mode)
        _, played, unplayed = self.cache_pix
        dpr = played.devicePixelRatio()
        qp.drawPixmap(QPointF(0, top), unplayed)
        qp.drawPixmap(QRectF(0, top, px, h), played, QRectF(0, 0, px * dpr, h * dpr))
        if self.dur:
            qp.setPen(QPen(QColor("#ffffff"), 1.5))
            qp.drawLine(QPointF(px, top), QPointF(px, top + h))

    def _render(self, w, h, mode):
        dpr = self.devicePixelRatioF()
        pw, ph = max(1, int(w * dpr)), max(1, int(h * dpr))
        pix = []
        for color in (self.accent, UNPLAYED):
            pm = QPixmap(pw, ph)
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing, True)
            if mode == "Classic":
                self._draw_classic(p, w, h, color, 0, h)
            elif mode == "Bars":
                self._draw_bars(p, w, h, color)
            elif mode == "Stereo":
                self._draw_classic(p, w, h / 2, color, 0, h / 2, ch=0)
                self._draw_classic(p, w, h / 2, color, h / 2, h / 2, ch=1)
                p.setPen(QPen(QColor(255, 255, 255, 40), 1))
                p.drawLine(QPointF(0, h / 2), QPointF(w, h / 2))
                p.setPen(QColor(255, 255, 255, 90))
                p.drawText(4, 12, "L")
                p.drawText(4, int(h / 2) + 12, "R")
            elif mode == "Spectrogram":
                self._draw_spectrogram(p, w, h, played=(color is self.accent))
            p.end()
            pix.append(pm)
        return pix[0], pix[1]

    @staticmethod
    def _band(top_vals, bot_vals, mid, amp):
        path = QPainterPath()
        path.moveTo(0, mid - top_vals[0] * amp)
        for x in range(1, len(top_vals)):
            path.lineTo(x, mid - top_vals[x] * amp)
        for x in range(len(bot_vals) - 1, -1, -1):
            path.lineTo(x, mid - bot_vals[x] * amp)
        path.closeSubpath()
        return path

    def _draw_classic(self, p, w, h, color, top, height, ch=None):
        """Peaks as a translucent outer layer, loudness (RMS) as the solid core."""
        cols, rms = self._columns(int(w))
        if ch is None:
            mn, mx, r = cols[:, :, 0].min(1), cols[:, :, 1].max(1), rms.max(1)
        else:
            mn, mx, r = cols[:, ch, 0], cols[:, ch, 1], rms[:, ch]
        mid = top + height / 2
        amp = height / 2 * 0.95
        r = np.minimum(r * 1.414, 1.0)  # RMS -> sine-peak equivalent, so a loud master fills ~70-90%
        p.setPen(Qt.NoPen)
        outer = QColor(color)
        outer.setAlpha(95)
        p.setBrush(outer)
        p.drawPath(self._band(mx, mn, mid, amp))
        p.setBrush(color)
        p.drawPath(self._band(r, -r, mid, amp))

    def _draw_bars(self, p, w, h, color):
        bar, gap = 3, 2
        n = max(1, int(w // (bar + gap)))
        _, rms = self._columns(n)
        r = rms.max(1)
        top = r.max() or 1.0
        amp = np.clip(r / top, 0, 1) ** 1.6  # loudness relative to the track's loudest moment
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        mid = h / 2
        for i, a in enumerate(amp):
            bh = max(2.0, a * (h * 0.92))
            p.drawRoundedRect(QRectF(i * (bar + gap), mid - bh / 2, bar, bh), 1.5, 1.5)

    def _draw_spectrogram(self, p, w, h, played):
        spec = self.ana.spec
        tot = self.total_blocks()
        ncols = int(w)
        idx = np.minimum(np.linspace(0, tot, ncols + 1).astype(np.int64), len(spec))
        img = np.zeros((ncols, NBANDS), np.uint8)
        valid = idx[:-1] < len(spec)
        if valid.any():
            img[valid] = np.maximum.reduceat(spec, idx[:-1][valid], axis=0)
        rgb = self.t["lut_arr"][img.T[::-1]]  # (bands, cols), low freq at bottom
        if not played:
            rgb = ((rgb >> 1) & 0x7F7F7F) | 0xFF000000  # dim upcoming part
        rgb = np.ascontiguousarray(rgb.astype(np.uint32))
        qi = QImage(rgb.data, ncols, NBANDS, ncols * 4, QImage.Format_ARGB32).copy()
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawImage(QRectF(0, 0, w, h), qi)

    def _spectrum_step(self, paused):
        target = np.zeros(NBANDS, np.float32)
        if self.ana and self.dur and not paused:
            i = int(self.pos * FPS_BLOCKS)
            if 0 <= i < len(self.ana.spec):
                lo = max(0, i - 1)
                target = self.ana.spec[lo:i + 1].max(0).astype(np.float32) / 255
                target = np.clip((target - 0.22) / 0.78 + _tilt, 0, 1)
        up = target > self.spec_smooth
        self.spec_smooth = np.where(up, target, self.spec_smooth * 0.82)
        self.spec_peak = np.maximum(self.spec_peak - 0.012, self.spec_smooth)

    def _paint_spectrum(self, qp, w, h, frac, strip=True):
        n = NBANDS
        gap = 2
        bw = max(2.0, (w - gap * (n - 1)) / n)
        grad = QLinearGradient(0, h, 0, 0)
        grad.setColorAt(0, self.accent)
        grad.setColorAt(0.7, QColor(self.t["light"]))
        grad.setColorAt(1, QColor(self.t["lighter"]))
        usable = h - (6 if strip else 2)
        qp.setPen(Qt.NoPen)
        for i in range(n):
            x = i * (bw + gap)
            bh = self.spec_smooth[i] * usable
            if bh > 0.5:
                qp.setBrush(grad)
                qp.drawRect(QRectF(x, usable - bh, bw, bh))
            if self.spec_peak[i] > 0.01:
                pk = self.spec_peak[i] * usable
                qp.setBrush(QColor("#ffffff"))
                qp.drawRect(QRectF(x, usable - pk - 2, bw, 2))
        if not strip:
            return
        # progress strip doubles as the seek bar in this mode
        qp.setBrush(QColor("#33363d"))
        qp.drawRect(QRectF(0, h - 3, w, 3))
        qp.setBrush(self.accent)
        qp.drawRect(QRectF(0, h - 3, w * frac, 3))


def _fmt(sec):
    sec = int(sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
