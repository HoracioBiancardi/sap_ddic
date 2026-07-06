"""Input validation for user-supplied table names and search terms.

Both validators run as FastAPI dependencies, before any downstream cache
file path is built or any SQL parameter is bound. This closes off path
traversal (a validated ``table_name`` is safe to use in
``cache/{table_name}.json``) and LIKE-pattern injection (a raw ``%`` or
``_`` from the user could otherwise widen a search far beyond intent, even
though bound parameters already rule out classic SQL injection).
"""

import re
import unicodedata

from fastapi import HTTPException, Path, Query

_TABLE_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_/]{0,29}$")
_SEARCH_TERM_RE = re.compile(r"^[A-Z0-9_ /]{1,30}$")


def _strip_accents(text: str) -> str:
    """Removes diacritics so accented input matches its plain-ASCII form.

    Args:
        text: Raw text, possibly containing accented characters (e.g. "ç", "ã").

    Returns:
        The text with combining diacritical marks stripped (e.g. "Produção"
        becomes "Producao"), so business-term search terms typed with proper
        Portuguese accents still match the plain-ASCII synonym dictionary
        and pass the search-term character whitelist.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


class InputValidator:
    """Validates and normalizes user-supplied identifiers before use."""

    @staticmethod
    def validate_table_name(table_name: str = Path(...)) -> str:
        """Validates a table name path parameter.

        Args:
            table_name: Raw table name taken from the request path.

        Returns:
            The normalized (trimmed, uppercased) table name.

        Raises:
            HTTPException: With status 400 if the name does not match a
                valid SAP object-name shape.
        """
        normalized = table_name.strip().upper()
        if not _TABLE_NAME_RE.match(normalized):
            raise HTTPException(status_code=400, detail="Invalid table name.")
        return normalized

    @staticmethod
    def validate_search_term(q: str = Query(..., min_length=1, max_length=30)) -> str:
        """Validates and escapes a search query parameter.

        Args:
            q: Raw search term taken from the request query string.

        Returns:
            The normalized (trimmed, uppercased) term with any literal
            ``%``/``_`` escaped so it is safe to embed in a LIKE pattern.

        Raises:
            HTTPException: With status 400 if the term contains characters
                outside the allowed alphanumeric/underscore/slash/space set.
        """
        normalized = _strip_accents(q.strip()).upper()
        if not _SEARCH_TERM_RE.match(normalized):
            raise HTTPException(status_code=400, detail="Invalid search term.")
        return normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
