"""Narrative long-form account analysis report (Chinese, human-readable).

Aggregates the latest distillation, health report, media enrichment, video
analyses, and comment analysis into a deterministic Markdown document meant
for operators who want to imitate the distilled account: positioning, content
strategy, production craft, heat rules, comment needs, and an action list.

Everything is rendered from persisted artifacts - no model calls - so the
report is fast, reproducible, and evidence-backed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined

from video_account_distiller.distillation.pipeline import (
    _latest_comment_analysis,
    _latest_distillation,
    _latest_video_analyses,
    _media_features,
)
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import (
    CommentAnalysis,
    DerivedMetrics,
    MediaFeatureRecord,
    MetricSnapshot,
    SingleVideoAnalysis,
    Video,
)
from video_account_distiller.sampling.dataset import load_account_dataset
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import read_json

NARRATIVE_VERSION = "0.1.0"


def _latest_health_report(project: ProjectLayout, account_id: str) -> dict[str, Any] | None:
    """Load the newest account-health report JSON for the account."""
    report_dir = project.root / "reports" / "accounts" / account_id
    if not report_dir.is_dir():
        return None
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for path in sorted(report_dir.glob("rpt_*/report.json")):
        try:
            payload = read_json(path)
        except (OSError, ValueError):
            continue
        generated_at = payload.get("generated_at")
        if isinstance(generated_at, str):
            try:
                stamp = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
            except ValueError:
                stamp = datetime.min.replace(tzinfo=UTC)
        else:
            stamp = datetime.min.replace(tzinfo=UTC)
        candidates.append((stamp, payload))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _latest_enrichment(project: ProjectLayout, account_id: str) -> dict[str, Any] | None:
    """Load the newest media-enrichment summary for the account."""
    base = project.root / "analyses" / "accounts" / account_id / "media-enrichments"
    if not base.is_dir():
        return None
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for path in sorted(base.glob("ame_*/enrichment.json")):
        try:
            payload = read_json(path)
        except (OSError, ValueError):
            continue
        stamp = datetime.min.replace(tzinfo=UTC)
        raw = payload.get("generated_at")
        if isinstance(raw, str):
            try:
                stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                pass
        candidates.append((stamp, payload))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _video_rows(
    project: ProjectLayout,
    account_id: str,
) -> list[dict[str, Any]]:
    """Combine snapshots, derived metrics, analyses, and media per video."""
    dataset = load_account_dataset(project, account_id)
    video_ids = {record.video.video_id for record in dataset.records}
    analyses = _latest_video_analyses(project, video_ids)
    media = {
        item.video_id: item
        for item in _media_features(project, video_ids)
    }
    rows: list[dict[str, Any]] = []
    for record in dataset.records:
        video: Video = record.video
        metric: MetricSnapshot | None = record.metric
        derived: DerivedMetrics | None = record.derived
        analysis: SingleVideoAnalysis | None = analyses.get(video.video_id)
        media_feature: MediaFeatureRecord | None = media.get(video.video_id)
        semantics = (
            analysis.blind_analysis.semantics.model_dump(mode="json")
            if analysis is not None
            else {}
        )
        rows.append(
            {
                "video_id": video.video_id,
                "title": video.title or "(无标题)",
                "published_at": (
                    video.published_at.isoformat() if video.published_at else None
                ),
                "duration_seconds": video.duration_seconds,
                "likes": metric.likes if metric else None,
                "comments": metric.comments if metric else None,
                "shares": metric.shares if metric else None,
                "saves": metric.saves if metric else None,
                "score": derived.performance_score if derived else None,
                "band": derived.performance_band if derived else None,
                "pillar": semantics.get("primary_pillar"),
                "hook_type": (semantics.get("hook") or {}).get("primary_type"),
                "analysis_status": analysis.status if analysis else None,
                "avg_shot_ms": media_feature.average_shot_duration_ms if media_feature else None,
            }
        )
    rows.sort(key=lambda item: (item["score"] is None, -(item["score"] or 0.0)))
    return rows


def _bands_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for row in rows:
        band = row["band"]
        if band:
            summary[band] = summary.get(band, 0) + 1
    return dict(sorted(summary.items()))


def _format_time(value: str | None) -> str:
    if not value:
        return "未知"
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


class NarrativeReportService:
    """Generate a deterministic Chinese long-form analysis report."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def generate(self, *, account_id: str, dry_run: bool = False) -> dict[str, Any]:
        """Build or reuse the narrative report for one account."""
        try:
            distillation = _latest_distillation(self.project, account_id)
        except DistillerError:
            distillation = None
        health = _latest_health_report(self.project, account_id)
        enrichment = _latest_enrichment(self.project, account_id)
        comment_analysis, _ = _latest_comment_analysis(self.project, account_id)
        rows = _video_rows(self.project, account_id)
        bands = _bands_summary(rows)

        seed = {
            "account_id": account_id,
            "version": NARRATIVE_VERSION,
            "distillation_id": distillation.distillation_id if distillation else None,
            "report_id": (health or {}).get("report_id"),
            "video_rows": [
                {
                    "video_id": row["video_id"],
                    "score": row["score"],
                    "band": row["band"],
                    "pillar": row["pillar"],
                }
                for row in rows
            ],
        }
        narrative_id = stable_id("narr_", seed)
        output_dir = self.project.root / "reports" / "accounts" / account_id / narrative_id
        narrative_path = output_dir / "narrative.md"
        if narrative_path.is_file() and not dry_run:
            return {
                "ok": True,
                "dry_run": False,
                "already_generated": True,
                "outputs": [self.project.relative(narrative_path)],
            }

        run_id = stable_id("run_dry_", narrative_id)
        if not dry_run:
            scope_hashes = (
                [str(item) for item in distillation.data_scope.values()]
                if distillation
                else []
            )
            manifest = self.project.begin_run(
                "report narrative",
                input_hashes=sorted(
                    {
                        *scope_hashes,
                        *((health or {}).get("input_hashes") or []),
                    }
                ),
            )
            run_id = manifest.run_id

        payload = self._build_payload(
            account_id=account_id,
            distillation=distillation,
            health=health,
            enrichment=enrichment,
            comment_analysis=comment_analysis,
            rows=rows,
            bands=bands,
        )
        markdown = self._render(payload)

        if not dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "narrative.md").write_text(markdown, encoding="utf-8")
            (output_dir / "run_id.txt").write_text(run_id, encoding="utf-8")
        return {
            "ok": True,
            "dry_run": dry_run,
            "already_generated": False,
            "outputs": [self.project.relative(narrative_path)],
        }

    def _build_payload(
        self,
        *,
        account_id: str,
        distillation: Any | None,
        health: dict[str, Any] | None,
        enrichment: dict[str, Any] | None,
        comment_analysis: CommentAnalysis | None,
        rows: list[dict[str, Any]],
        bands: dict[str, int],
    ) -> dict[str, Any]:
        stats = {}
        if health:
            stats = dict(health.get("statistics") or {})
        band_order = ("S", "A", "B", "C", "D")
        return {
            "account_id": account_id,
            "generated_at": datetime.now(UTC).isoformat(),
            "stats": stats,
            "bands": {
                band: bands.get(band, 0) for band in band_order if bands.get(band)
            },
            "rows": rows,
            "top_rows": rows[:5],
            "bottom_rows": list(reversed(rows[-5:])),
            "positioning": (
                distillation.positioning.model_dump(mode="json")
                if distillation is not None
                else {}
            ),
            "clusters": (
                [item.model_dump(mode="json") for item in distillation.content_clusters]
                if distillation is not None
                else []
            ),
            "patterns": (
                [item.model_dump(mode="json") for item in distillation.patterns]
                if distillation is not None
                else []
            ),
            "comment_needs": (
                [item.model_dump(mode="json") for item in distillation.comment_need_clusters]
                if distillation is not None
                else []
            ),
            "strengths": distillation.strengths if distillation is not None else [],
            "weaknesses": distillation.weaknesses if distillation is not None else [],
            "copyable": (
                distillation.copyable_factors if distillation is not None else []
            ),
            "actions": (
                distillation.action_recommendations if distillation is not None else []
            ),
            "experiments": (
                distillation.experiment_plan if distillation is not None else []
            ),
            "warnings": distillation.warnings if distillation is not None else [],
            "enrichment": enrichment or {},
            "comment_count": comment_analysis.comment_count if comment_analysis else 0,
        }

    def _render(self, payload: dict[str, Any]) -> str:
        template_path = Path(__file__).parent / "templates" / "narrative.md.j2"
        try:
            environment = Environment(
                undefined=StrictUndefined,
                autoescape=False,
                trim_blocks=True,
                lstrip_blocks=True,
            )
            template = environment.from_string(template_path.read_text(encoding="utf-8"))
            return template.render(**payload).rstrip() + "\n"
        except Exception as exc:
            raise DistillerError(
                ErrorCode.REPORT_GENERATION,
                "Failed to render narrative report",
                details={"reason": str(exc)},
            ) from exc
