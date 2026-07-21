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

from backend.schemas import MartTableNode

_TABLE_NAME_RE = re.compile(r"^/?[A-Z][A-Z0-9_/]{0,29}$")
_SEARCH_TERM_RE = re.compile(r"^[A-Z0-9_ /]{1,30}$")
_TCODE_RE = re.compile(r"^[A-Z0-9_]{1,20}$")

# A mart canvas with more tables than this is almost certainly a mistake (or
# a very slow query) rather than an intentional model.
_MAX_MART_TABLES = 12


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
    def validate_table_name_value(table_name: str) -> str:
        """Validates a single table name that didn't arrive as a path
        parameter (e.g. one entry of a JSON request body's table list).

        Args:
            table_name: Raw table name string.

        Returns:
            The normalized (trimmed, uppercased) table name.

        Raises:
            HTTPException: With status 400 if the name does not match a
                valid SAP object-name shape.
        """
        normalized = table_name.strip().upper()
        if not _TABLE_NAME_RE.match(normalized):
            raise HTTPException(status_code=400, detail=f"Invalid table name: {table_name!r}.")
        return normalized

    @staticmethod
    def validate_tcode(tcode: str = Path(...)) -> str:
        """Validates a transaction code path parameter.

        Args:
            tcode: Raw transaction code taken from the request path.

        Returns:
            The normalized (trimmed, uppercased) transaction code.

        Raises:
            HTTPException: With status 400 if the code does not match a
                valid SAP transaction code shape.
        """
        normalized = tcode.strip().upper()
        if not _TCODE_RE.match(normalized):
            raise HTTPException(status_code=400, detail="Invalid transaction code.")
        return normalized

    @staticmethod
    def validate_mart_nodes(tables: list[MartTableNode]) -> dict[str, str]:
        """Validates a mart request's full canvas node list.

        Args:
            tables: Raw ``{node_id, table_name}`` pairs taken from a
                :class:`backend.schemas.MartGenerateRequest`. The same
                ``table_name`` may legitimately repeat under different
                ``node_id``s (e.g. KNA1 as both "sold-to" and "payer") —
                only ``node_id`` must be unique.

        Returns:
            A mapping of normalized ``node_id`` to normalized ``table_name``,
            in request order.

        Raises:
            HTTPException: With status 400 if any ``node_id``/``table_name``
                doesn't match a valid SAP identifier shape, if the list is
                empty, if a ``node_id`` repeats, or if there are more than
                :data:`_MAX_MART_TABLES` entries.
        """
        if not tables:
            raise HTTPException(status_code=400, detail="At least one table is required.")
        if len(tables) > _MAX_MART_TABLES:
            raise HTTPException(status_code=400, detail=f"Too many tables (max {_MAX_MART_TABLES}).")

        table_names: dict[str, str] = {}
        for node in tables:
            node_id = InputValidator.validate_table_name_value(node.node_id)
            table_name = InputValidator.validate_table_name_value(node.table_name)
            if node_id in table_names:
                raise HTTPException(status_code=400, detail=f"Duplicate node_id: {node_id!r}.")
            table_names[node_id] = table_name

        return table_names

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
