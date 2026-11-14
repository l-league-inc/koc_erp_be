"""Windows 탐색기에 그대로 쓸 수 있는 파일·폴더 이름."""

_ILLEGAL = set('\\/:*?"<>|')
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(10)),
    *(f"LPT{i}" for i in range(10)),
}


def is_windows_name(name: str) -> bool:
    if not name or name in {".", ".."}:
        return False
    if any(char in _ILLEGAL for char in name) or name.endswith((" ", ".")):
        return False
    stem = name.split(".", 1)[0]
    return stem.upper() not in _RESERVED


def sanitize_windows_name(name: str, *, fallback: str) -> str:
    cleaned = "".join("_" if char in _ILLEGAL else char for char in (name or ""))
    cleaned = cleaned.rstrip(" .")
    if not cleaned or cleaned in {".", ".."}:
        cleaned = fallback
    stem = cleaned.split(".", 1)[0]
    if stem.upper() in _RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned[:255]


def suffixed_name(name: str, number: int) -> str:
    marker = f" ({number})"
    if "." in name[1:]:
        base, extension = name.rsplit(".", 1)
        extension = f".{extension}"
    else:
        base, extension = name, ""
    room = 255 - len(marker) - len(extension)
    if room < 1:
        room = 1
    return f"{base[:room]}{marker}{extension}"


def allocate_unique_name(name: str, taken: set[str], *, fallback: str) -> str:
    cleaned = sanitize_windows_name(name, fallback=fallback)
    if cleaned not in taken:
        taken.add(cleaned)
        return cleaned
    number = 2
    while True:
        candidate = suffixed_name(cleaned, number)
        if candidate not in taken:
            taken.add(candidate)
            return candidate
        number += 1
