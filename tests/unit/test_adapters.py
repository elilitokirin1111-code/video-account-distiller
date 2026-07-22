from __future__ import annotations

import json
from pathlib import Path

import pytest

from video_account_distiller.adapters.files import FileAdapter
from video_account_distiller.adapters.mapping import MappingResolver, load_mapping_file
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import Platform


def test_file_adapter_supports_csv_json_and_jsonl(tmp_path: Path) -> None:
    csv_path = tmp_path / "input.csv"
    csv_path.write_text("id,name\n1,A\n", encoding="utf-8")
    json_path = tmp_path / "input.json"
    json_path.write_text(json.dumps({"records": [{"id": 2}]}), encoding="utf-8")
    jsonl_path = tmp_path / "input.jsonl"
    jsonl_path.write_text('{"id":3}\n', encoding="utf-8")
    adapter = FileAdapter()
    assert adapter.load_records(csv_path) == [{"id": "1", "name": "A"}]
    assert adapter.load_records(json_path) == [{"id": 2}]
    assert adapter.load_records(jsonl_path) == [{"id": 3}]


def test_file_adapter_rejects_missing_and_unsupported(tmp_path: Path) -> None:
    adapter = FileAdapter()
    with pytest.raises(DistillerError) as missing:
        adapter.load_records(tmp_path / "missing.csv")
    assert missing.value.code == ErrorCode.INPUT_MISSING
    unsupported = tmp_path / "input.xlsx"
    unsupported.write_bytes(b"test")
    with pytest.raises(DistillerError) as captured:
        adapter.load_records(unsupported)
    assert captured.value.code == ErrorCode.SCHEMA_INVALID


def test_custom_mapping_and_required_mapping_error(fixtures_dir: Path) -> None:
    mapping = load_mapping_file(fixtures_dir / "cross-platform" / "custom-mapping.yaml")
    assert mapping.fields["platform_account_id"] == "custom_uid"
    resolver = MappingResolver()
    resolved = resolver.resolve(
        entity="accounts",
        platform=Platform.DOUYIN,
        available_fields={"custom_uid", "custom_name", "custom_fans", "custom_snapshot"},
        explicit=mapping,
    )
    assert resolved.timezone == "Asia/Shanghai"
    with pytest.raises(DistillerError) as captured:
        resolver.resolve(
            entity="videos",
            platform=Platform.DOUYIN,
            available_fields={"title"},
        )
    assert captured.value.code == ErrorCode.FIELD_MAPPING_REQUIRED
