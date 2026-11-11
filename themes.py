"""Cratedig skins. Each skin sets the accent family, the dark surfaces and the spectrogram colormap."""
import numpy as np
from PySide6.QtGui import QColor, QPalette

THEMES = {
    "Blue": dict(accent="#2f9bff", light="#7cc4ff", lighter="#d6efff", bg="#111419", base="#13161c",
                 alt="#181c23", mid="#1f242c", bar="#171b22", line="#2a3039", sel="#24405e",
                 lut=[(0, (2, 4, 16)), (0.3, (10, 40, 110)), (0.55, (20, 110, 210)), (0.75, (60, 180, 255)),
                      (0.9, (160, 225, 255)), (1.0, (245, 252, 255))]),
    "Ember": dict(accent="#ff8a1f", light="#ffc34d", lighter="#fff3c4", bg="#141518", base="#16171a",
                  alt="#1c1d21", mid="#24262b", bar="#1b1c20", line="#2e3036", sel="#4a3424",
                  lut=[(0, (0, 0, 4)), (0.25, (66, 10, 104)), (0.5, (147, 38, 103)), (0.7, (221, 81, 58)),
                       (0.85, (252, 165, 10)), (1.0, (252, 255, 164))]),
    "Neon": dict(accent="#2bff88", light="#9dffc9", lighter="#e6fff1", bg="#0f1412", base="#111613",
                 alt="#161d19", mid="#1c2420", bar="#141b17", line="#26302b", sel="#1f4632",
                 lut=[(0, (0, 6, 4)), (0.3, (0, 50, 40)), (0.55, (0, 130, 90)), (0.75, (40, 220, 130)),
                      (0.9, (170, 255, 200)), (1.0, (240, 255, 245))]),
    "Violet": dict(accent="#a46bff", light="#cfa8ff", lighter="#f1e6ff", bg="#131119", base="#15131c",
                   alt="#1b1824", mid="#221f2c", bar="#19161f", line="#2d2939", sel="#3b2c5c",
                   lut=[(0, (4, 0, 12)), (0.3, (40, 10, 90)), (0.55, (110, 40, 190)), (0.75, (180, 100, 255)),
                        (0.9, (225, 190, 255)), (1.0, (250, 245, 255))]),
    "Crimson": dict(accent="#ff3b5c", light="#ff8fa3", lighter="#ffe0e6", bg="#161113", base="#181315",
                    alt="#1f181b", mid="#261e21", bar="#1c1518", line="#33282c", sel="#55242f",
                    lut=[(0, (8, 0, 2)), (0.3, (70, 0, 20)), (0.55, (170, 20, 50)), (0.75, (255, 70, 90)),
                         (0.9, (255, 170, 180)), (1.0, (255, 240, 242))]),
}
DEFAULT = "Blue"


def get(name):
    t = dict(THEMES.get(name) or THEMES[DEFAULT])
    t["name"] = name if name in THEMES else DEFAULT
    t["lut_arr"] = make_lut(t["lut"])
    return t


def make_lut(stops):
    xs = np.linspace(0, 1, 256)
    out = np.zeros((256, 3), np.float32)
    for ch in range(3):
        out[:, ch] = np.interp(xs, [s[0] for s in stops], [s[1][ch] for s in stops])
    o = out.astype(np.uint32)
    return (np.uint32(0xFF000000) | (o[:, 0] << 16) | (o[:, 1] << 8) | o[:, 2]).astype(np.uint32)


def apply(app, t):
    app.setStyle("Fusion")
    p = QPalette()
    text = QColor("#e6e8ec")
    p.setColor(QPalette.Window, QColor(t["mid"]))
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, QColor(t["base"]))
    p.setColor(QPalette.AlternateBase, QColor(t["alt"]))
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.Button, QColor(t["mid"]))
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.ToolTipBase, QColor(t["alt"]))
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.Highlight, QColor(t["sel"]))
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.PlaceholderText, QColor("#7d8088"))
    app.setPalette(p)
    a, line = t["accent"], t["line"]
    app.setStyleSheet(f"""
        QWidget#bar {{ background:{t['bar']}; border-top:1px solid {line}; }}
        QTreeView {{ border:1px solid {line}; }}
        QHeaderView::section {{ background:{t['alt']}; color:#b9bcc4; border:0; border-right:1px solid {line};
                                padding:4px 6px; }}
        QLineEdit {{ background:{t['base']}; border:1px solid {line}; border-radius:4px; padding:4px 6px; }}
        QLineEdit:focus {{ border-color:{a}; }}
        QSlider::groove:horizontal {{ height:4px; background:#33363d; border-radius:2px; }}
        QSlider::sub-page:horizontal {{ background:{a}; border-radius:2px; }}
        QSlider::handle:horizontal {{ background:#f2f2f2; width:12px; margin:-5px 0; border-radius:6px; }}
        QToolButton {{ padding:3px 6px; }}
        QToolButton:checked {{ background:{t['sel']}; border-radius:4px; }}
        QToolButton:hover {{ background:{line}; border-radius:4px; }}
        QPushButton#chip {{ background:{t['alt']}; border:1px solid {line}; border-radius:4px; padding:3px 10px; }}
        QPushButton#chip:hover {{ border-color:{a}; }}
        QSplitter::handle {{ background:{t['mid']}; }}
        QLabel#now {{ color:{a}; font-weight:600; }}
        QMenu::item:selected {{ background:{t['sel']}; }}
    """)
