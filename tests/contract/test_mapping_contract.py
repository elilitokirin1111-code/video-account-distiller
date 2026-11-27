from __future__ import annotations

from video_account_distiller.adapters.mapping import MappingResolver
from video_account_distiller.models import Platform


def test_every_supported_platform_has_all_entity_templates() -> None:
    resolver = MappingResolver()
    for platform in Platform:
        template = resolver.platform_templates[platform.value]
        assert set(template) == {
            "accounts",
            "videos",
            "metrics",
            "comments",
            "audience_profiles",
        }


def test_canonical_columns_work_for_every_platform() -> None:
    resolver = MappingResolver()
    fields_by_entity = {
        "accounts": {"platform_account_id"},
        "videos": {"platform_video_id", "account_id"},
        "metrics": {"video_id", "snapshot_at"},
        "comments": {"platform_comment_id", "video_id", "text"},
        "audience_profiles": {
            "account_id",
            "snapshot_at",
            "dimension",
            "bucket",
            "source_schema_version",
        },
    }
    for platform in Platform:
        for entity, fields in fields_by_entity.items():
            mapping = resolver.resolve(
                entity=entity,  # type: ignore[arg-type]
                platform=platform,
                available_fields=fields,
            )
            assert fields.issubset(mapping.fields)
