# Cratedig

A Windows file explorer and media player in one window. Browse folders like Explorer, sort however you want, and hit play: everything in the view plays in that sort order. Audio and video.

## Features (v0.2)
- Folder tree + big sortable file list (name, type, size, date); folders always on top
- Play in sort order: double-click a file and the whole view queues from there
- Filter as you type (Ctrl+F), back/forward/up, editable address bar
- Waveform panel with 6 views: Classic, Bars, Spectrum, Bars + Spectrum, Spectrogram, Stereo (W cycles; click/drag to seek)
- Waveforms are analyzed in the background and cached
- Skins: Blue, Ember, Neon, Violet, Crimson
- Video: 9:16 plays in a tall column on the right, 16:9/square above the list, F for fullscreen, Esc to exit
- Right-click: Play from here, Show in Explorer, Copy Full Path

## Keys
| Key | Action |
|---|---|
| Enter / double-click | Open folder or play |
| Space | Play / pause |
| Backspace | Up a folder |
| Alt+Left / Alt+Right | Back / forward |
| Ctrl+F / Ctrl+L | Filter / address bar |
| Ctrl+Left / Ctrl+Right | Previous / next track |
| Shift+Left / Shift+Right | Seek -10s / +10s |
| W | Cycle waveform view |
| V | Show / hide video |
| F or F11 | Fullscreen (Esc exits) |

## Setup
1. Python 3.12+:
   ```
   python -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt
   ```
2. **libmpv** (not in the repo, too big for GitHub): put `libmpv-2.dll` in a `lib\` folder next to `cratedig.py`.
   Get it from an mpv dev build (e.g. the `mpv-dev-x86_64-*.7z` archives from shinchiro's mpv-winbuild-cmake releases) or copy it from an mpv.net install (`C:\Program Files\mpv.net\libmpv-2.dll`).
3. **ffmpeg** on PATH (or `lib\ffmpeg.exe`) for waveform analysis: `winget install Gyan.FFmpeg`
4. Run `Cratedig.bat` (or `.venv\Scripts\python cratedig.py [folder or file]`).

Settings live in the registry (QSettings `Cratedig`), the waveform cache and `error.log` in `%LOCALAPPDATA%\Cratedig\`.

## Roadmap
See [PLAN.md](PLAN.md): drag-and-drop playlist panel, media columns (duration/artist/BPM/key), deep indexed search with filters, A/B loop, quick preview, crossfade, installer (.exe).
