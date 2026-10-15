"""Короткие человеческие форматы для нового интерфейса: время игры, даты, размеры, склонения."""

from datetime import date, datetime, timedelta

from shared.i18n import get_language, t


def plural_form(n: int) -> str:
    """Форма для числа: one / few / many (русские правила; для английского — one / many)."""
    n = abs(int(n))
    if get_language() != "ru":
        return "one" if n == 1 else "many"
    m100, m10 = n % 100, n % 10
    if 10 < m100 < 15:
        return "many"
    if m10 == 1:
        return "one"
    if 1 < m10 < 5:
        return "few"
    return "many"


def count(n: int, base: str) -> str:
    """``count(48, "q.mods")`` → «48 модов». Ключи: ``<base>_one/_few/_many`` с параметром ``{n}``."""
    return t(f"{base}_{plural_form(n)}", n=n)


def duration(seconds: int) -> str:
    hours, rem = divmod(max(0, int(seconds)), 3600)
    minutes = rem // 60
    if hours:
        return t("time.hours_minutes", h=hours, m=f"{minutes:02d}")
    return t("time.minutes", m=minutes)


def clock(seconds: int) -> str:
    """Таймер игры: 4:05, 1:02:33."""
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def when(value: str | float | None, today: date | None = None) -> str:
    """«Сегодня, 10:05», «Вчера, 22:14», «09.10, 18:40», «09.10.2025». Принимает ISO-строку или timestamp."""
    if not value:
        return "—"
    try:
        moment = datetime.fromtimestamp(value) if isinstance(value, (int, float)) else datetime.fromisoformat(value)
    except (ValueError, OSError):
        return str(value)
    today = today or date.today()
    hm = moment.strftime("%H:%M")
    if moment.date() == today:
        return t("q.today_at", time=hm)
    if moment.date() == today - timedelta(days=1):
        return t("q.yesterday_at", time=hm)
    if moment.year == today.year:
        return moment.strftime("%d.%m, ") + hm
    return moment.strftime("%d.%m.%Y")


def size(num: int) -> str:
    """412 МБ, 1,2 ГБ — десятичная запятая для русского."""
    value = float(max(0, num))
    unit = "b"
    for unit in ("b", "kb", "mb", "gb"):
        if value < 1024 or unit == "gb":
            break
        value /= 1024
    text = f"{value:.0f}" if unit in ("b", "kb") or value >= 100 else f"{value:.1f}".rstrip("0").rstrip(".")
    if get_language() == "ru":
        text = text.replace(".", ",")
    return t(f"q.unit_{unit}", n=text)


def memory(mb: int) -> str:
    """4096 → «4 ГБ», 3584 → «3,5 ГБ»."""
    gb = mb / 1024
    text = f"{gb:.1f}".rstrip("0").rstrip(".")
    if get_language() == "ru":
        text = text.replace(".", ",")
    return t("q.unit_gb", n=text)
