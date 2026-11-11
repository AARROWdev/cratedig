# Cratedig — plan

Windows media player + file explorer in one window. Audio and video.

## Stack
- Python + PySide6 (UI), libmpv via python-mpv (playback, every format)
- Metadata: mutagen (tags, duration, bitrate, sample rate, BPM/key tags)
- Index: SQLite (background drive index for deep search)
- Ship: PyInstaller (exe folder) + Inno Setup (Setup.exe: Start Menu, desktop icon, uninstaller, "Open with")

## Layout
- Left: folder tree (drives, favorites)
- Center: big file list with columns
- Right: playlist panel
- Bottom: player bar with waveform scrubber; video shows in the window

## Features
1. Explorer: sort by name, type, date, size + media columns (duration, artist, title, bitrate, sample rate, BPM, key); show/hide columns; file ops (rename, copy, move, delete to Recycle Bin, open in Explorer, Copy Full Path)
2. Play in sort order: Play queues the whole current view in its current sort
3. Drag-and-drop playlists: drag files/folders in, drag to reorder, save/load .m3u
4. Search: instant filter in current folder; deep indexed search across drives; filters like `type:wav bpm:170-176 date:2026`
5. Quick preview: hover/spacebar audition without touching the queue
6. A/B loop on the waveform
7. Crossfade / gapless
8. Video playback in the same window

## Milestones
- v0.1: window, tree, file list with sorting, play in sort order (mpv), player bar
- v0.2: playlist panel with drag and drop, .m3u
- v0.3: media columns (mutagen), instant filter
- v0.4: waveform, A/B loop, quick preview
- v0.5: deep indexed search + filter syntax
- v0.6: crossfade/gapless, file ops
- v1.0: exe + installer
