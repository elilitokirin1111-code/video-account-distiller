# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import shutil

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


repository = Path(SPECPATH).parents[1]
source_root = repository / "src"

datas = collect_data_files("video_account_distiller")
datas += collect_data_files("video_account_distiller_desktop")
datas += [
    (
        str(repository / "skills" / "video-account-distiller" / "assets" / "prompts"),
        "video_account_distiller/features/prompts",
    ),
    (
        str(source_root / "video_account_distiller" / "collection" / "_mediacrawler_bridge.py"),
        "video_account_distiller/collection",
    ),
    (str(repository / "LICENSE"), "."),
    (str(repository / "THIRD_PARTY_NOTICES.md"), "."),
    (str(repository / "docs" / "desktop-user-guide.md"), "."),
]

# MediaCrawler remains a separate, pinned subprocess environment. Its source
# and lockfile ship without development caches. The bundled uv binary creates
# the locked environment on first use.
mediacrawler_root = repository / "third_party" / "MediaCrawler"
excluded_parts = {
    ".git",
    ".github",
    ".venv",
    "__pycache__",
    "docs",
    "test",
    "tests",
    "webui",
}
if mediacrawler_root.is_dir():
    for source in mediacrawler_root.rglob("*"):
        relative = source.relative_to(mediacrawler_root)
        if not source.is_file() or any(part in excluded_parts for part in relative.parts):
            continue
        if source.suffix in {".pyc", ".pyo"}:
            continue
        target = Path("third_party/MediaCrawler") / relative.parent
        datas.append((str(source), target.as_posix()))
    datas.append(
        (
            str(repository / "packaging" / "windows" / ".distiller-pinned-commit"),
            "third_party/MediaCrawler",
        )
    )

binaries = []
uv_executable = shutil.which("uv")
if uv_executable:
    binaries.append((uv_executable, "bin"))

hiddenimports = collect_submodules("keyring.backends")

a = Analysis(
    [str(source_root / "video_account_distiller_desktop" / "main.py")],
    pathex=[str(source_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["mypy", "pytest", "ruff", "streamlit"],
    noarchive=False,
    optimize=1,
)

# Qt 6 on Windows imports Microsoft's unversioned system ICU API. A developer
# PATH may also contain a version-suffixed third-party `icuuc.dll` (for example
# from Poppler); PyInstaller can mistake that incompatible DLL for the system
# library. Never ship that accidental capture—Windows 10/11 supplies the API.
qt_system_icu_conflicts = {"icuuc.dll", "icudt78.dll"}
a.binaries = [
    entry
    for entry in a.binaries
    if Path(str(entry[0])).name.lower() not in qt_system_icu_conflicts
]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VideoAccountDistiller",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(repository / "build" / "desktop" / "app-icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="VideoAccountDistiller",
)
