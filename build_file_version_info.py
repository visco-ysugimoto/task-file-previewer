"""
PyInstaller 用の Windows バージョンリソース (file_version_info.txt) を生成する。

app_version.txt の先頭行（例: 1.0.0）を filevers / 表示用文字列に反映する。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

OUT_NAME = "file_version_info.txt"
APP_VERSION_FILE = Path(__file__).resolve().parent / "app_version.txt"


def _read_semver_line() -> str:
    if not APP_VERSION_FILE.is_file():
        return "0.0.0"
    text = APP_VERSION_FILE.read_text(encoding="utf-8", errors="ignore").strip()
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return "0.0.0"


def _to_numeric_tuple(semver: str) -> tuple[int, int, int, int]:
    nums = [int(x) for x in re.findall(r"\d+", semver)]
    while len(nums) < 4:
        nums.append(0)
    return int(nums[0]), int(nums[1]), int(nums[2]), int(nums[3])


def build_version_info_text() -> str:
    semver = _read_semver_line()
    a, b, c, d = _to_numeric_tuple(semver)
    # プロパティに表示する版文字列（4桁未満はそのまま連結）
    display_ver = semver.strip()[:64] or f"{a}.{b}.{c}.{d}"
    return f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({a}, {b}, {c}, {d}),
    prodvers=({a}, {b}, {c}, {d}),
    mask=0x3F,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', 'Viscotech'),
          StringStruct('FileDescription', 'Task File Image Previewer'),
          StringStruct('FileVersion', '{display_ver}'),
          StringStruct('InternalName', 'TaskFilePreviewer'),
          StringStruct('LegalCopyright', 'Copyright (c) Viscotech'),
          StringStruct('OriginalFilename', 'TaskFilePreviewer.exe'),
          StringStruct('ProductName', 'TaskFilePreviewer'),
          StringStruct('ProductVersion', '{display_ver}')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main() -> int:
    root = Path(__file__).resolve().parent
    out = root / OUT_NAME
    out.write_text(build_version_info_text(), encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
