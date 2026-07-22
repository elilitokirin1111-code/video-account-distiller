"""Deterministic stratified sampling for account-level analysis."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from video_account_distiller.config import load_config
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import (
    DataQualityFlag,
    SampleItem,
    SampleManifest,
    SamplingCoverage,
)
from video_account_distiller.sampling.dataset import (
    AccountDataset,
    AccountVideoRecord,
    load_account_dataset,
)
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_json, read_json

STRATEGY_VERSION = "1.0.0"
BANDS = ("S", "A", "B", "C", "D")


def _duration_bucket(duration_seconds: float | None) -> str:
    if duration_seconds is None:
        return "unknown"
    if duration_seconds < 30:
        return "short_lt_30s"
    if duration_seconds < 60:
        return "medium_30_59s"
    return "long_ge_60s"


def _pillar(record: AccountVideoRecord) -> str:
    value = record.video.content_type
    return value.strip() if value and value.strip() else "unknown"


def _band(record: AccountVideoRecord) -> str:
    if record.derived is None or record.derived.performance_band is None:
        return "unknown"
    return record.derived.performance_band


def _is_promoted(record: AccountVideoRecord) -> bool:
    metric = record.metric
    return bool(
        record.video.is_ad
        or (metric is not None and metric.is_promoted)
        or (
            metric is not None and metric.promotion_spend is not None and metric.promotion_spend > 0
        )
    )


def _is_outlier(record: AccountVideoRecord) -> bool:
    return bool(
        record.derived is not None
        and record.derived.outlier_flags
        or DataQualityFlag.OUTLIER in record.video.data_quality_flags
    )


def _record_order(record: AccountVideoRecord) -> tuple[float, float, str]:
    published = (
        record.video.published_at.timestamp() if record.video.published_at else float("-inf")
    )
    score = (
        record.derived.performance_score
        if record.derived is not None and record.derived.performance_score is not None
        else float("-inf")
    )
    return (-published, -score, record.video.video_id)


def _default_sample_size(population_size: int, configured_size: int) -> int:
    if population_size < 30:
        return population_size
    if population_size <= 100:
        return min(population_size, max(20, min(configured_size, 40)))
    if population_size <= 500:
        return min(population_size, max(40, min(configured_size, 80)))
    return min(population_size, max(60, min(configured_size, 120)))


def _coverage(records: list[AccountVideoRecord], *, recent_video_ids: set[str]) -> SamplingCoverage:
    return SamplingCoverage(
        performance=dict(sorted(Counter(_band(record) for record in records).items())),
        recency={
            "recent": sum(record.video.video_id in recent_video_ids for record in records),
            "not_recent": sum(record.video.video_id not in recent_video_ids for record in records),
        },
        content_pillar=dict(sorted(Counter(_pillar(record) for record in records).items())),
        duration=dict(
            sorted(
                Counter(
                    _duration_bucket(record.video.duration_seconds) for record in records
                ).items()
            )
        ),
        special={
            "promoted_or_ad": sum(_is_promoted(record) for record in records),
            "outlier": sum(_is_outlier(record) for record in records),
        },
    )


def _sampling_warnings(
    dataset: AccountDataset,
    selected: list[AccountVideoRecord],
    major_pillars: list[str],
) -> list[str]:
    warnings: list[str] = []
    if len(dataset.records) < 30:
        warnings.append("small_sample: fewer than 30 videos; treat results as descriptive")
    if any(record.derived is None for record in dataset.records):
        warnings.append("missing_derived_metrics: some videos have no performance band")
    if any(_pillar(record) == "unknown" for record in dataset.records):
        warnings.append(
            "unknown_content_pillar: content_type is missing for some videos; "
            "Phase 2 uses it as a pillar proxy"
        )
    if any(record.video.published_at is None for record in dataset.records):
        warnings.append("missing_publish_time: recency coverage is partial")
    selected_bands = {_band(record) for record in selected}
    population_bands = {_band(record) for record in dataset.records}
    for band in BANDS:
        if band in population_bands and band not in selected_bands:
            warnings.append(f"sampling_gap: performance band {band} is not represented")
    selected_pillars = {_pillar(record) for record in selected}
    for pillar in major_pillars:
        if pillar not in selected_pillars:
            warnings.append(f"sampling_gap: major content pillar {pillar!r} is not represented")
    return warnings


class SamplingService:
    """Select and persist a reproducible account-local stratified sample."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def _build_manifest(
        self,
        *,
        dataset: AccountDataset,
        requested_size: int | None,
        run_id: str,
        generated_at: datetime,
    ) -> SampleManifest:
        config = load_config(self.project.config_path)
        population = sorted(dataset.records, key=_record_order)
        if not any(record.derived is not None for record in population):
            raise DistillerError(
                ErrorCode.INSUFFICIENT_SAMPLE,
                "Sampling requires account-local derived metrics",
                details={
                    "account_id": dataset.account.account_id,
                    "next_command": (
                        "distiller metrics --project <dir> "
                        f"--account {dataset.account.account_id} --json"
                    ),
                },
            )
        if requested_size is not None and requested_size < 1:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Sample size must be at least 1",
                details={"size": requested_size},
            )
        target_size = (
            min(requested_size, len(population))
            if requested_size is not None
            else _default_sample_size(len(population), config.analysis.default_sample_size)
        )
        requested_value = (
            requested_size if requested_size is not None else config.analysis.default_sample_size
        )

        dated = [record for record in population if record.video.published_at is not None]
        recent_count = min(
            len(dated),
            max(1, math.ceil(len(population) * config.analysis.recent_sample_fraction)),
        )
        recent = dated[:recent_count]
        recent_ids = {record.video.video_id for record in recent}
        recent_cutoff = recent[-1].video.published_at if recent else None

        pillar_counts = Counter(_pillar(record) for record in population)
        pillar_threshold = max(2, math.ceil(len(population) * 0.10))
        major_pillars = [
            pillar
            for pillar, count in sorted(pillar_counts.items(), key=lambda item: (-item[1], item[0]))
            if pillar != "unknown" and count >= pillar_threshold
        ]

        reasons: dict[str, set[str]] = defaultdict(set)
        selected_by_id: dict[str, AccountVideoRecord] = {}

        def include(record: AccountVideoRecord, reason: str) -> None:
            video_id = record.video.video_id
            if video_id in selected_by_id:
                reasons[video_id].add(reason)
                return
            if len(selected_by_id) >= target_size:
                return
            selected_by_id[video_id] = record
            reasons[video_id].add(reason)

        if target_size == len(population):
            for record in population:
                include(record, "population:all")
        else:
            promoted = [record for record in population if _is_promoted(record)]
            outliers = [record for record in population if _is_outlier(record)]
            if promoted:
                include(promoted[0], "special:promoted_or_ad")
            if outliers:
                include(outliers[0], "special:outlier")

            for band in BANDS:
                candidates = [record for record in population if _band(record) == band]
                if candidates:
                    include(candidates[0], f"performance:{band}")

            for pillar in major_pillars:
                candidates = [record for record in population if _pillar(record) == pillar]
                candidate = next(
                    (
                        record
                        for record in candidates
                        if record.video.video_id not in selected_by_id
                    ),
                    candidates[0],
                )
                include(candidate, f"content_pillar:{pillar}")

            for bucket in ("short_lt_30s", "medium_30_59s", "long_ge_60s", "unknown"):
                candidates = [
                    record
                    for record in population
                    if _duration_bucket(record.video.duration_seconds) == bucket
                ]
                if candidates:
                    candidate = next(
                        (
                            record
                            for record in candidates
                            if record.video.video_id not in selected_by_id
                        ),
                        candidates[0],
                    )
                    include(candidate, f"duration:{bucket}")

            recent_quota = max(1, math.ceil(target_size * config.analysis.recent_sample_fraction))
            for record in recent[:recent_quota]:
                include(record, "recency:recent")

            grouped: dict[str, list[AccountVideoRecord]] = {
                band: [record for record in population if _band(record) == band]
                for band in (*BANDS, "unknown")
            }
            positions = {band: 0 for band in grouped}
            while len(selected_by_id) < target_size:
                added = False
                for band in (*BANDS, "unknown"):
                    candidates = grouped[band]
                    while (
                        positions[band] < len(candidates)
                        and candidates[positions[band]].video.video_id in selected_by_id
                    ):
                        positions[band] += 1
                    if positions[band] >= len(candidates):
                        continue
                    include(candidates[positions[band]], f"balanced_fill:{band}")
                    positions[band] += 1
                    added = True
                    if len(selected_by_id) >= target_size:
                        break
                if not added:
                    break

        selected = sorted(selected_by_id.values(), key=_record_order)
        for record in selected:
            video_id = record.video.video_id
            reasons[video_id].add(f"performance:{_band(record)}")
            reasons[video_id].add(f"content_pillar:{_pillar(record)}")
            reasons[video_id].add(f"duration:{_duration_bucket(record.video.duration_seconds)}")
            if video_id in recent_ids:
                reasons[video_id].add("recency:recent")
            if _is_promoted(record):
                reasons[video_id].add("special:promoted_or_ad")
            if _is_outlier(record):
                reasons[video_id].add("special:outlier")

        manifest_key = {
            "account_id": dataset.account.account_id,
            "strategy_version": STRATEGY_VERSION,
            "requested_size": requested_value,
            "target_size": target_size,
            "selected_video_ids": [record.video.video_id for record in selected],
            "input_hashes": dataset.input_hashes,
        }
        manifest_id = stable_id("smp_", manifest_key)
        items = [
            SampleItem(
                video_id=record.video.video_id,
                source_video_id=record.video.source_record_id,
                published_at=record.video.published_at,
                performance_band=(record.derived.performance_band if record.derived else None),
                performance_score=(record.derived.performance_score if record.derived else None),
                content_pillar=_pillar(record),
                duration_bucket=_duration_bucket(record.video.duration_seconds),
                is_promoted=_is_promoted(record),
                is_outlier=_is_outlier(record),
                selection_reasons=sorted(reasons[record.video.video_id]),
                evidence_id=stable_id("evi_", manifest_id, record.video.video_id),
            )
            for record in selected
        ]
        warnings = _sampling_warnings(dataset, selected, major_pillars)
        if requested_size is not None and requested_size > len(population):
            warnings.append(
                f"requested_size_reduced: requested {requested_size}, population {len(population)}"
            )
        return SampleManifest(
            sample_manifest_id=manifest_id,
            account_id=dataset.account.account_id,
            strategy_version=STRATEGY_VERSION,
            population_size=len(population),
            requested_size=requested_value,
            target_size=target_size,
            selected_size=len(items),
            generated_at=generated_at,
            run_id=run_id,
            input_hashes=dataset.input_hashes,
            recent_cutoff=recent_cutoff,
            population_coverage=_coverage(population, recent_video_ids=recent_ids),
            selected_coverage=_coverage(selected, recent_video_ids=recent_ids),
            selected=items,
            warnings=warnings,
        )

    def select(
        self,
        *,
        account_id: str,
        size: int | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Build or reuse a content-addressed sample manifest."""

        dataset = load_account_dataset(self.project, account_id)
        now = datetime.now(UTC)
        draft = self._build_manifest(
            dataset=dataset,
            requested_size=size,
            run_id=stable_id("run_dry_", account_id, size, STRATEGY_VERSION),
            generated_at=now,
        )
        relative = Path("analyses") / "accounts" / account_id / "samples" / draft.sample_manifest_id
        output_path = self.project.root / relative / "sample-manifest.json"
        if output_path.is_file() and not dry_run:
            existing = SampleManifest.model_validate(read_json(output_path))
            return {
                "ok": True,
                "dry_run": False,
                "already_generated": True,
                "manifest": existing.model_dump(mode="json"),
                "output": self.project.relative(output_path),
            }
        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "already_generated": False,
                "manifest": draft.model_dump(mode="json"),
                "output": self.project.relative(output_path),
            }

        run = self.project.begin_run("sample", input_hashes=dataset.input_hashes)
        manifest = self._build_manifest(
            dataset=dataset,
            requested_size=size,
            run_id=run.run_id,
            generated_at=now,
        )
        atomic_write_json(output_path, manifest.model_dump(mode="json"))
        state = self.project.load_state()
        state.last_sample_at = now
        self.project.save_state(state)
        self.project.finish_run(
            run,
            success=True,
            processed_counts={
                "population_videos": manifest.population_size,
                "selected_videos": manifest.selected_size,
            },
            output_files=[self.project.relative(output_path)],
            warnings=manifest.warnings,
        )
        return {
            "ok": True,
            "dry_run": False,
            "already_generated": False,
            "manifest": manifest.model_dump(mode="json"),
            "output": self.project.relative(output_path),
        }
