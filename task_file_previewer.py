"""
タスクファイル (.ziq/.zit/.zii) の画像プレビュー専用ツール。

特徴:
- 拡張子を .zip に変更せず、そのまま読み込み
- 展開せずに ZIP 内の画像を直接読み込んで表示
- 最初の txt 内に記載された FILE= の画像リストを参照
"""
from __future__ import annotations

import io
import os
import re
import sys
import threading
import zipfile
import ctypes
from dataclasses import dataclass
from typing import List, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

_DND_IMPORT_ERROR: Optional[str] = None
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD  # type: ignore[import-not-found]
except Exception as exc:  # noqa: BLE001
    DND_FILES = None
    TkinterDnD = None
    _DND_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"


SUPPORTED_FILE_TYPES = [
    ("Task Files", "*.ziq"),
    ("Task Files", "*.zit"),
    ("Task Files", "*.zii"),
    ("ZIP Files", "*.zip"),
    ("All Files", "*.*"),
]
PREVIEW_LIMIT_OPTIONS = ("6","12", "24", "48", "96", "すべて")
DEFAULT_PREVIEW_LIMIT = 6
APP_ID = "viscotech.TaskFilePreviewer"


def _get_resource_path(filename: str) -> str:
    """PyInstaller配布/開発実行の両方で使えるリソースパスを返す。"""
    candidate_dirs = [
        os.path.dirname(os.path.abspath(sys.executable))
        if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.abspath(__file__)),
        getattr(sys, "_MEIPASS", ""),
    ]
    for base_dir in candidate_dirs:
        if not base_dir:
            continue
        path = os.path.join(base_dir, filename)
        if os.path.exists(path):
            return path
    return os.path.join(candidate_dirs[0], filename)


def _set_windows_app_id() -> None:
    """タスクバーで埋め込みアイコンを使わせるため AppUserModelID を設定する。"""
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def _apply_window_icon(window: tk.Misc) -> None:
    """Windowsのタイトルバー/タスクバー向けに icon_image.ico を適用する。"""
    icon_path = _get_resource_path("icon_image.ico")
    if not os.path.exists(icon_path):
        return
    try:
        window.iconbitmap(icon_path)
    except Exception:
        pass
    try:
        with Image.open(icon_path) as icon_image:
            icon_photo = ImageTk.PhotoImage(icon_image.convert("RGBA"))
        # 参照保持しないとアイコンが反映されないことがある。
        setattr(window, "_task_file_previewer_icon_ref", icon_photo)
        window.iconphoto(True, icon_photo)
    except Exception:
        pass
    if os.name != "nt":
        return
    try:
        hwnd = window.winfo_id()
        image_icon = 1
        lr_loadfromfile = 0x0010
        icon_small = 0
        icon_big = 1
        wm_seticon = 0x0080
        hicon_small = ctypes.windll.user32.LoadImageW(
            None, icon_path, image_icon, 16, 16, lr_loadfromfile
        )
        hicon_big = ctypes.windll.user32.LoadImageW(
            None, icon_path, image_icon, 32, 32, lr_loadfromfile
        )
        if hicon_small:
            ctypes.windll.user32.SendMessageW(hwnd, wm_seticon, icon_small, hicon_small)
        if hicon_big:
            ctypes.windll.user32.SendMessageW(hwnd, wm_seticon, icon_big, hicon_big)
        setattr(window, "_task_file_previewer_hicon_small", hicon_small)
        setattr(window, "_task_file_previewer_hicon_big", hicon_big)
    except Exception:
        pass


@dataclass
class PreviewItem:
    """プレビュー表示に必要な情報を保持する。"""

    full_path_in_zip: str
    thumb_bytes: bytes


# viscotech/task/gXX/YY/info.txt のデータ行は「カンマのみ」区切り。
# タイトル・コメントにカンマが含まれると単純な列番号では破綻するため、
# 「日時6連 (年,月,日,国,時,分)」とその直前の「整数5連」を行の右側から探索して
# 列位置を決める。5連より左の先頭4列の次から5連手前までをタイトル+コメント領域とみなす。
#
# タイトル領域にカンマが複数あるときの区切り（コメントは1セグメント／タイトルは1セグメントのどちらか想定）:
# - "comment_last": 最後の1セグメントをコメント、それより前をカンマで結合してタイトル
# - "title_first":  先頭1セグメントをタイトル、それより後をカンマで結合してコメント
# 両方にカンマのみで含まれる場合は情報として復元不能のため、必要ならこの定数を切り替える。
_TASK_INFO_MID_SPLIT = "comment_last"

# アンカー探索に失敗したときの従来の固定列(0起算)。カンマを含まない行向け。
_TASK_INFO_TITLE_INDEX = 4
_TASK_INFO_COMMENT_INDEX = 5
_TASK_INFO_DATETIME_START = 11

_TASK_INFO_PATH_RE = re.compile(r"(?i)viscotech/task/g\d+/\d+/info\.txt$")


@dataclass
class TaskZipMetadata:
    """タスクZIPから取得した表示用メタデータ。"""

    version: Optional[str] = None
    title: Optional[str] = None
    comment: Optional[str] = None
    last_updated: Optional[str] = None


class TaskFilePreviewerApp:
    """タスクファイルの画像プレビューを行う GUI アプリ。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        _apply_window_icon(self.root)
        self.root.title("Task File Image Previewer")
        self.root.geometry("980x680")
        self.root.minsize(840, 560)

        self.current_file: str = ""
        self.current_task_version: Optional[str] = None
        self._task_metadata: Optional[TaskZipMetadata] = None
        self.preview_items: List[PreviewItem] = []
        self.all_bmp_paths: List[str] = []
        self.current_index: int = 0
        self._is_loading: bool = False
        # 非同期読み込みの世代番号。古いスレッド結果を破棄するために使う。
        self._load_seq: int = 0
        self._preview_limit: Optional[int] = DEFAULT_PREVIEW_LIMIT
        self._thumb_cache: dict[str, bytes] = {}

        # Tk画像は参照を保持しないとガベージコレクションで消える。
        self._thumb_refs: List[ImageTk.PhotoImage] = []
        self._viewer_ref: Optional[ImageTk.PhotoImage] = None

        self._build_ui()

    def _build_ui(self) -> None:
        # 画面構成:
        # 1) 上部: ファイル選択と表示上限
        # 2) 中央: ステータス/進捗表示
        # 3) 下部: サムネイル一覧(スクロール可能)
        # 4) 最下部: 使い方の補足
        #
        # 役割を分けておくことで、将来のUI変更時に影響範囲を追いやすくする。
        top = ttk.Frame(self.root, padding=12)
        top.pack(fill=tk.X)

        self.file_var = tk.StringVar(value="ファイル未選択")
        self.status_var = tk.StringVar(value="タスクファイルを選択してください。")
        self.count_var = tk.StringVar(value="")
        self.version_var = tk.StringVar(value="")
        self.title_var = tk.StringVar(value="")
        self.comment_var = tk.StringVar(value="")
        self.last_updated_var = tk.StringVar(value="")

        self.open_button = ttk.Button(
            top, text="タスクファイルを開く", command=self.pick_file
        )
        self.open_button.pack(side=tk.LEFT)
        ttk.Label(top, text="表示上限:").pack(side=tk.LEFT, padx=(14, 4))
        self.preview_limit_var = tk.StringVar(value=str(DEFAULT_PREVIEW_LIMIT))
        self.preview_limit_combo = ttk.Combobox(
            top,
            textvariable=self.preview_limit_var,
            values=PREVIEW_LIMIT_OPTIONS,
            state="disabled",
            width=8,
        )
        self.preview_limit_combo.pack(side=tk.LEFT)
        self.preview_limit_combo.bind(
            "<<ComboboxSelected>>", self._on_preview_limit_changed
        )
        ttk.Label(top, textvariable=self.file_var).pack(side=tk.LEFT, padx=(12, 0))

        self.drop_hint_var = tk.StringVar(
            value="ここにタスクファイルをドラッグ＆ドロップできます。"
        )
        self.drop_label = tk.Label(
            self.root,
            textvariable=self.drop_hint_var,
            bg="#eef5ff",
            fg="#224",
            bd=1,
            relief=tk.SOLID,
            padx=12,
            pady=10,
        )
        self.drop_label.pack(fill=tk.X, padx=12, pady=(0, 8))

        info = ttk.Frame(self.root, padding=(12, 0, 12, 6))
        info.pack(fill=tk.X)
        ttk.Label(info, textvariable=self.status_var).pack(anchor=tk.W)
        ttk.Label(info, textvariable=self.count_var).pack(anchor=tk.W, pady=(3, 0))
        ttk.Label(info, textvariable=self.version_var).pack(anchor=tk.W, pady=(3, 0))
        ttk.Label(info, textvariable=self.title_var, wraplength=920).pack(
            anchor=tk.W, pady=(3, 0)
        )
        ttk.Label(info, textvariable=self.comment_var, wraplength=920).pack(
            anchor=tk.W, pady=(3, 0)
        )
        ttk.Label(info, textvariable=self.last_updated_var).pack(
            anchor=tk.W, pady=(3, 0)
        )
        self.loading_frame = ttk.Frame(info)
        self.progress = ttk.Progressbar(
            self.loading_frame, mode="indeterminate", length=220
        )
        self.progress.pack(side=tk.LEFT)
        self.stage_var = tk.StringVar(value="")
        ttk.Label(
            self.loading_frame, textvariable=self.stage_var, foreground="#555"
        ).pack(side=tk.LEFT, padx=(8, 0))

        canvas_area = ttk.Frame(self.root)
        canvas_area.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 12))
        self.canvas = tk.Canvas(canvas_area, bg="#f3f3f3", highlightthickness=0)
        self.v_scrollbar = ttk.Scrollbar(
            canvas_area, orient=tk.VERTICAL, command=self.canvas.yview
        )
        self.canvas.configure(yscrollcommand=self.v_scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.thumb_frame = ttk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window(
            (0, 0), window=self.thumb_frame, anchor="nw"
        )

        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.thumb_frame.bind("<Configure>", self._on_thumb_frame_configure)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", self._on_mousewheel)
        self.canvas.bind("<Button-5>", self._on_mousewheel)
        self.thumb_frame.bind("<MouseWheel>", self._on_mousewheel)
        self.thumb_frame.bind("<Button-4>", self._on_mousewheel)
        self.thumb_frame.bind("<Button-5>", self._on_mousewheel)

        note = (
            "使い方: .ziq / .zit / .zii を選択すると、内部の img 情報を読み取り、"
            "代表画像を表示します。サムネイルをクリックすると拡大表示します。"
        )
        ttk.Label(self.root, text=note, padding=(12, 0, 12, 12), foreground="#555").pack(
            anchor=tk.W
        )
        self._install_drag_and_drop()

    def _on_canvas_resize(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.canvas_window, width=event.width)

    def _on_thumb_frame_configure(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_mousewheel(self, event: tk.Event) -> None:
        # Windows/macOS(Legacy含む)/Linux のイベント差分を吸収する。
        if hasattr(event, "delta") and event.delta:
            step = -1 if event.delta > 0 else 1
            self.canvas.yview_scroll(step, "units")
            return
        if getattr(event, "num", None) == 4:
            self.canvas.yview_scroll(-1, "units")
            return
        if getattr(event, "num", None) == 5:
            self.canvas.yview_scroll(1, "units")

    def pick_file(self) -> None:
        if self._is_loading:
            self.status_var.set("読み込み中です。完了までお待ちください。")
            return
        path = filedialog.askopenfilename(
            title="タスクファイルを選択",
            filetypes=SUPPORTED_FILE_TYPES,
        )
        if not path:
            return
        self.load_task_file(path)

    def load_task_file(self, path: str) -> None:
        # 新規読み込みの起点。
        # ここでは「入力検証」「UI初期化」「非同期処理の起動」までを担当し、
        # 実際の重いI/O処理は worker 側へ委譲する。
        if self._is_loading:
            self.status_var.set("読み込み中です。完了までお待ちください。")
            return
        if not self._is_supported_task_file(path):
            messagebox.showwarning(
                "未対応ファイル",
                "対応拡張子は .ziq / .zit / .zii / .zip のみです。",
            )
            return
        self._load_seq += 1
        seq = self._load_seq
        self.current_file = path
        self._thumb_cache.clear()
        self._preview_limit = DEFAULT_PREVIEW_LIMIT
        self.preview_limit_var.set(str(DEFAULT_PREVIEW_LIMIT))
        self.file_var.set(path)
        self.status_var.set("読み込み中...")
        self.count_var.set("")
        self.current_task_version = None
        self._task_metadata = None
        self.version_var.set("")
        self.title_var.set("")
        self.comment_var.set("")
        self.last_updated_var.set("")
        self._set_loading_state(True)
        self._set_stage_message("ZIP構造を確認中...")
        self._clear_thumbnails()

        # 重いZIP解析はUIスレッド外で実行し、画面フリーズを避ける。
        worker = threading.Thread(
            target=self._load_preview_worker,
            args=(seq, path),
            daemon=True,
        )
        worker.start()

    def _install_drag_and_drop(self) -> None:
        if DND_FILES is None:
            self.drop_hint_var.set(
                "ドラッグ&ドロップを使うには、実行中のPythonへ tkinterdnd2 の導入が必要です。"
            )
            detail = (
                "D&D初期化失敗\n\n"
                f"Python: {sys.executable}\n"
                f"原因: {_DND_IMPORT_ERROR or 'tkinterdnd2 が見つかりません'}\n\n"
                "以下を同じ環境で実行してください:\n"
                f"\"{sys.executable}\" -m pip install tkinterdnd2"
            )
            self.status_var.set("D&Dは未有効です(詳細はドロップ欄をクリック)")
            self.drop_label.bind(
                "<Button-1>", lambda _e, msg=detail: messagebox.showinfo("D&D設定", msg)
            )
            return
        if not hasattr(self.root, "drop_target_register"):
            self.drop_hint_var.set(
                "この実行環境ではドラッグ＆ドロップ初期化に失敗しました。"
            )
            return

        self.drop_label.drop_target_register(DND_FILES)
        self.drop_label.dnd_bind("<<Drop>>", self._on_drop_file)
        self.root.drop_target_register(DND_FILES)
        self.root.dnd_bind("<<Drop>>", self._on_drop_file)

    def _on_drop_file(self, event: tk.Event) -> None:
        if self._is_loading:
            self.status_var.set("読み込み中です。完了までお待ちください。")
            return
        path = self._parse_drop_path(getattr(event, "data", ""))
        if not path:
            self.status_var.set("ドロップされた内容を読み取れませんでした。")
            return
        self.load_task_file(path)

    def _parse_drop_path(self, raw_data: str) -> Optional[str]:
        if not raw_data:
            return None
        try:
            # D&Dデータは "{...}" や複数パスで来るため splitlist で正規化する。
            candidates = self.root.tk.splitlist(raw_data)
            if not candidates:
                return None
            path = candidates[0].strip()
        except tk.TclError:
            path = raw_data.strip()

        if path.startswith("{") and path.endswith("}"):
            path = path[1:-1]
        return path

    @staticmethod
    def _is_supported_task_file(path: str) -> bool:
        lower = path.lower()
        return lower.endswith((".ziq", ".zit", ".zii", ".zip"))

    def _parse_preview_limit(self, value: str) -> Optional[int]:
        if value == "すべて":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return DEFAULT_PREVIEW_LIMIT

    def _on_preview_limit_changed(self, _event: tk.Event) -> None:
        # すでに抽出済みの all_bmp_paths を使って再描画だけを行う。
        # ファイル全体の再解析を避けることで、表示上限変更の応答を速くする。
        if not self.current_file or not self.all_bmp_paths:
            return
        if self._is_loading:
            self.status_var.set("読み込み中です。完了までお待ちください。")
            return

        self._preview_limit = self._parse_preview_limit(self.preview_limit_var.get())
        self._load_seq += 1
        seq = self._load_seq
        self._set_loading_state(True)
        self._set_stage_message("表示上限を変更中...")
        self.status_var.set("表示上限の変更を反映中...")

        worker = threading.Thread(
            target=self._reload_preview_worker,
            args=(seq, self.current_file, list(self.all_bmp_paths), self._preview_limit),
            daemon=True,
        )
        worker.start()

    def _set_loading_state(self, is_loading: bool) -> None:
        # ローディング中は操作を絞って競合操作を防ぎ、
        # 完了時に必要な操作のみ再度有効化する。
        self._is_loading = is_loading
        if is_loading:
            self.open_button.configure(state=tk.DISABLED)
            self.preview_limit_combo.configure(state="disabled")
            self.loading_frame.pack(anchor=tk.W, pady=(6, 0))
            self.progress.start(12)
        else:
            self.open_button.configure(state=tk.NORMAL)
            if self.all_bmp_paths:
                self.preview_limit_combo.configure(state="readonly")
            self.progress.stop()
            self.loading_frame.pack_forget()
            self.stage_var.set("")

    def _set_stage_message(self, message: str) -> None:
        self.stage_var.set(message)
        self.status_var.set(message)

    def _load_preview_worker(self, seq: int, task_file_path: str) -> None:
        # 初回読み込みワーカー:
        # - ZIPから参照順BMP一覧を抽出
        # - 表示上限に応じたサンプルを選定
        # - サムネイルを生成
        # - UIスレッドへ結果通知
        #
        # UI体感を上げるため、1枚目ができた時点で先行表示する。
        try:
            # UI更新は Tk のメインスレッドでのみ安全なため after() で戻す。
            self.root.after(0, lambda: self._set_stage_if_current(seq, "ZIP構造を確認中..."))
            all_bmp_paths = self._extract_ordered_bmp_paths(task_file_path)
            task_meta = self._extract_task_zip_metadata(task_file_path)

            self.root.after(0, lambda: self._set_stage_if_current(seq, "代表画像を選定中..."))
            selected = self._pick_sample_paths(all_bmp_paths, max_images=self._preview_limit)

            preview_items: List[PreviewItem] = []
            first_sent = False
            total_selected = len(selected)

            if selected:
                with zipfile.ZipFile(task_file_path, "r") as zf:
                    for idx, full_path in enumerate(selected):
                        self.root.after(
                            0,
                            lambda i=idx, t=total_selected: self._set_stage_if_current(
                                seq, f"サムネイル生成中... ({i + 1}/{t})"
                            ),
                        )
                        item = self._make_preview_item(zf, full_path)
                        if not item:
                            continue
                        preview_items.append(item)
                        if not first_sent:
                            # 先頭だけ先に描画し、体感待ち時間を短くする。
                            first_sent = True
                            self.root.after(
                                0,
                                lambda item=item, total=len(all_bmp_paths), s=total_selected: (
                                    self._on_first_preview_ready(seq, all_bmp_paths, item, total, s)
                                ),
                            )

            self.root.after(
                0,
                lambda: self._on_preview_loaded(
                    seq, all_bmp_paths, preview_items, task_meta, None
                ),
            )
        except Exception as exc:  # noqa: BLE001
            self.root.after(
                0, lambda: self._on_preview_loaded(seq, [], [], None, str(exc))
            )

    def _reload_preview_worker(
        self,
        seq: int,
        task_file_path: str,
        all_bmp_paths: List[str],
        preview_limit: Optional[int],
    ) -> None:
        # 表示上限変更時の再生成ワーカー。
        # all_bmp_paths は再利用できるため、ZIP内TXTの再解析は行わない。
        try:
            self.root.after(0, lambda: self._set_stage_if_current(seq, "代表画像を再選定中..."))
            selected = self._pick_sample_paths(all_bmp_paths, max_images=preview_limit)
            total_selected = len(selected)
            preview_items: List[PreviewItem] = []

            if selected:
                with zipfile.ZipFile(task_file_path, "r") as zf:
                    for idx, full_path in enumerate(selected):
                        self.root.after(
                            0,
                            lambda i=idx, t=total_selected: self._set_stage_if_current(
                                seq, f"サムネイル再生成中... ({i + 1}/{t})"
                            ),
                        )
                        item = self._make_preview_item(zf, full_path)
                        if item:
                            preview_items.append(item)

            self.root.after(
                0,
                lambda: self._on_preview_loaded(
                    seq,
                    all_bmp_paths,
                    preview_items,
                    self._task_metadata,
                    None,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            self.root.after(
                0,
                lambda: self._on_preview_loaded(
                    seq,
                    all_bmp_paths,
                    [],
                    self._task_metadata,
                    str(exc),
                ),
            )

    def _set_stage_if_current(self, seq: int, message: str) -> None:
        # すでに別ファイル読み込みが始まっていれば、この更新は無視する。
        if seq != self._load_seq:
            return
        self._set_stage_message(message)

    def _on_first_preview_ready(
        self,
        seq: int,
        all_bmp_paths: List[str],
        first_item: PreviewItem,
        total_paths: int,
        total_selected: int,
    ) -> None:
        if seq != self._load_seq:
            return
        self.all_bmp_paths = all_bmp_paths
        self.preview_items = [first_item]
        self.count_var.set(
            f"画像参照数: {total_paths} / 表示数: 1/{max(1, total_selected)}"
        )
        self.status_var.set("先頭画像を表示しました。残りを読み込み中...")
        self._render_thumbnails()

    def _on_preview_loaded(
        self,
        seq: int,
        all_bmp_paths: List[str],
        preview_items: List[PreviewItem],
        metadata: Optional[TaskZipMetadata],
        error: Optional[str],
    ) -> None:
        # 読み込み完了時のUI反映を一元化する。
        # 正常/異常/画像なしをここで分岐させることで、
        # worker側は「結果を渡すだけ」の責務にできる。
        if seq != self._load_seq:
            return

        if error:
            self.status_var.set("読み込み失敗")
            self.count_var.set("")
            self.current_task_version = None
            self._task_metadata = None
            self.version_var.set("")
            self.title_var.set("")
            self.comment_var.set("")
            self.last_updated_var.set("")
            self._set_loading_state(False)
            messagebox.showerror("エラー", f"読み込みに失敗しました。\n{error}")
            return

        self.all_bmp_paths = all_bmp_paths
        self.preview_items = preview_items
        self._apply_metadata_to_ui(metadata)

        if not all_bmp_paths:
            self.status_var.set("画像参照が見つかりませんでした。")
            self.count_var.set("")
            self._set_loading_state(False)
            return

        self.status_var.set("読み込み完了")
        self.count_var.set(f"画像参照数: {len(all_bmp_paths)} / 表示数: {len(preview_items)}")
        self._render_thumbnails()
        self._set_loading_state(False)

    def _apply_metadata_to_ui(self, metadata: Optional[TaskZipMetadata]) -> None:
        """ZIP から得たメタデータをラベルへ反映する。"""
        self._task_metadata = metadata
        if not metadata:
            self.current_task_version = None
            self.version_var.set("タスクバージョン: 不明")
            self.title_var.set("タイトル: 不明")
            self.comment_var.set("コメント: 不明")
            self.last_updated_var.set("最終更新日: 不明")
            return
        self.current_task_version = metadata.version
        self.version_var.set(
            f"タスクバージョン: {metadata.version}"
            if metadata.version
            else "タスクバージョン: 不明"
        )
        self.title_var.set(
            f"タイトル: {metadata.title}" if metadata.title else "タイトル: 不明"
        )
        self.comment_var.set(
            f"コメント: {metadata.comment}" if metadata.comment else "コメント: 不明"
        )
        self.last_updated_var.set(
            f"最終更新日: {metadata.last_updated}"
            if metadata.last_updated
            else "最終更新日: 不明"
        )

    def _extract_task_zip_metadata(self, task_file_path: str) -> TaskZipMetadata:
        """ver.txt と viscotech/task/gXX/YY/info.txt から表示用情報をまとめて取得する。"""
        with zipfile.ZipFile(task_file_path, "r") as zf:
            raw_names = zf.namelist()
            normalized_names = [name.replace("\\", "/") for name in raw_names]
            ver_path = self._find_ver_txt_path(normalized_names)
            version: Optional[str] = None
            last_from_zip: Optional[str] = None
            if ver_path:
                with zf.open(ver_path) as ver_file:
                    raw_ver = ver_file.read().decode("utf-8", errors="ignore")
                version = self._parse_task_version_text(raw_ver)
                try:
                    last_from_zip = self._format_zip_date_time(zf.getinfo(ver_path))
                except KeyError:
                    last_from_zip = None

            info_path = self._find_task_info_txt_path(raw_names, normalized_names)
            title: Optional[str] = None
            comment: Optional[str] = None
            last_from_info: Optional[str] = None
            if info_path:
                with zf.open(info_path) as info_file:
                    raw_info = info_file.read().decode("utf-8-sig", errors="ignore")
                title, comment, last_from_info = self._parse_task_info_txt(raw_info)

            last_updated = last_from_info or last_from_zip
            return TaskZipMetadata(
                version=version,
                title=title,
                comment=comment,
                last_updated=last_updated,
            )

    @staticmethod
    def _find_ver_txt_path(normalized_names: List[str]) -> Optional[str]:
        for name in normalized_names:
            lower = name.lower()
            if lower == "viscotech/ver.txt" or lower.endswith("/viscotech/ver.txt"):
                return name
        return None

    @staticmethod
    def _find_task_info_txt_path(
        raw_names: List[str], normalized_names: List[str]
    ) -> Optional[str]:
        """viscotech/task/gXX/YY/info.txt を探す。img フォルダ隣接を優先し、無ければパターン一致で1件選ぶ。"""
        norm_to_raw: dict[str, str] = {}
        for raw, norm in zip(raw_names, normalized_names):
            norm_to_raw.setdefault(norm, raw)

        keys = list(norm_to_raw.keys())
        img_prefix = TaskFilePreviewerApp._find_img_prefix(keys)
        if img_prefix and img_prefix.endswith("img/"):
            candidate = img_prefix[: -len("img/")] + "info.txt"
            if candidate in norm_to_raw:
                return norm_to_raw[candidate]

        matches = [norm_to_raw[k] for k in keys if _TASK_INFO_PATH_RE.search(k)]
        if not matches:
            return None
        matches.sort(key=lambda p: p.replace("\\", "/").lower())
        return matches[0]

    @staticmethod
    def _parse_task_info_txt(
        raw_text: str,
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """info.txt からタイトル・コメント・更新日表示文字列を取り出す。"""
        lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
        if not lines:
            return None, None, None
        # 1行目はヘッダ(例: 3,1,0)、2行目にタスクCSVが入る
        data_line = lines[1] if len(lines) >= 2 else lines[0]
        parts = data_line.split(",")
        title, comment, last_s = TaskFilePreviewerApp._parse_task_info_parts(parts)
        return title, comment, last_s

    @staticmethod
    def _parse_task_info_parts(
        parts: List[str],
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """split 済み列からタイトル・コメント・更新日を取り出す。"""
        anchor = TaskFilePreviewerApp._find_task_info_datetime_anchor(parts)
        if anchor is not None:
            mid = parts[4 : anchor - 5]
            title, comment = TaskFilePreviewerApp._split_title_comment_mid(mid)
            last_s = TaskFilePreviewerApp._format_task_info_datetime_at(parts, anchor)
            return title, comment, last_s

        title = TaskFilePreviewerApp._csv_field(parts, _TASK_INFO_TITLE_INDEX)
        comment = TaskFilePreviewerApp._csv_field(parts, _TASK_INFO_COMMENT_INDEX)
        last_s = TaskFilePreviewerApp._format_task_info_datetime_at(
            parts, _TASK_INFO_DATETIME_START
        )
        return title, comment, last_s

    @staticmethod
    def _csv_field(parts: List[str], index: int) -> Optional[str]:
        if index >= len(parts):
            return None
        s = parts[index].strip()
        return s if s else None

    @staticmethod
    def _find_task_info_datetime_anchor(parts: List[str]) -> Optional[int]:
        """日時6連の開始インデックス。直前5セグメントがすべて整数である最も右の候補を採用。"""
        # 先頭4 + タイトル/コメント(最低1+1) + 5 + 6  → anchor 最低 10
        for i in range(len(parts) - 6, 9, -1):
            if not TaskFilePreviewerApp._task_info_five_int_tokens(parts[i - 5 : i]):
                continue
            if TaskFilePreviewerApp._task_info_valid_datetime_six(parts, i):
                return i
        return None

    @staticmethod
    def _task_info_five_int_tokens(slice5: List[str]) -> bool:
        if len(slice5) != 5:
            return False
        for t in slice5:
            if not TaskFilePreviewerApp._is_plain_int_token(t):
                return False
        return True

    @staticmethod
    def _is_plain_int_token(s: str) -> bool:
        s = s.strip()
        if not s:
            return False
        if s.startswith("-"):
            s = s[1:]
        return bool(s) and s.isdigit()

    @staticmethod
    def _task_info_valid_datetime_six(parts: List[str], i: int) -> bool:
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

    @staticmethod
    def _split_title_comment_mid(mid: List[str]) -> tuple[Optional[str], Optional[str]]:
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
        comment = ",".join(mid[1:]).strip()
        return (title if title else None), (comment if comment else None)

    @staticmethod
    def _format_task_info_datetime_at(parts: List[str], start: int) -> Optional[str]:
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

    @staticmethod
    def _format_zip_date_time(zi: zipfile.ZipInfo) -> str:
        y, m, d, hh, mm, ss = zi.date_time
        return f"{y:04d}-{m:02d}-{d:02d} {hh:02d}:{mm:02d}:{ss:02d}"

    def _extract_ordered_bmp_paths(self, task_file_path: str) -> List[str]:
        # ZIPから「表示順付きBMP一覧」を作る中核処理。
        # 優先ルール:
        # - /img/ 配下を対象
        # - 最初の txt に記載された FILE= の順序を採用
        # - 実在する bmp のみを解決して返す
        #
        # これにより、単純なファイル名ソートではなく
        # タスク作成側が意図した順番でプレビューできる。
        with zipfile.ZipFile(task_file_path, "r") as zf:
            all_names = [name.replace("\\", "/") for name in zf.namelist()]

            img_prefix = self._find_img_prefix(all_names)
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
            with zf.open(first_txt) as txt:
                for raw_line in txt:
                    line = raw_line.decode("utf-8", errors="ignore")
                    # FILE= の出現順を保持して閲覧順の期待に合わせる。
                    if "FILE=" in line:
                        bmp_name = line.split("FILE=", 1)[1].strip()
                        if bmp_name:
                            referenced_names.append(bmp_name)

            if not referenced_names:
                return []

            bmp_lookup = {
                os.path.basename(name).lower(): name
                for name in all_names
                if name.startswith(img_prefix) and name.lower().endswith(".bmp")
            }

            resolved = []
            for bmp_name in referenced_names:
                full_path = bmp_lookup.get(bmp_name.lower())
                if full_path:
                    resolved.append(full_path)
            return resolved

    def _extract_task_version(self, task_file_path: str) -> Optional[str]:
        """互換用。ZIP を再度開くため、バッチ取得には _extract_task_zip_metadata を使う。"""
        return self._extract_task_zip_metadata(task_file_path).version

    @staticmethod
    def _parse_task_version_text(raw_text: str) -> Optional[str]:
        # 1,2,3行目をメジャー/マイナー/パッチ、5行目をビルド番号として扱う。
        lines = [line.strip() for line in raw_text.splitlines()]
        if len(lines) < 5:
            return None
        major, minor, patch, build = lines[0], lines[1], lines[2], lines[4]
        if not all((major, minor, patch, build)):
            return None
        return f"{major}.{minor}.{patch}B{build}"

    @staticmethod
    def _find_img_prefix(all_names: List[str]) -> Optional[str]:
        # zip内の階層は案件ごとに変化するため、
        # 固定パスではなく「/img/ が現れる最初の位置」から探索する。
        for name in all_names:
            normalized = name.replace("\\", "/")
            if "/img/" in normalized:
                index = normalized.index("/img/")
                return normalized[: index + len("/img/")]
        return None

    @staticmethod
    def _pick_sample_paths(
        all_paths: List[str], max_images: Optional[int]
    ) -> List[str]:
        if not all_paths:
            return []
        if max_images is None:
            return all_paths
        if len(all_paths) <= max_images:
            return all_paths
        # 等間隔サンプリングで先頭〜末尾の偏りを抑える。
        step = max(1, len(all_paths) // max_images)
        return all_paths[::step][:max_images]

    def _make_preview_item(
        self, zf: zipfile.ZipFile, full_path: str
    ) -> Optional[PreviewItem]:
        # 1画像分のサムネイル生成。
        # 同一画像への再アクセスはキャッシュを返し、再読み込みコストを削減する。
        cached = self._thumb_cache.get(full_path)
        if cached is not None:
            return PreviewItem(full_path_in_zip=full_path, thumb_bytes=cached)
        try:
            with zf.open(full_path) as image_data:
                src = image_data.read()
            with Image.open(io.BytesIO(src)) as image:
                # 一覧表示は軽量なJPEGサムネイルに変換して負荷を下げる。
                image.thumbnail((180, 180), Image.Resampling.BILINEAR)
                buf = io.BytesIO()
                image.convert("RGB").save(buf, format="JPEG", quality=72)
            thumb_bytes = buf.getvalue()
            self._thumb_cache[full_path] = thumb_bytes
            return PreviewItem(full_path_in_zip=full_path, thumb_bytes=thumb_bytes)
        except Exception:
            return None

    def _clear_thumbnails(self) -> None:
        for child in self.thumb_frame.winfo_children():
            child.destroy()
        self._thumb_refs.clear()

    def _render_thumbnails(self) -> None:
        # preview_items をグリッドに再描画する。
        # 描画前に一度クリアすることで、古い結果が混在しないようにする。
        self._clear_thumbnails()
        if not self.preview_items:
            ttk.Label(
                self.thumb_frame,
                text="表示可能なサムネイルがありません。",
                padding=12,
            ).grid(row=0, column=0, sticky="w")
            return

        columns = 4
        for idx, item in enumerate(self.preview_items):
            row = idx // columns
            col = idx % columns

            pil_img = Image.open(io.BytesIO(item.thumb_bytes))
            tk_img = ImageTk.PhotoImage(pil_img)
            # ボタンに設定した画像が消えないよう参照を保持する。
            self._thumb_refs.append(tk_img)

            frame = ttk.Frame(self.thumb_frame, padding=8)
            frame.grid(row=row, column=col, sticky="nsew")

            btn = tk.Button(
                frame,
                image=tk_img,
                relief=tk.RAISED,
                bd=1,
                command=lambda p=item.full_path_in_zip: self.open_viewer_for_path(p),
                cursor="hand2",
            )
            btn.pack()
            ttk.Label(
                frame,
                text=os.path.basename(item.full_path_in_zip),
                width=24,
                anchor="center",
            ).pack(pady=(5, 0))

    def open_viewer_for_path(self, selected_path: str) -> None:
        if not self.all_bmp_paths:
            return
        try:
            self.current_index = self.all_bmp_paths.index(selected_path)
        except ValueError:
            self.current_index = 0
        self._open_viewer_window()

    def _open_viewer_window(self) -> None:
        # サムネイル一覧とは独立した Toplevel を開き、
        # ここで前後移動(ボタン/矢印キー)を閉じた文脈で扱う。
        viewer = tk.Toplevel(self.root)
        _apply_window_icon(viewer)
        viewer.title("画像プレビュー")
        viewer.geometry("920x700")
        viewer.minsize(760, 560)

        top = ttk.Frame(viewer, padding=10)
        top.pack(fill=tk.X)

        index_var = tk.StringVar()
        name_var = tk.StringVar()

        ttk.Button(top, text="◀ 前へ", command=lambda: self._move_index(-1, index_var, name_var, image_label)).pack(
            side=tk.LEFT
        )
        ttk.Button(top, text="次へ ▶", command=lambda: self._move_index(1, index_var, name_var, image_label)).pack(
            side=tk.LEFT, padx=(8, 12)
        )
        ttk.Label(top, textvariable=index_var).pack(side=tk.LEFT)

        image_area = ttk.Frame(viewer, padding=10)
        image_area.pack(fill=tk.BOTH, expand=True)

        image_label = tk.Label(image_area, bg="#111")
        image_label.pack(fill=tk.BOTH, expand=True)

        bottom = ttk.Frame(viewer, padding=(10, 0, 10, 10))
        bottom.pack(fill=tk.X)
        ttk.Label(bottom, textvariable=name_var, foreground="#555").pack(anchor=tk.W)

        self._render_large_image(viewer, image_label, index_var, name_var)

        viewer.bind("<Left>", lambda _e: self._move_index(-1, index_var, name_var, image_label))
        viewer.bind("<Right>", lambda _e: self._move_index(1, index_var, name_var, image_label))

    def _move_index(
        self,
        direction: int,
        index_var: tk.StringVar,
        name_var: tk.StringVar,
        image_label: tk.Label,
    ) -> None:
        if not self.all_bmp_paths:
            return
        self.current_index = (self.current_index + direction) % len(self.all_bmp_paths)
        self._render_large_image(image_label.winfo_toplevel(), image_label, index_var, name_var)

    def _render_large_image(
        self,
        viewer: tk.Toplevel,
        image_label: tk.Label,
        index_var: tk.StringVar,
        name_var: tk.StringVar,
    ) -> None:
        # 現在インデックスの原寸画像を読み、ビューアサイズに合わせて描画する。
        # 大きい画像でも表示を崩さないよう、最大幅/高さを毎回計算する。
        if not self.current_file or not self.all_bmp_paths:
            return

        path_in_zip = self.all_bmp_paths[self.current_index]
        try:
            with zipfile.ZipFile(self.current_file, "r") as zf:
                with zf.open(path_in_zip) as img_data:
                    src = img_data.read()
            with Image.open(io.BytesIO(src)) as image:
                # ビューア枠に収まるよう都度リサイズして表示する。
                max_w = max(400, viewer.winfo_width() - 70)
                max_h = max(300, viewer.winfo_height() - 170)
                image.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
                tk_img = ImageTk.PhotoImage(image.convert("RGB"))
            # 参照保持しないとLabel上の画像が消える場合がある。
            self._viewer_ref = tk_img
            image_label.config(image=tk_img)
            index_var.set(f"{self.current_index + 1} / {len(self.all_bmp_paths)}")
            name_var.set(path_in_zip)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("エラー", f"画像表示に失敗しました。\n{exc}")


def main() -> None:
    _set_windows_app_id()
    if TkinterDnD is not None:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    app = TaskFilePreviewerApp(root)

    # 右クリックメニューなどから "TaskFilePreviewer.exe <path>" で起動された場合は
    # 初期表示後に対象ファイルを自動で読み込む。
    startup_path = _get_startup_file_from_argv()
    if startup_path:
        root.after(0, lambda p=startup_path: app.load_task_file(p))

    root.mainloop()


def _get_startup_file_from_argv() -> Optional[str]:
    """起動引数から読み込み対象ファイルを取り出す。"""
    if len(sys.argv) <= 1:
        return None

    # 右クリック連携では先頭引数に選択ファイルが渡される。
    path = sys.argv[1].strip().strip('"')
    if path.startswith("{") and path.endswith("}"):
        path = path[1:-1]
    if not os.path.isfile(path):
        return None
    if not TaskFilePreviewerApp._is_supported_task_file(path):
        return None
    return path


if __name__ == "__main__":
    main()
