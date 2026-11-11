# Cratedig

**A file explorer and media player in one window, for Windows.**

Browse your folders like Explorer, sort them however you want, and hit play: everything in the view plays in that order. Built for digging through crates of WAVs, masters, stems and video clips without bouncing between Explorer and a player.

---

## Download

Grab the latest **`Cratedig-vX.Y-portable-win64.zip`** from [Releases](../../releases).

1. Unzip it anywhere (Desktop, Documents, a USB stick).
2. Double-click **`Cratedig.exe`**.

That's it. No installer, no Python, no extra downloads. The video engine (mpv) and the waveform engine (ffmpeg) are bundled inside. Windows 10 or 11, 64-bit.

> First launch: Windows SmartScreen may say "Windows protected your PC" because the app isn't code-signed yet. Click **More info → Run anyway**.

---

## What it does

### Explorer
- Folder tree on the left, big file list in the middle
- Sort by **name, type, size or date** (click a column); folders always stay on top
- Natural sorting, so `Track 2` comes before `Track 10`
- **Filter as you type** (Ctrl+F), back / forward / up, editable address bar (Ctrl+L)
- Right-click: Play from here, Show in Explorer, Copy Full Path

### Player
- **Plays in sort order:** double-click any file and the whole view queues from there, in the order you sorted it
- Audio and video: WAV, FLAC, AIFF, MP3, M4A, OGG, OPUS, MP4, MKV, MOV, WEBM and more
- Gapless audio between tracks

### Waveform panel (6 views, press W to cycle)
| View | What you see |
|---|---|
| **Classic** | Full-track waveform; solid core = loudness, faint edge = peaks, so drops and breakdowns stand out |
| **Bars** | Track map as bars, scaled to the track's loudest moment |
| **Spectrum** | Live frequency bars bouncing to the music |
| **Bars + Spectrum** | Live spectrum on top, track map underneath |
| **Spectrogram** | Frequency over time as a heat map: sub-bass, drops and hats at a glance |
| **Stereo** | Left and right channels stacked |

Click or drag anywhere on the panel to seek. Waveforms are analyzed in the background on first play and cached, so they're instant after that.

### Video
- **Smart layout:** vertical 9:16 videos play in a tall column on the right; 16:9 and square play above the list
- **Fullscreen** for any video: F (or F11), Esc to come back
- Videos with no audio track just show "no audio" in the waveform panel

### Skins
**Blue** (default), **Ember**, **Neon**, **Violet**, **Crimson**: the Skin button recolors the whole app, including the spectrogram.

---

## Keyboard

| Key | Action |
|---|---|
| Enter / double-click | Open folder or play |
| Space | Play / pause |
| Backspace | Up a folder |
| Alt+Left / Alt+Right | Back / forward |
| Ctrl+F | Filter |
| Ctrl+L | Type a path |
| Ctrl+Left / Ctrl+Right | Previous / next track |
| Shift+Left / Shift+Right | Seek -10s / +10s |
| W | Cycle waveform view |
| V | Show / hide video |
| F or F11 | Fullscreen (Esc exits) |

Cratedig remembers your last folder, window size, column layout, volume, view and skin.

---

## Roadmap
- Drag-and-drop playlist panel, save/load .m3u
- Media columns: duration, artist, title, bitrate, sample rate, BPM, key
- Deep indexed search across drives with filters like `type:wav bpm:170-176 date:2026`
- A/B loop, quick preview without touching the queue, crossfade
- Installer (Start Menu, desktop icon, "Open with")

Full plan in [PLAN.md](PLAN.md).

---

## Run from source

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```
- Put `libmpv-2.dll` in a `lib\` folder next to `cratedig.py` (from an mpv dev build, e.g. shinchiro's `mpv-dev-x86_64-*.7z`, or copy it from an mpv.net install).
- Install ffmpeg: `winget install Gyan.FFmpeg`
- Run `Cratedig.bat` or `.venv\Scripts\python cratedig.py [folder or file]`

**Build the portable zip:** `.venv\Scripts\python -m pip install pyinstaller`, then `.\build.ps1`.

Built with Python, PySide6 (Qt), mpv and ffmpeg. Settings live in the registry (`HKCU\Software\Cratedig`); the waveform cache and `error.log` are in `%LOCALAPPDATA%\Cratedig\`.
