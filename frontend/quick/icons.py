"""Иконки интерфейса: Lucide (ISC), значки загрузчиков и иллюстрации пустых состояний.

Файл сгенерирован из макета Nexora (Figma/HTML), правьте словари вручную при необходимости.
Иконки рисуются через ``QSvgRenderer`` нужным цветом и размером — см. ``images.py``.
"""

# Контурные иконки 24×24, линия 1,5 px
ICONS: dict[str, str] = {
    "library": '<rect width="8" height="18" x="3" y="3" rx="1"/><path d="M7 3v18"/><path d="M20.4 18.9c.2.5-.1 1.1-.6 1.3l-1.9.7c-.5.2-1.1-.1-1.3-.6L11.1 5.1c-.2-.5.1-1.1.6-1.3l1.9-.7c.5-.2 1.1.1 1.3.6Z"/>',
    "compass": '<circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/>',
    "globe": '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>',
    "sliders": '<line x1="21" x2="14" y1="4" y2="4"/><line x1="10" x2="3" y1="4" y2="4"/><line x1="21" x2="12" y1="12" y2="12"/><line x1="8" x2="3" y1="12" y2="12"/><line x1="21" x2="16" y1="20" y2="20"/><line x1="12" x2="3" y1="20" y2="20"/><line x1="14" x2="14" y1="2" y2="6"/><line x1="8" x2="8" y1="10" y2="14"/><line x1="16" x2="16" y1="18" y2="22"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
    "chevron-left": '<path d="m15 18-6-6 6-6"/>',
    "play": '<polygon points="6 3 20 12 6 21 6 3"/>',
    "square": '<rect width="14" height="14" x="5" y="5" rx="2"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
    "kebab": '<circle cx="12" cy="12" r="1"/><circle cx="12" cy="5" r="1"/><circle cx="12" cy="19" r="1"/>',
    "copy": '<rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
    "folder": '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    "lightbulb": '<path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"/><path d="M9 18h6"/><path d="M10 22h4"/>',
    "alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "trash": '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/>',
    "refresh": '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
    "zap": '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    "terminal": '<path d="m4 17 6-6-6-6"/><path d="M12 19h8"/>',
    "archive": '<rect width="20" height="5" x="2" y="3" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "user": '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    "server": '<rect width="20" height="8" x="2" y="2" rx="2"/><rect width="20" height="8" x="2" y="14" rx="2"/><line x1="6" x2="6.01" y1="6" y2="6"/><line x1="6" x2="6.01" y1="18" y2="18"/>',
    "external": '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    "share": '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" x2="15.42" y1="13.51" y2="17.49"/><line x1="15.41" x2="8.59" y1="6.51" y2="10.49"/>',
    "cpu": '<rect width="16" height="16" x="4" y="4" rx="2"/><rect width="6" height="6" x="9" y="9"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/>',
    "panel-left": '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "image": '<rect width="18" height="18" x="3" y="3" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>',
    "package": '<path d="M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z"/><path d="M12 22V12"/><path d="M3.29 7 12 12l8.71-5"/>',
    "activity": '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>',
    "layers": '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
    "circle-alert": '<circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/>',
    "file-text": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
    "arrow-right": '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    "corner-down-left": '<polyline points="9 10 4 15 9 20"/><path d="M20 4v7a4 4 0 0 1-4 4H4"/>',
    "pencil": '<path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/><path d="m15 5 4 4"/>',
    "log-out": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" x2="9" y1="12" y2="12"/>',
    "chest": '<path d="M4 9a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v10H4Z"/><path d="M4 12h16"/><path d="M10 12v3h4v-3"/><path d="M6 7V6a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v1"/>',
    "minus": '<path d="M5 12h14"/>',
    "maximize": '<rect width="14" height="14" x="5" y="5" rx="1"/>',
    "cube": '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
    "import": '<path d="M12 3v12"/><path d="m8 11 4 4 4-4"/><path d="M8 5H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-4"/>',
    "history": '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>',
    "wrench": '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
}

# Значки загрузчиков 16×16 (собственная отрисовка, не логотипы)
LOADER_MARKS: dict[str, str] = {
    "vanilla": '<polygon points="8 1.5 14 4.75 8 8 2 4.75" fill="#7DBB62"/><polygon points="2 4.75 8 8 8 14.5 2 11.25" fill="#8C6A47"/><polygon points="14 4.75 8 8 8 14.5 14 11.25" fill="#6B4E33"/>',
    "fabric": '<rect x="1" y="1" width="14" height="14" rx="3" fill="#D9CBA6"/><path d="M4.5 11.5 11.5 4.5" stroke="#4B3F27" stroke-width="1.6" stroke-linecap="round" stroke-dasharray="2 2.4" fill="none"/>',
    "quilt": '<rect x="1" y="1" width="6.5" height="6.5" rx="1.2" fill="#7C5CBF"/><rect x="8.5" y="1" width="6.5" height="6.5" rx="1.2" fill="#E0A53B"/><rect x="1" y="8.5" width="6.5" height="6.5" rx="1.2" fill="#4FA3A5"/><rect x="8.5" y="8.5" width="6.5" height="6.5" rx="1.2" fill="#D9644A"/>',
    "forge": '<path d="M2 3.5h12l-1.5 3H9.5V10H12v2.5H4V10h2.5V6.5H3.5Z" fill="#C9663A"/>',
    "neoforge": '<path d="M2 4.5h11l-1.5 3H9.5V11H12v2.5H4V11h2.5V7.5H3.5Z" fill="#E8913A"/><circle cx="12.5" cy="2.8" r="1.4" fill="#F0B23A"/>',
    "optifine": '<circle cx="8" cy="8" r="6" fill="none" stroke="#5AA9E6" stroke-width="1.6"/><circle cx="8" cy="8" r="2" fill="#5AA9E6"/>',
    "paper": '<rect x="2.5" y="1.5" width="11" height="13" rx="1.5" fill="#E8E2D2"/><path d="M5 5h6M5 8h6M5 11h4" stroke="#8C836E" stroke-width="1.2" stroke-linecap="round"/>',
    "purpur": '<rect x="1.5" y="1.5" width="13" height="13" rx="2" fill="#A97FC4"/><path d="M4.5 4.5h7v7h-7z" fill="none" stroke="#5E3A7A" stroke-width="1.4"/>',
}

# Иллюстрации пустых состояний 72×72
ILLUSTRATIONS: dict[str, str] = {
    "library": '<path d="M36 10 58 22v26L36 60 14 48V22Z"/><path d="m14 22 22 12 22-12"/><path d="M36 34v26" stroke-dasharray="3 3"/>',
    "mods": '<rect x="12" y="38" width="22" height="22" rx="2"/><rect x="38" y="38" width="22" height="22" rx="2"/><rect x="25" y="12" width="22" height="22" rx="2" stroke-dasharray="3 3"/>',
    "server": '<rect x="12" y="14" width="48" height="16" rx="3"/><rect x="12" y="38" width="48" height="16" rx="3"/><path d="M20 22h.01M20 46h.01M36 62v-8" stroke-dasharray="1 0"/>',
    "search": '<circle cx="31" cy="31" r="17"/><path d="m44 44 16 16"/><path d="m25 30 6-3 6 3v7l-6 3-6-3Z" stroke-dasharray="2 3"/>',
    "worlds": '<path d="M8 56 26 26l12 18 8-10 18 22Z"/><circle cx="52" cy="18" r="5"/>',
}

LOGO = ('<rect x="2" y="3" width="5" height="18" rx="1" fill="{fg}"/><rect x="17" y="3" width="5" height="18" rx="1" '
        'fill="{fg}"/><rect x="7" y="6" width="4" height="4" fill="{accent}"/><rect x="10" y="10" width="4" height="4" '
        'fill="{accent}"/><rect x="13" y="14" width="4" height="4" fill="{accent}"/>')


def icon_svg(name: str, color: str, stroke: float = 1.5) -> bytes:
    body = ICONS.get(name, "")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>').encode()


def loader_svg(loader: str) -> bytes:
    body = LOADER_MARKS.get(loader, LOADER_MARKS["vanilla"])
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">{body}</svg>'.encode()


def illustration_svg(name: str, color: str) -> bytes:
    body = ILLUSTRATIONS.get(name, "")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 72 72" fill="none" stroke="{color}" '
            f'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">{body}</svg>').encode()


def logo_svg(fg: str, accent: str) -> bytes:
    body = LOGO.format(fg=fg, accent=accent)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{body}</svg>'.encode()
