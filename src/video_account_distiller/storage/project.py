"""Project initialization, state, and run-manifest management."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from video_account_distiller.config import default_config, load_config
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import ProjectState, RunManifest
from video_account_distiller.utils.hashing import sha256_json
from video_account_distiller.utils.ids import new_run_id, stable_id
from video_account_distiller.utils.io import atomic_write_json, atomic_write_text, read_json

PROJECT_DIRECTORIES = (
    "raw/accounts",
    "raw/videos",
    "raw/metrics",
    "raw/comments",
    "raw/transcripts",
    "raw/model-outputs",
    "raw/imports",
    "staging/accounts",
    "staging/videos",
    "staging/metrics",
    "staging/comments",
    "staging/transcripts",
    "normalized",
    "analyses/accounts",
    "analyses/videos",
    "analyses/comments",
    "analyses/comparisons",
    "knowledge-base/accounts",
    "knowledge-base/patterns",
    "knowledge-base/rules",
    "knowledge-base/experiments",
    "knowledge-base/reviews",
    "predictions",
    "publications",
    "reports",
    "runs",
)


class ProjectLayout:
    """Resolved paths and durable state for one local analysis project."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.config_path = self.root / "distiller.yaml"
        self.state_path = self.root / ".distiller-state.json"
        self.status_path = self.root / "STATUS.md"
        self.normalized_dir = self.root / "normalized"
        self.runs_dir = self.root / "runs"

    @classmethod
    def initialize(
        cls, root: Path, *, project_name: str | None = None
    ) -> tuple[ProjectLayout, bool]:
        """Create an idempotent project structure without overwriting user files."""

        layout = cls(root)
        already_initialized = layout.config_path.exists() and layout.state_path.exists()
        layout.root.mkdir(parents=True, exist_ok=True)
        for relative in PROJECT_DIRECTORIES:
            (layout.root / relative).mkdir(parents=True, exist_ok=True)

        name = project_name or layout.root.name
        now = datetime.now(UTC)
        if not layout.config_path.exists():
            atomic_write_text(layout.config_path, default_config(name).as_yaml())
        if not layout.state_path.exists():
            state = ProjectState(
                project_id=stable_id("proj_", str(layout.root)),
                project_name=name,
                created_at=now,
                updated_at=now,
            )
            atomic_write_json(layout.state_path, state.model_dump(mode="json"))
        if not layout.status_path.exists():
            atomic_write_text(
                layout.status_path,
                "# Distiller project status\n\nRun `distiller status --project .` to refresh.\n",
            )
        secrets_example = layout.root / ".distiller-secrets.example"
        if not secrets_example.exists():
            atomic_write_text(
                secrets_example,
                "# Offline phases need no credentials.\n",
            )
        return layout, already_initialized

    @classmethod
    def open(cls, root: Path) -> ProjectLayout:
        """Open an initialized project or raise a stable error."""

        layout = cls(root)
        if not layout.config_path.is_file() or not layout.state_path.is_file():
            raise DistillerError(
                ErrorCode.PROJECT_NOT_INITIALIZED,
                f"Not a distiller project: {layout.root}",
            )
        load_config(layout.config_path)
        return layout

    def load_state(self) -> ProjectState:
        """Read and validate durable project state."""

        return ProjectState.model_validate(read_json(self.state_path))

    def save_state(self, state: ProjectState) -> None:
        """Atomically save project state with a refreshed timestamp."""

        state.updated_at = datetime.now(UTC)
        atomic_write_json(self.state_path, state.model_dump(mode="json"))

    def begin_run(self, command: str, *, input_hashes: list[str] | None = None) -> RunManifest:
        """Create a running manifest in a unique run directory."""

        run_id = new_run_id()
        manifest = RunManifest(
            run_id=run_id,
            command=command,
            started_at=datetime.now(UTC),
            input_hashes=input_hashes or [],
            config_hash=sha256_json(load_config(self.config_path).model_dump(mode="json")),
        )
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        atomic_write_json(run_dir / "manifest.json", manifest.model_dump(mode="json"))
        return manifest

    def finish_run(
        self,
        manifest: RunManifest,
        *,
        success: bool,
        processed_counts: dict[str, int] | None = None,
        output_files: list[str] | None = None,
        warnings: list[str] | None = None,
        errors: list[str] | None = None,
    ) -> RunManifest:
        """Finalize a run manifest and update the project pointer."""

        manifest.finished_at = datetime.now(UTC)
        manifest.status = "success" if success else "failed"
        manifest.processed_counts = processed_counts or {}
        manifest.output_files = output_files or []
        manifest.warnings = warnings or []
        manifest.errors = errors or []
        atomic_write_json(
            self.runs_dir / manifest.run_id / "manifest.json",
            manifest.model_dump(mode="json"),
        )
        state = self.load_state()
        state.last_run_id = manifest.run_id
        self.save_state(state)
        return manifest

    def relative(self, path: Path) -> str:
        """Return a project-relative POSIX path for portable manifests."""

        return path.resolve().relative_to(self.root).as_posix()
