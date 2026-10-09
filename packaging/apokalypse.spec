from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


project_root = Path.cwd()
source_root = project_root / "src"
static_dir = source_root / "apokalypse" / "static"

analysis = Analysis(
    [str(source_root / "apokalypse" / "main.py")],
    pathex=[str(source_root)],
    binaries=[],
    datas=[(str(static_dir), "apokalypse/static")],
    hiddenimports=["libtorrent", *collect_submodules("uvicorn")],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
    optimize=1,
)

python_archive = PYZ(analysis.pure)

application = EXE(
    python_archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="BT Apokalypse",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    version=str(project_root / "packaging" / "version_info.txt"),
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

bundle = COLLECT(
    application,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="BT Apokalypse",
)
