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


# Generational suffixes are part of the name, not of the person's identity:
# "Bob Smith" and "Bob Smith Jr." are usually one person written two ways.
# They are NOT interchangeable with each other, though - see names_are_variants.
GENERATIONAL_SUFFIXES = {"jr", "jnr", "sr", "snr", "ii", "iii", "iv"}


def _name_parts(value: str | None) -> tuple[list[str], str | None]:
    """Split a name into its normalized tokens and its generational suffix."""
    tokens = normalize_name(value).split()
    suffix: str | None = None
    # Only ever strip a suffix that trails a real first+last name, so a
    # two-token name like "Iva Sr" keeps both tokens and stays matchable.
    while len(tokens) > 2 and tokens[-1] in GENERATIONAL_SUFFIXES:
        suffix = tokens[-1] if suffix is None else suffix
        tokens.pop()
    return tokens, suffix


def core_name(value: str | None) -> str:
    """A coarse bucketing key: the name without middle names or suffixes.

    "Bob Smith", "Bob A. Smith" and "Bob Smith Jr." all bucket to "bob smith".
    This key only ever *proposes* candidates -- because it also buckets
    "Bob Smith Jr." and "Bob Smith Sr." together, a proposal must always be
    confirmed with names_are_variants before two records are treated as one.
    """
    tokens, _ = _name_parts(value)
    if len(tokens) > 2:
        tokens = [tokens[0], tokens[-1]]
    return " ".join(tokens)


def names_are_variants(left: str | None, right: str | None) -> bool:
    """True when two names are the same person written differently.

    Tolerates what exports and sign-in sheets drop -- a middle name/initial or
    a generational suffix present on one side and absent on the other -- while
    refusing anything that *conflicts*:

    - "Bob Smith Jr." vs "Bob Smith Sr." are two people (a real pattern at
      family-owned dealers), never one.
    - "Bob A. Smith" vs "Bob C. Smith" are two people.
    - "Bob A. Smith" vs "Bob Andrew Smith" are one person (same initial).

    A false merge issues one certificate for two people, which is worse than a
    false split, so anything this function is unsure about must answer False.
    """
    left_tokens, left_suffix = _name_parts(left)
    right_tokens, right_suffix = _name_parts(right)
    if len(left_tokens) < 2 or len(right_tokens) < 2:
        # A single-token name ("Cher", or a truncated export) carries too
        # little signal to merge on.
        return False
    if left_tokens[0] != right_tokens[0] or left_tokens[-1] != right_tokens[-1]:
        return False
    if left_suffix and right_suffix and left_suffix != right_suffix:
        return False
    left_middles = left_tokens[1:-1]
    right_middles = right_tokens[1:-1]
    if not left_middles or not right_middles:
        # One side simply omits the middle name(s): the classic sign-in-sheet
        # vs registration-export difference.
        return True
    # Both spell out a middle name: the initials must line up, so "Bob A."
    # and "Bob Andrew" match while "Bob A." and "Bob C." do not.
    return [token[0] for token in left_middles] == [token[0] for token in right_middles]
