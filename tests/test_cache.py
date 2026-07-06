"""Unit tests for backend.cache.MetadataCache."""

from pathlib import Path

from backend.cache import MetadataCache


class TestMetadataCache:
    """Tests for read/write/is_valid behavior of MetadataCache."""

    def test_read_returns_none_when_missing(self, tmp_path: Path) -> None:
        """Reading a table that was never cached returns None."""
        cache = MetadataCache(tmp_path)
        assert cache.read("MARA") is None

    def test_write_then_read_roundtrips(self, tmp_path: Path) -> None:
        """A written cache entry can be read back with its payload intact."""
        cache = MetadataCache(tmp_path)
        contract = {"table_name": "MARA", "columns": []}
        cache.write("MARA", contract, as4date="20240620")

        cached = cache.read("MARA")
        assert cached is not None
        assert cached["payload"] == contract
        assert cached["as4date"] == "20240620"

    def test_is_valid_true_when_as4date_matches(self, tmp_path: Path) -> None:
        """Cache is valid when the stored AS4DATE matches the current one."""
        cache = MetadataCache(tmp_path)
        cache.write("MARA", {"table_name": "MARA"}, as4date="20240620")
        cached = cache.read("MARA")
        assert cache.is_valid(cached, current_as4date="20240620") is True

    def test_is_valid_false_when_as4date_changed(self, tmp_path: Path) -> None:
        """Cache is invalid when the table changed in SAP since it was cached."""
        cache = MetadataCache(tmp_path)
        cache.write("MARA", {"table_name": "MARA"}, as4date="20240620")
        cached = cache.read("MARA")
        assert cache.is_valid(cached, current_as4date="20250101") is False

    def test_read_returns_none_for_corrupted_file(self, tmp_path: Path) -> None:
        """A corrupted cache file is treated as a cache miss, not an error."""
        cache = MetadataCache(tmp_path)
        (tmp_path / "MARA.json").write_text("{not valid json", encoding="utf-8")
        assert cache.read("MARA") is None

    def test_write_creates_cache_directory(self, tmp_path: Path) -> None:
        """The cache directory is created on demand if it does not exist yet."""
        nested_dir = tmp_path / "nested" / "cache"
        cache = MetadataCache(nested_dir)
        assert nested_dir.exists()
        cache.write("MARA", {"table_name": "MARA"}, as4date="20240620")
        assert (nested_dir / "MARA.json").exists()
