"""Immutable transcript import pipeline."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import (
    DataQualityFlag,
    ImportReceipt,
    TranscriptSegment,
)
from video_account_distiller.quality import QualityReport, write_quality_report
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.transcripts.parser import parse_transcript
from video_account_distiller.utils.hashing import sha256_file
from video_account_distiller.utils.ids import new_run_id, stable_id
from video_account_distiller.utils.io import atomic_write_text
from video_account_distiller.utils.lookup import resolve_video


class TranscriptImportService:
    """Import subtitle files against an existing normalized video."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def import_file(
        self,
        *,
        video_id: str,
        source: Path,
        language: str | None = None,
        source_name: str = "user_subtitle",
        dry_run: bool = False,
    ) -> tuple[ImportReceipt | None, QualityReport, bool]:
        """Parse, validate, hash, and stage one transcript file."""

        source = source.expanduser().resolve()
        video = resolve_video(self.project, video_id)
        canonical_video_id = video.video_id
        if not source.is_file():
            raise DistillerError(ErrorCode.INPUT_MISSING, f"Transcript file not found: {source}")
        raw_hash = sha256_file(source)
        state = self.project.load_state()
        existing = next(
            (
                receipt
                for receipt in state.imports
                if receipt.entity == "transcripts"
                and receipt.raw_hash == raw_hash
                and receipt.target_id == canonical_video_id
            ),
            None,
        )
        if existing is not None:
            return (
                existing,
                QualityReport(
                    run_id=existing.run_id,
                    entity="transcripts",
                    input_hashes=[raw_hash],
                    stats={
                        "input_rows": existing.input_rows,
                        "accepted_rows": existing.accepted_rows,
                        "rejected_rows": existing.rejected_rows,
                        "duplicate_rows": existing.duplicate_rows,
                    },
                    warnings=["Transcript hash already imported for this video."],
                ),
                True,
            )

        parsed = parse_transcript(source)
        run_id = new_run_id()
        manifest = None
        if not dry_run:
            manifest = self.project.begin_run("import transcripts", input_hashes=[raw_hash])
            run_id = manifest.run_id
        source_uri = f"raw/imports/transcripts/{raw_hash}{source.suffix.lower()}"
        accepted: list[TranscriptSegment] = []
        seen: set[str] = set()
        duplicate_rows = 0
        for item in parsed:
            segment_id = stable_id(
                "ts_",
                canonical_video_id,
                item.start_ms,
                item.end_ms,
                item.text,
            )
            if segment_id in seen:
                duplicate_rows += 1
                continue
            seen.add(segment_id)
            flags = (
                [DataQualityFlag.TRANSCRIPT_LOW_CONFIDENCE]
                if item.confidence is not None and item.confidence < 0.8
                else []
            )
            accepted.append(
                TranscriptSegment(
                    record_id=segment_id,
                    source_platform=video.platform,
                    source_type="transcript_segment",
                    source_uri=source_uri,
                    source_record_id=item.source_id,
                    collected_at=None,
                    run_id=run_id,
                    raw_hash=raw_hash,
                    data_quality_flags=flags,
                    segment_id=segment_id,
                    video_id=canonical_video_id,
                    start_ms=item.start_ms,
                    end_ms=item.end_ms,
                    text=item.text,
                    speaker=item.speaker,
                    confidence=item.confidence,
                    language=language or video.language,
                    source=source_name,
                )
            )
        report = QualityReport(
            run_id=run_id,
            entity="transcripts",
            input_hashes=[raw_hash],
            stats={
                "input_rows": len(parsed),
                "accepted_rows": len(accepted),
                "rejected_rows": 0,
                "duplicate_rows": duplicate_rows,
            },
            warnings=(
                ["Transcript timing is unavailable for one or more segments."]
                if any(item.start_ms is None or item.end_ms is None for item in accepted)
                else []
            ),
        )
        if dry_run:
            report.warnings.append("Dry run: no project files or state were changed.")
            return None, report, False

        assert manifest is not None
        raw_path = self.project.root / source_uri
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        # Atomically preserve the raw transcript source.
        try:
            with open(raw_path, "xb") as dst:
                dst.write(source.read_bytes())
        except FileExistsError:
            pass
        if sha256_file(raw_path) != raw_hash:
            raise DistillerError(ErrorCode.RAW_INTEGRITY, f"Raw copy hash mismatch: {raw_path}")
        staging_name = f"{canonical_video_id}-{raw_hash}.jsonl"
        staging_path = self.project.root / "staging" / "transcripts" / staging_name
        atomic_write_text(
            staging_path,
            "".join(
                json.dumps(item.model_dump(mode="json"), ensure_ascii=False) + "\n"
                for item in accepted
            ),
        )
        report_json, report_markdown = write_quality_report(
            report, self.project.runs_dir / manifest.run_id
        )
        receipt = ImportReceipt(
            entity="transcripts",
            platform=video.platform,
            source_name=source.name,
            target_id=canonical_video_id,
            raw_hash=raw_hash,
            raw_path=self.project.relative(raw_path),
            staging_path=self.project.relative(staging_path),
            run_id=manifest.run_id,
            input_rows=len(parsed),
            accepted_rows=len(accepted),
            rejected_rows=0,
            duplicate_rows=duplicate_rows,
            quality_report_json=self.project.relative(report_json),
            quality_report_markdown=self.project.relative(report_markdown),
        )
        state.imports.append(receipt)
        state.last_transcript_at = datetime.now(UTC)
        self.project.save_state(state)
        outputs = [
            receipt.raw_path,
            str(receipt.staging_path),
            receipt.quality_report_json,
            receipt.quality_report_markdown,
        ]
        self.project.finish_run(
            manifest,
            success=True,
            processed_counts=report.stats,
            output_files=outputs,
            warnings=report.warnings,
        )
        return receipt, report, False
