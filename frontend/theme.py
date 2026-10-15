"""Тема оформления (QSS) — тёмная и светлая.

Виджеты получают стили через ``objectName``/свойства, а не инлайн-стилями:
``setObjectName("Card")``, ``setProperty("variant", "primary")`` и т.д.
"""

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

PALETTES = {
    "dark": {
        "bg": "#16161d", "surface": "#1f1f29", "surface2": "#282834", "surface3": "#323241",
        "border": "#363645", "text": "#ececf1", "muted": "#9a9aab", "accent": "#4f8cff",
        "accent_hover": "#6a9fff", "accent_text": "#ffffff", "success": "#2fbf71",
        "success_hover": "#38d27f", "danger": "#e5484d", "danger_hover": "#f05b60",
        "warning": "#f5a524", "selection": "#2c4a80",
    },
    "light": {
        "bg": "#eef0f5", "surface": "#ffffff", "surface2": "#f4f5f9", "surface3": "#e7e9f0",
        "border": "#d8dbe5", "text": "#1c1d24", "muted": "#626678", "accent": "#2f6fed",
        "accent_hover": "#4a82f0", "accent_text": "#ffffff", "success": "#1f9d5a",
        "success_hover": "#25b066", "danger": "#d93036", "danger_hover": "#e5484d",
        "warning": "#c77d00", "selection": "#cfdcfb",
    },
}

_QSS = """
* {{ font-family: "Segoe UI", "Inter", "Noto Sans", sans-serif; font-size: 13px; color: {text}; }}
QMainWindow, QDialog {{ background: {bg}; }}
QWidget#Page {{ background: transparent; }}
QToolTip {{ background: {surface3}; color: {text}; border: 1px solid {border}; padding: 4px 6px; }}

QFrame#Sidebar {{ background: {surface}; border-right: 1px solid {border}; }}
QLabel#Logo {{ font-size: 20px; font-weight: 700; padding: 0 0 0 10px; }}
QLabel#LogoSub {{ color: {muted}; font-size: 11px; padding: 2px 16px 12px 16px; }}
QPushButton#NavButton {{
    background: transparent; border: none; border-radius: 8px; text-align: left;
    padding: 9px 14px; color: {muted}; font-size: 13px;
}}
QPushButton#NavButton:hover {{ background: {surface2}; color: {text}; }}
QPushButton#NavButton:checked {{ background: {selection}; color: {text}; font-weight: 600; }}

QLabel#PageTitle {{ font-size: 22px; font-weight: 700; }}
QLabel#PageSubtitle, QLabel[muted="true"] {{ color: {muted}; }}
QLabel#SectionTitle {{ font-size: 15px; font-weight: 600; padding-top: 6px; }}
QLabel#CardTitle {{ font-size: 14px; font-weight: 600; }}
QLabel#Empty {{ color: {muted}; font-size: 14px; padding: 40px; }}
QLabel#Badge {{
    background: {surface3}; color: {muted}; border-radius: 6px; padding: 2px 8px; font-size: 11px;
}}
QLabel#BadgeSuccess {{ background: {success}; color: #ffffff; border-radius: 6px; padding: 2px 8px; font-size: 11px; }}
QLabel#BadgeDanger {{ background: {danger}; color: #ffffff; border-radius: 6px; padding: 2px 8px; font-size: 11px; }}
QLabel#Code {{
    font-family: "Consolas", "JetBrains Mono", monospace; font-size: 26px; font-weight: 700;
    letter-spacing: 4px; background: {surface2}; border: 1px solid {border}; border-radius: 10px; padding: 12px;
}}

QFrame#Card {{ background: {surface}; border: 1px solid {border}; border-radius: 12px; }}
QFrame#Card:hover {{ border-color: {surface3}; }}
QFrame#Hero {{
    border-radius: 14px; border: 1px solid {border};
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {selection}, stop:1 {surface});
}}

QPushButton {{
    background: {surface2}; border: 1px solid {border}; border-radius: 8px; padding: 7px 14px;
}}
QPushButton:hover {{ background: {surface3}; }}
QPushButton:pressed {{ background: {border}; }}
QPushButton:disabled {{ color: {muted}; background: {surface2}; border-color: {surface2}; }}
QPushButton[variant="primary"] {{ background: {accent}; border-color: {accent}; color: {accent_text}; font-weight: 600; }}
QPushButton[variant="primary"]:hover {{ background: {accent_hover}; border-color: {accent_hover}; }}
QPushButton[variant="play"] {{ background: {success}; border-color: {success}; color: #ffffff; font-weight: 600; }}
QPushButton[variant="play"]:hover {{ background: {success_hover}; border-color: {success_hover}; }}
QPushButton[variant="danger"] {{ background: transparent; border-color: {danger}; color: {danger}; }}
QPushButton[variant="danger"]:hover {{ background: {danger}; color: #ffffff; }}
QPushButton[variant="stop"] {{ background: {danger}; border-color: {danger}; color: #ffffff; font-weight: 600; }}
QPushButton[variant="stop"]:hover {{ background: {danger_hover}; }}
QPushButton[variant="ghost"] {{ background: transparent; border-color: transparent; }}
QPushButton[variant="ghost"]:hover {{ background: {surface2}; }}
QPushButton::menu-indicator {{ width: 0; }}
QPushButton[size="small"] {{ padding: 3px 10px; font-size: 12px; }}

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {surface2}; border: 1px solid {border}; border-radius: 8px; padding: 6px 8px;
    selection-background-color: {accent}; selection-color: {accent_text};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {accent}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {surface}; border: 1px solid {border}; selection-background-color: {selection};
    selection-color: {text}; outline: 0;
}}
QPlainTextEdit#Log {{ font-family: "Consolas", "JetBrains Mono", monospace; font-size: 12px; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {border}; background: {surface2}; }}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; image: url({check_icon}); }}

QSlider::groove:horizontal {{ height: 6px; background: {surface3}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {text}; width: 16px; height: 16px; margin: -5px 0; border-radius: 8px; }}

QProgressBar {{ background: {surface3}; border: none; border-radius: 4px; height: 8px; text-align: center; font-size: 10px; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 4px; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {surface3}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {border}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {surface3}; border-radius: 4px; min-width: 30px; }}

QTabWidget::pane {{ border: 1px solid {border}; border-radius: 10px; background: {surface}; top: -1px; }}
QTabBar::tab {{ background: transparent; padding: 8px 14px; color: {muted}; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {text}; border-bottom-color: {accent}; }}
QTabBar::tab:hover {{ color: {text}; }}

QListWidget, QTableWidget {{
    background: {surface}; border: 1px solid {border}; border-radius: 10px; outline: 0;
    alternate-background-color: {surface2};
}}
QListWidget::item, QTableWidget::item {{ padding: 6px; }}
QListWidget::item:selected, QTableWidget::item:selected {{ background: {selection}; color: {text}; }}
QHeaderView::section {{ background: {surface2}; border: none; border-bottom: 1px solid {border}; padding: 6px; color: {muted}; }}

QMenu {{ background: {surface}; border: 1px solid {border}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {selection}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 6px; }}

QStatusBar {{ background: {surface}; border-top: 1px solid {border}; color: {muted}; }}
QStatusBar QLabel {{ color: {muted}; }}
QMessageBox {{ background: {bg}; }}
"""


_current_mode = "dark"


def current_colors() -> dict[str, str]:
    """Цвета активной темы (для HTML-вывода, где QSS не действует)."""
    return PALETTES.get(_current_mode, PALETTES["dark"])


def apply_theme(app: QApplication, mode: str = "dark") -> None:
    global _current_mode
    _current_mode = mode if mode in PALETTES else "dark"
    colors = PALETTES.get(mode, PALETTES["dark"])
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(colors["bg"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(colors["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(colors["surface2"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(colors["surface"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(colors["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(colors["surface2"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(colors["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(colors["accent"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(colors["accent_text"]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(colors["muted"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(colors["surface3"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(colors["text"]))
    app.setPalette(palette)
    from shared.paths import get_resources_dir
    check_icon = (get_resources_dir() / "check.svg").as_posix()
    app.setStyleSheet(_QSS.format(**colors, check_icon=check_icon))
