# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []

try:
    tmp_ret = collect_all("tkinterdnd2")
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]
except Exception:
    # tkinterdnd2 が未導入でもアプリ本体は起動可能（D&D機能のみ無効）
    pass

icon_path = Path("icon_image.ico")
exe_icon = str(icon_path) if icon_path.exists() else None
if icon_path.exists():
    datas.append((str(icon_path), "."))

_version_path = Path("file_version_info.txt")
_manifest_path = Path("app.manifest")
_exe_opts = {}
if _version_path.exists():
    _exe_opts["version"] = str(_version_path)
if _manifest_path.exists():
    _exe_opts["manifest"] = str(_manifest_path)

a = Analysis(
    ['task_file_previewer.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='TaskFilePreviewer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=exe_icon,
    **_exe_opts,
)
