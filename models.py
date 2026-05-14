"""タスクZIPプレビューアで使うデータ構造（GUI と ZIP読み取りの両方から参照）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class PreviewItem:
    """1枚分のサムネイル表示用データ。"""

    full_path_in_zip: str
    thumb_bytes: bytes


@dataclass
class TaskZipMetadata:
    """ZIP（ver.txt / info.txt）から集約した表示用メタデータ。"""

    version: Optional[str] = None
    title: Optional[str] = None
    comment: Optional[str] = None
    last_updated: Optional[str] = None


@dataclass
class TaskFolder:
    """ZIP 内の viscotech/task/gXX/<task> 1件分。"""

    prefix: str
    label: str
