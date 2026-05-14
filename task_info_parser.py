"""
viscotech/task/gXX/YY/info.txt のテキストからタイトル・コメント・更新日を取り出す。

形式の概要
----------
**v2（文字数前置）** … データ行が `102,2,2,...` で始まり、先頭3フィールドの次が
「タイトル文字数, タイトル本文（カンマ可）, （任意の整数フィールド）, コメント文字数, コメント本文」。
ヘッダ1行目が `3,2,0` のときだけでなく、`3,1,0` でもデータ行がこの形なら v2 として読む。

**v1（列ベース）** … カンマ split 後に「日時6連」とその直前の「整数5連」を行末から探し、
タイトル+コメント領域を切り出す。アンカーが取れないときは固定列インデックスにフォールバック。

文字数は Python の ``len()``（Unicode コードポイント数）に合わせる。
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

# v1: mid 領域をタイトルとコメントに分ける策略（先頭セルをタイトル、残りをコメント結合）
_TASK_INFO_MID_SPLIT = "title_first"

# v1: アンカー探索に失敗したときの固定列（0 起算）
_TASK_INFO_TITLE_INDEX = 4
_TASK_INFO_COMMENT_INDEX = 6
_TASK_INFO_DATETIME_START = 11


def parse_task_info_txt(raw_text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """info.txt 全文から (タイトル, コメント, 更新日表示文字列) を返す。"""
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    if not lines:
        return None, None, None
    header_line = lines[0]
    data_line = lines[1] if len(lines) >= 2 else lines[0]
    v2_header = _header_suggests_length_prefixed(header_line)
    data_v2 = _data_row_looks_length_prefixed(data_line)
    length_row_hint = v2_header or data_v2
    # v2 の可能性があるときは生文字列から先に読む。
    # split(',') 先行だと「タイトル/コメント本文中のカンマ」で壊れるため。
    if length_row_hint:
        parsed = _parse_v2_length_prefixed_line(data_line)
        if parsed is not None:
            return parsed
    parts = data_line.split(",")
    return _parse_v1_split_parts(parts, v2_header_hint=length_row_hint)


def _header_suggests_length_prefixed(header_line: str) -> bool:
    """ヘッダ第2フィールドが 2 以上なら v2 とみなす。"""
    hparts = header_line.split(",")
    if len(hparts) < 2:
        return False
    try:
        sub = int(hparts[1].strip())
    except ValueError:
        return False
    return sub >= 2


def _data_row_looks_length_prefixed(data_line: str) -> bool:
    """データ行自体が titleLen/title/commentLen/comment 形式なら v2 とみなす。"""
    parts = data_line.split(",")
    if len(parts) < 5:
        return False
    if not _is_plain_int_token(parts[3]):
        return False
    if parts[0] == "102" and parts[1] == "2" and parts[2] == "2":
        return True
    return _parse_v2_length_prefixed_line(data_line) is not None


def _parse_v2_after_title(
    data_line: str, pos: int, n_skip: int
) -> Optional[Tuple[Optional[str], Optional[str]]]:
    """タイトル直後から整数を n_skip 個飛ばし、その後の commentLen とコメント本文・日時を解釈する。"""
    p = pos
    for _ in range(n_skip):
        idx = data_line.find(",", p)
        if idx < 0:
            return None
        if not _is_plain_int_token(data_line[p:idx]):
            return None
        p = idx + 1
    idx = data_line.find(",", p)
    if idx < 0:
        return None
    try:
        comment_len = int(data_line[p:idx].strip())
    except ValueError:
        return None
    if comment_len < 0:
        return None
    p = idx + 1
    if p + comment_len > len(data_line):
        return None
    comment = data_line[p : p + comment_len]
    p += comment_len
    tail = data_line[p:]
    if tail.startswith(","):
        tail = tail[1:]
    tail_parts = tail.split(",") if tail else []
    anchor = _find_datetime_anchor(tail_parts)
    if anchor is None:
        return None
    last_s = _format_datetime_at(tail_parts, anchor)
    if len(comment) != comment_len:
        return None
    c: Optional[str] = comment or None
    return (c, last_s)


def _parse_v2_length_prefixed_line(
    data_line: str,
) -> Optional[Tuple[Optional[str], Optional[str], Optional[str]]]:
    """v2: titleLen, title, （任意整数）, commentLen, comment を生の文字列から読む。"""
    pos = 0
    for _ in range(3):
        idx = data_line.find(",", pos)
        if idx < 0:
            return None
        pos = idx + 1
    idx = data_line.find(",", pos)
    if idx < 0:
        return None
    try:
        title_len = int(data_line[pos:idx].strip())
    except ValueError:
        return None
    if title_len < 0:
        return None
    title_start = idx + 1
    if title_start + title_len > len(data_line):
        return None
    title = data_line[title_start : title_start + title_len]
    parts_csv = data_line.split(",")
    # 一部データで title_len が次セル(例: ",4")まで食い込むことがあるため補正する。
    if (
        len(parts_csv) > 5
        and _is_plain_int_token(parts_csv[3])
        and title_len > len(parts_csv[4])
        and title == parts_csv[4] + "," + parts_csv[5]
        and _is_plain_int_token(parts_csv[5])
    ):
        title = parts_csv[4]
    pos = title_start + len(title)
    if pos >= len(data_line) or data_line[pos] != ",":
        return None
    pos += 1
    # タイトル直後に余分な整数フィールドが挟まる揺れがあるため、
    # スキップ数を複数候補で試す。
    for n_skip in (1, 0, 2):
        got = _parse_v2_after_title(data_line, pos, n_skip)
        if got is not None:
            comment, last_s = got
            t: Optional[str] = title or None
            return (t, comment, last_s)
    return None


def _parse_v1_split_parts(
    parts: List[str],
    *,
    v2_header_hint: bool = False,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """カンマ分割済みのデータ行からタイトル・コメント・更新日を取り出す。"""
    anchor = _find_datetime_anchor(parts)
    if anchor is not None:
        mid = parts[4 : anchor - 5]
        title, comment = _split_title_comment_mid(mid, v2_header_hint=v2_header_hint)
        last_s = _format_datetime_at(parts, anchor)
        return title, comment, last_s

    title = _csv_field(parts, _TASK_INFO_TITLE_INDEX)
    comment = _csv_field(parts, _TASK_INFO_COMMENT_INDEX)
    last_s = _format_datetime_at(parts, _TASK_INFO_DATETIME_START)
    return title, comment, last_s


def _csv_field(parts: List[str], index: int) -> Optional[str]:
    if index >= len(parts):
        return None
    s = parts[index].strip()
    return s if s else None


def _find_datetime_anchor(parts: List[str]) -> Optional[int]:
    """日時6連の開始インデックス（直前5セグメントがすべて整数の最も右の候補）。"""
    for i in range(len(parts) - 6, 4, -1):
        if not _five_int_tokens(parts[i - 5 : i]):
            continue
        if _valid_datetime_six(parts, i):
            return i
    return None


def _five_int_tokens(slice5: List[str]) -> bool:
    if len(slice5) != 5:
        return False
    return all(_is_plain_int_token(t) for t in slice5)


def _is_plain_int_token(s: str) -> bool:
    s = s.strip()
    if not s:
        return False
    if s.startswith("-"):
        s = s[1:]
    return bool(s) and s.isdigit()


def _valid_datetime_six(parts: List[str], i: int) -> bool:
    if i + 6 > len(parts):
        return False
    try:
        year = int(parts[i])
        month = int(parts[i + 1])
        day = int(parts[i + 2])
        hour = int(parts[i + 4])
        minute = int(parts[i + 5])
    except (ValueError, TypeError):
        return False
    if not (1990 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31):
        return False
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return False
    return True


def _split_title_comment_mid(
    mid: List[str],
    *,
    v2_header_hint: bool = False,
) -> Tuple[Optional[str], Optional[str]]:
    if not mid:
        return None, None
    if len(mid) == 1:
        s = mid[0].strip()
        return (s if s else None), None
    if len(mid) == 2:
        a, b = mid[0].strip(), mid[1].strip()
        return (a if a else None), (b if b else None)
    if _TASK_INFO_MID_SPLIT == "comment_last":
        title = ",".join(mid[:-1]).strip()
        comment = mid[-1].strip()
        return (title if title else None), (comment if comment else None)
    title = mid[0].strip()
    rest = mid[1:]
    if (
        v2_header_hint
        and len(rest) >= 2
        and _is_plain_int_token(rest[0])
    ):
        try:
            clen = int(rest[0].strip())
        except ValueError:
            clen = -1
        if clen >= 0:
            body = ",".join(rest[1:]).strip()
            if len(body) == clen:
                return (title if title else None), (body if body else None)
    comment = ",".join(rest).strip()
    return (title if title else None), (comment if comment else None)


def _format_datetime_at(parts: List[str], start: int) -> Optional[str]:
    """parts[start:start+6] を year,month,day,国,hour,min として表示用に整形。"""
    if start < 0 or len(parts) < start + 6:
        return None
    try:
        year = int(parts[start])
        month = int(parts[start + 1])
        day = int(parts[start + 2])
        hour = int(parts[start + 4])
        minute = int(parts[start + 5])
    except (ValueError, TypeError):
        return None
    return f"{year}年{month}月{day}日{hour}:{minute:02d}"


# ZIP 内パス探索用（task_zip_reader からも利用）
TASK_INFO_TXT_PATH_RE = re.compile(r"(?i)viscotech/task/g\d+/\d+/info\.txt$")
