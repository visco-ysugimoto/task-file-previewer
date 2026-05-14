"""
タスクZIP（.ziq 等）からメタデータと img 参照順の BMP 一覧を読み取る。

GUI（Tk）には依存しない。ZIP を開いてパス解決・デコードのみ行う。
"""

from __future__ import annotations

import os
import re
import sys
import zipfile
from typing import List, Optional

_pkg = os.path.dirname(os.path.abspath(__file__))
if _pkg not in sys.path:
    sys.path.insert(0, _pkg)

from models import TaskFolder, TaskZipMetadata
from task_info_parser import TASK_INFO_TXT_PATH_RE, parse_task_info_txt

TASK_FOLDER_RE = re.compile(r"(?i)(^|.*/)viscotech/task/(g\d+)/([^/]+)/")


def is_supported_task_archive(path: str) -> bool:
    """プレビュー対象とみなす拡張子かどうか。"""
    lower = path.lower()
    return lower.endswith((".ziq", ".zit", ".zii", ".zig", ".zia", ".zip"))


def extract_task_zip_metadata(
    task_file_path: str, task_prefix: Optional[str] = None
) -> TaskZipMetadata:
    """ver.txt と info.txt から TaskZipMetadata を組み立てる。"""
    with zipfile.ZipFile(task_file_path, "r") as zf:
        raw_names = zf.namelist()
        normalized_names = [name.replace("\\", "/") for name in raw_names]
        norm_to_raw = _normalized_to_raw_map(raw_names, normalized_names)
        ver_path = find_ver_txt_path(normalized_names)
        version: Optional[str] = None
        last_from_zip: Optional[str] = None
        if ver_path:
            with zf.open(norm_to_raw.get(ver_path, ver_path)) as ver_file:
                raw_ver = ver_file.read().decode("utf-8", errors="ignore")
            version = parse_task_version_text(raw_ver)
            try:
                last_from_zip = format_zip_date_time(
                    zf.getinfo(norm_to_raw.get(ver_path, ver_path))
                )
            except KeyError:
                last_from_zip = None

        info_path = find_task_info_txt_path(raw_names, normalized_names, task_prefix)
        title: Optional[str] = None
        comment: Optional[str] = None
        last_from_info: Optional[str] = None
        if info_path:
            with zf.open(info_path) as info_file:
                raw_info = info_file.read().decode("utf-8-sig", errors="ignore")
            title, comment, last_from_info = parse_task_info_txt(raw_info)

        last_updated = last_from_info or last_from_zip
        return TaskZipMetadata(
            version=version,
            title=title,
            comment=comment,
            last_updated=last_updated,
        )


def list_task_folders(task_file_path: str) -> List[TaskFolder]:
    """ZIP 内の viscotech/task/gXX/<task> フォルダを列挙する。"""
    with zipfile.ZipFile(task_file_path, "r") as zf:
        normalized_names = [name.replace("\\", "/") for name in zf.namelist()]
    return discover_task_folders(normalized_names)


def discover_task_folders(normalized_names: List[str]) -> List[TaskFolder]:
    folders: dict[str, TaskFolder] = {}
    for name in normalized_names:
        match = TASK_FOLDER_RE.search(name)
        if not match:
            continue
        prefix = name[: match.end()].rstrip("/")
        group = match.group(2)
        task = match.group(3)
        folders.setdefault(prefix, TaskFolder(prefix=prefix, label=f"{group}/{task}"))
    return sorted(folders.values(), key=lambda folder: _task_folder_sort_key(folder.label))


def _task_folder_sort_key(label: str) -> tuple[int, str, int, str]:
    group, _, task = label.partition("/")
    group_num = _first_int(group)
    task_num = _first_int(task)
    return group_num, group.lower(), task_num, task.lower()


def _first_int(value: str) -> int:
    match = re.search(r"\d+", value)
    if not match:
        return 10**9
    return int(match.group(0))


def find_ver_txt_path(normalized_names: List[str]) -> Optional[str]:
    for name in normalized_names:
        lower = name.lower()
        if lower == "viscotech/ver.txt" or lower.endswith("/viscotech/ver.txt"):
            return name
    return None


def find_task_info_txt_path(
    raw_names: List[str],
    normalized_names: List[str],
    task_prefix: Optional[str] = None,
) -> Optional[str]:
    """viscotech/task/gXX/YY/info.txt。img 隣接を優先し、無ければパターン一致で1件。"""
    norm_to_raw: dict[str, str] = {}
    for raw, norm in zip(raw_names, normalized_names):
        norm_to_raw.setdefault(norm, raw)

    keys = list(norm_to_raw.keys())
    if task_prefix:
        normalized_prefix = task_prefix.rstrip("/")
        candidate = f"{normalized_prefix}/info.txt"
        if candidate in norm_to_raw:
            return norm_to_raw[candidate]

    # まず /img/ と同じ案件フォルダ配下の info.txt を優先する。
    # ZIP に複数 task が入るケースでも、表示対象との対応を取りやすくするため。
    img_prefix = find_img_prefix(keys, task_prefix)
    if img_prefix and img_prefix.endswith("img/"):
        candidate = img_prefix[: -len("img/")] + "info.txt"
        if candidate in norm_to_raw:
            return norm_to_raw[candidate]

    matches = [norm_to_raw[k] for k in keys if TASK_INFO_TXT_PATH_RE.search(k)]
    if not matches:
        return None
    matches.sort(key=lambda p: p.replace("\\", "/").lower())
    return matches[0]


def parse_task_version_text(raw_text: str) -> Optional[str]:
    """ver.txt: 1〜3行が版、5行目がビルド番号。"""
    lines = [line.strip() for line in raw_text.splitlines()]
    if len(lines) < 5:
        return None
    major, minor, patch, build = lines[0], lines[1], lines[2], lines[4]
    if not all((major, minor, patch, build)):
        return None
    return f"{major}.{minor}.{patch}B{build}"


def format_zip_date_time(zi: zipfile.ZipInfo) -> str:
    y, m, d, hh, mm, ss = zi.date_time
    return f"{y:04d}-{m:02d}-{d:02d} {hh:02d}:{mm:02d}:{ss:02d}"


def find_img_prefix(
    all_names: List[str], task_prefix: Optional[str] = None
) -> Optional[str]:
    """ZIP 内で `/img/` が現れる最初のパスから img フォルダのプレフィックスを得る。"""
    if task_prefix:
        expected = task_prefix.rstrip("/") + "/img/"
        for name in all_names:
            normalized = name.replace("\\", "/")
            if normalized.startswith(expected):
                return expected
        return None

    for name in all_names:
        normalized = name.replace("\\", "/")
        if "/img/" in normalized:
            index = normalized.index("/img/")
            return normalized[: index + len("/img/")]
    return None


def extract_ordered_bmp_paths(
    task_file_path: str, task_prefix: Optional[str] = None
) -> List[str]:
    """
    最初の img 直下 txt の FILE= 順で BMP パス一覧を返す。
    実在する bmp のみ、参照順を維持する。
    """
    with zipfile.ZipFile(task_file_path, "r") as zf:
        raw_names = zf.namelist()
        all_names = [name.replace("\\", "/") for name in raw_names]
        norm_to_raw = _normalized_to_raw_map(raw_names, all_names)

        img_prefix = find_img_prefix(all_names, task_prefix)
        if not img_prefix:
            return []

        txt_files = sorted(
            name
            for name in all_names
            if name.startswith(img_prefix) and name.lower().endswith(".txt")
        )
        if not txt_files:
            return []

        first_txt = txt_files[0]
        referenced_names: List[str] = []
        with zf.open(norm_to_raw.get(first_txt, first_txt)) as txt:
            for raw_line in txt:
                line = raw_line.decode("utf-8", errors="ignore")
                if "FILE=" in line:
                    bmp_name = line.split("FILE=", 1)[1].strip()
                    if bmp_name:
                        referenced_names.append(bmp_name)

        if not referenced_names:
            return []

        # FILE= 側はファイル名だけ持つため、basename -> 実パスの辞書に変換して解決する。
        bmp_lookup = {
            os.path.basename(name).lower(): norm_to_raw.get(name, name)
            for name in all_names
            if name.startswith(img_prefix) and name.lower().endswith(".bmp")
        }

        resolved: List[str] = []
        for bmp_name in referenced_names:
            full_path = bmp_lookup.get(bmp_name.lower())
            if full_path:
                resolved.append(full_path)
        return resolved


def _normalized_to_raw_map(raw_names: List[str], normalized_names: List[str]) -> dict[str, str]:
    norm_to_raw: dict[str, str] = {}
    for raw, norm in zip(raw_names, normalized_names):
        norm_to_raw.setdefault(norm, raw)
    return norm_to_raw


def pick_sample_paths(all_paths: List[str], max_images: Optional[int]) -> List[str]:
    """表示上限。None なら全件。超える場合は等間隔に間引く。"""
    if not all_paths:
        return []
    if max_images is None:
        return all_paths
    if len(all_paths) <= max_images:
        return all_paths
    step = max(1, len(all_paths) // max_images)
    return all_paths[::step][:max_images]
