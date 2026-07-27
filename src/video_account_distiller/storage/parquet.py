"""Atomic Parquet storage for normalized model records."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import TypeVar

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


def write_models(path: Path, records: Sequence[BaseModel]) -> None:
    """Atomically write validated model records to Parquet."""

    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [record.model_dump(mode="python") for record in records]
    table = pa.Table.from_pylist(rows)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    try:
        pq.write_table(table, temp_name, compression="zstd")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def read_models(path: Path, model_type: type[ModelT]) -> list[ModelT]:
    """Read a Parquet table and validate every record with Pydantic."""

    if not path.is_file():
        return []
    # These stores are always concrete single files. ``pq.read_table`` routes
    # through the dataset layer, which imports pandas and may query Windows WMI
    # during platform detection. Reading the file directly avoids that
    # unrelated dependency path and is materially faster for repeated lookups.
    table = pq.ParquetFile(path).read()
    return [model_type.model_validate(row) for row in table.to_pylist()]
