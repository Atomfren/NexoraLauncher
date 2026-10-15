"""Сведения о системе."""

import os


def total_memory_mb() -> int:
    """Объём оперативной памяти в МБ (8192, если определить не удалось)."""
    try:
        if os.name == "nt":
            import ctypes

            class MemoryStatusEx(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]

            stat = MemoryStatusEx()
            stat.dwLength = ctypes.sizeof(MemoryStatusEx)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return int(stat.ullTotalPhys // (1024 * 1024))
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // (1024 * 1024))
    except (OSError, ValueError, AttributeError):
        return 8192


def recommended_memory_mb(mod_count: int, total_mb: int | None = None) -> int:
    """Рекомендуемый -Xmx по числу модов, не больше половины RAM."""
    total_mb = total_mb or total_memory_mb()
    if mod_count == 0:
        wanted = 2048
    elif mod_count <= 40:
        wanted = 4096
    elif mod_count <= 120:
        wanted = 6144
    else:
        wanted = 8192
    cap = max(2048, (total_mb // 2) // 512 * 512)
    return min(wanted, cap)
