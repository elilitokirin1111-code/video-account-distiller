from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
import pytest
from pydantic import BaseModel

from video_account_distiller.storage.parquet import read_models, write_models


class FixtureRow(BaseModel):
    value: int


def test_read_models_uses_single_file_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "rows.parquet"
    write_models(path, [FixtureRow(value=7)])

    def fail_dataset_reader(*args: object, **kwargs: object) -> None:
        raise AssertionError("single-file stores must not use the dataset reader")

    monkeypatch.setattr(pq, "read_table", fail_dataset_reader)

    assert read_models(path, FixtureRow) == [FixtureRow(value=7)]
