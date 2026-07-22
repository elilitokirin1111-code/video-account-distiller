from __future__ import annotations

import pytest

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.storage.duckdb_store import DuckDBStore
from video_account_distiller.storage.project import ProjectLayout


def test_duckdb_views_and_read_only_guard(normalized_project: ProjectLayout) -> None:
    with DuckDBStore(normalized_project.normalized_dir) as store:
        assert store.count("videos") == 6
        rows = store.query("SELECT COUNT(*) AS count FROM videos")
        assert rows == [{"count": 6}]
        with pytest.raises(DistillerError) as captured:
            store.query("DELETE FROM videos")
        assert captured.value.code == ErrorCode.QUERY_FAILED
