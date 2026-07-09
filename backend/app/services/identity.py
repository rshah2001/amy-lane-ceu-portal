import re
import unicodedata
from email.utils import parseaddr


def normalize_name(value: str | None) -> str:
    if not value:
        return ""
    # Strip accents (José -> Jose) so exports that drop diacritics still match.
    decomposed = unicodedata.normalize("NFKD", value)
    unaccented = "".join(char for char in decomposed if not unicodedata.combining(char))
    ascii_value = unaccented.encode("ascii", "ignore").decode()
    normalized = re.sub(r"[^a-z0-9]+", " ", ascii_value.casefold()).strip()
    if normalized:
        return normalized
    # Entirely non-Latin names (e.g. CJK) would normalize to "" and never match;
    # fall back to a casefolded, punctuation-free form of the original.
    return " ".join(re.sub(r"[\W_]+", " ", unaccented.casefold()).split())


def normalize_email(value: str | None) -> str | None:
    if not value:
        return None
    candidate = parseaddr(value.strip())[1].strip().lower()
    candidate = candidate.removeprefix("mailto:").strip()
    # Only match on plausible addresses; junk like "n/a" or "name_at_host.com"
    # must never become a matching key that merges unrelated attendees.
    if "@" not in candidate:
        return None
    return candidate or None


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
    value = " ".join(value.split())
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
