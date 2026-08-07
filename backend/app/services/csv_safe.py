"""Neutralize spreadsheet formula injection in exported CSV cells.

Excel, LibreOffice and Google Sheets treat a cell that starts with ``=``,
``+``, ``-`` or ``@`` as a *formula*, and legacy Excel additionally honours
``\\t``/``\\r`` as cell separators that can smuggle a formula into the next
cell. Our exports carry values that anonymous callers control (public check-in
sets the attendee name, the public survey sets the free-text answers and the
business location), so an attacker can post ``=cmd|'/C calc'!A1`` and have it
execute when an admin opens the downloaded report.

The fix is the standard one: prefix a risky cell with a single apostrophe,
which every spreadsheet reads as "this is text". The apostrophe is not part of
the stored value -- it only exists in the exported file.

Tradeoff on the ``-``/``+`` prefixes
------------------------------------
Blanket-quoting every leading ``-`` would render ordinary negative numbers as
``'-5``, which looks broken in a CEU report full of scores and hours. So a cell
whose *entire* content parses as a number is left alone: a spreadsheet parses
``-5`` as the number -5, and a bare number cannot reference cells, call
functions, or launch a process. Anything that is not purely numeric (e.g.
``-2+cmd|'/C calc'!A1``) still gets quoted. The residual risk of the exemption
is cosmetic only, and it keeps the exports readable.
"""

# Leading characters a spreadsheet may interpret as the start of a formula (or,
# for tab/CR, as a cell break that lets one follow).
FORMULA_PREFIXES = ("=", "+", "-", "@")
SEPARATOR_PREFIXES = ("\t", "\r")


def _is_plain_number(text: str) -> bool:
    """True when the whole cell is just a number (``-5``, ``+1.25``, ``3``)."""
    try:
        float(text)
    except (TypeError, ValueError):
        return False
    return True


def csv_safe(value: object) -> str:
    """Render ``value`` as a CSV cell that no spreadsheet will run as a formula.

    Apply this to every user-derived cell in an export. Do NOT apply it to our
    own hardcoded header strings -- those are trusted and quoting them would
    only make the header ugly.
    """
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    if not text:
        return text
    # Leading whitespace is trimmed by some importers, so a " =cmd" cell can
    # still land as a formula; decide on the first meaningful character.
    leading = text.lstrip(" \t\r\n")[:1]
    if text[0] in SEPARATOR_PREFIXES:
        return f"'{text}"
    if leading in FORMULA_PREFIXES and not _is_plain_number(text.strip()):
        return f"'{text}"
    return text
