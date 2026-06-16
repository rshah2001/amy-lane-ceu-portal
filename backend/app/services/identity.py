import re
import unicodedata
from email.utils import parseaddr


def normalize_name(value: str | None) -> str:
    if not value:
        return ""
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", ascii_value.lower()).strip()


def normalize_email(value: str | None) -> str | None:
    if not value:
        return None
    parsed = parseaddr(value.strip())[1].lower()
    return parsed or None


def is_valid_email(value: str | None) -> bool:
    if not value:
        return False
    return re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value.strip()) is not None


def humanize_name(value: str | None) -> str:
    """Convert exported "Last, First M" names into "First M Last" order.

    Microsoft Teams attendance exports list names last-name-first; certificates
    and other rosters use natural order. Leaves anything else untouched.
    """
    if not value:
        return ""
    value = value.strip()
    if value.count(",") == 1:
        last, first = (part.strip() for part in value.split(","))
        if last and first:
            return f"{first} {last}"
    return value


def split_name(full_name: str) -> tuple[str | None, str | None]:
    parts = full_name.strip().split()
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[-1]

