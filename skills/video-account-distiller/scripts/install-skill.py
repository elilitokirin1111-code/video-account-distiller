"""Install or uninstall this Skill by copy or symlink."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

SKILL_NAME = "video-account-distiller"


def target_path(destination: Path) -> Path:
    """Resolve and validate the destination target."""

    root = destination.expanduser().resolve()
    target = (root / SKILL_NAME).resolve()
    if target.parent != root or target.name != SKILL_NAME:
        raise ValueError("unsafe destination")
    return target


def install(destination: Path, mode: str) -> Path:
    """Install without overwriting an existing Skill."""

    source = Path(__file__).resolve().parents[1]
    target = target_path(destination)
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"destination already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if mode == "copy":
        shutil.copytree(source, target)
    elif mode == "symlink":
        target.symlink_to(source, target_is_directory=True)
    else:
        raise ValueError(f"unsupported mode: {mode}")
    return target


def uninstall(destination: Path, *, confirmed: bool) -> Path:
    """Remove only the validated Skill target after explicit confirmation."""

    if not confirmed:
        raise ValueError("uninstall requires --yes")
    target = target_path(destination)
    if target.is_symlink():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)
    elif target.exists():
        target.unlink()
    else:
        raise FileNotFoundError(target)
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    install_parser = subparsers.add_parser("install")
    install_parser.add_argument(
        "--destination", type=Path, default=Path.home() / ".codex" / "skills"
    )
    install_parser.add_argument("--mode", choices=("copy", "symlink"), default="copy")
    uninstall_parser = subparsers.add_parser("uninstall")
    uninstall_parser.add_argument(
        "--destination", type=Path, default=Path.home() / ".codex" / "skills"
    )
    uninstall_parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    if args.command == "install":
        changed = install(args.destination, args.mode)
        print(f"installed {SKILL_NAME} -> {changed}")
    else:
        changed = uninstall(args.destination, confirmed=args.yes)
        print(f"uninstalled {SKILL_NAME} from {changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
