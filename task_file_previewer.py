"""
タスクファイル (.ziq/.zit/.zii/.zig/.zia) の画像プレビュー専用ツール。

特徴:
- 拡張子を .zip に変更せず、そのまま読み込み
- 展開せずに ZIP 内の画像を直接読み込んで表示
- 最初の txt 内に記載された FILE= の画像リストを参照

コード構成（読み手向けの分割）:
- ``models`` … データクラス（サムネイル1件・ZIPメタデータ）
- ``task_info_parser`` … info.txt の v1/v2 パース
- ``task_zip_reader`` … ZIP から BMP 順序・ver/info の取得（Tk 非依存）
- ``resources`` … アイコン・Windows AppUserModelID・リソースパス
- 本ファイル … Tk GUI・バックグラウンド読み込み・画像表示のみ
"""

from __future__ import annotations

import io
import os
import sys
import threading
import zipfile
from typing import List, Optional

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from models import PreviewItem, TaskFolder, TaskZipMetadata
from resources import apply_window_icon, set_windows_app_id
from task_zip_reader import (
    extract_ordered_bmp_paths,
    extract_task_zip_metadata,
    is_supported_task_archive,
    list_task_folders,
    pick_sample_paths,
)

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
    ("Task Files", "*.zig"),
    ("Task Files", "*.zia"),
    ("ZIP Files", "*.zip"),
    ("All Files", "*.*"),
]
PREVIEW_LIMIT_OPTIONS = ("6", "12", "24", "48", "96", "すべて")
DEFAULT_PREVIEW_LIMIT = 6


class TaskFilePreviewerApp:
    """タスクファイルの画像プレビューを行う GUI アプリ。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        apply_window_icon(self.root)
        self.root.title("Task File Image Previewer")
        self.root.geometry("980x680")
        self.root.minsize(840, 560)

        self.current_file: str = ""
        self.current_task_version: Optional[str] = None
        self.current_task_prefix: Optional[str] = None
        self.task_folders: List[TaskFolder] = []
        self._task_metadata: Optional[TaskZipMetadata] = None
        self.preview_items: List[PreviewItem] = []
        self.all_bmp_paths: List[str] = []
        self.current_index: int = 0
        self._is_loading: bool = False
        self._load_seq: int = 0
        self._preview_limit: Optional[int] = DEFAULT_PREVIEW_LIMIT
        self._thumb_cache: dict[str, bytes] = {}

        self._thumb_refs: List[ImageTk.PhotoImage] = []
        self._viewer_ref: Optional[ImageTk.PhotoImage] = None
        self._thumbnail_columns: int = 4

        self._build_ui()

    def _build_ui(self) -> None:
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
        ttk.Label(top, text="グループ:").pack(side=tk.LEFT, padx=(14, 4))
        self.group_var = tk.StringVar(value="")
        self.group_combo = ttk.Combobox(
            top,
            textvariable=self.group_var,
            values=(),
            state="disabled",
            width=8,
        )
        self.group_combo.pack(side=tk.LEFT)
        self.group_combo.bind("<<ComboboxSelected>>", self._on_group_changed)
        ttk.Label(top, text="タスク:").pack(side=tk.LEFT, padx=(10, 4))
        self.task_var = tk.StringVar(value="")
        self.task_combo = ttk.Combobox(
            top,
            textvariable=self.task_var,
            values=(),
            state="disabled",
            width=8,
        )
        self.task_combo.pack(side=tk.LEFT)
        self.task_combo.bind("<<ComboboxSelected>>", self._on_task_changed)
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
            "使い方: .ziq / .zit / .zii / .zig / .zia を選択すると、内部の img 情報を読み取り、"
            "代表画像を表示します。サムネイルをクリックすると拡大表示します。"
        )
        ttk.Label(self.root, text=note, padding=(12, 0, 12, 12), foreground="#555").pack(
            anchor=tk.W
        )
        self._install_drag_and_drop()

    def _on_canvas_resize(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.canvas_window, width=event.width)
        columns = self._calculate_thumbnail_columns(event.width)
        if columns != self._thumbnail_columns:
            self._thumbnail_columns = columns
            if self.preview_items:
                self._render_thumbnails()

    def _on_thumb_frame_configure(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_mousewheel(self, event: tk.Event) -> None:
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
        if self._is_loading:
            self.status_var.set("読み込み中です。完了までお待ちください。")
            return
        if not is_supported_task_archive(path):
            messagebox.showwarning(
                "未対応ファイル",
                "対応拡張子は .ziq / .zit / .zii / .zig / .zia / .zip のみです。",
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
        self.current_task_prefix = None
        self.task_folders = []
        self.group_var.set("")
        self.task_var.set("")
        self.group_combo.configure(values=(), state="disabled")
        self.task_combo.configure(values=(), state="disabled")
        self._task_metadata = None
        self.version_var.set("")
        self.title_var.set("")
        self.comment_var.set("")
        self.last_updated_var.set("")
        self._set_loading_state(True)
        self._set_stage_message("ZIP構造を確認中...")
        self._clear_thumbnails()

        worker = threading.Thread(
            target=self._load_preview_worker,
            args=(seq, path, None),
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
            candidates = self.root.tk.splitlist(raw_data)
            if not candidates:
                return None
            path = candidates[0].strip()
        except tk.TclError:
            path = raw_data.strip()

        if path.startswith("{") and path.endswith("}"):
            path = path[1:-1]
        return path

    def _parse_preview_limit(self, value: str) -> Optional[int]:
        if value == "すべて":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return DEFAULT_PREVIEW_LIMIT

    def _on_preview_limit_changed(self, _event: tk.Event) -> None:
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

    def _on_group_changed(self, _event: tk.Event) -> None:
        if not self.current_file or self._is_loading:
            return
        group = self.group_var.get()
        task_labels = self._task_labels_for_group(group)
        self.task_combo.configure(values=task_labels)
        if not task_labels:
            return
        self.task_var.set(task_labels[0])
        self._load_selected_task_folder()

    def _on_task_changed(self, _event: tk.Event) -> None:
        if not self.current_file or self._is_loading:
            return
        self._load_selected_task_folder()

    def _load_selected_task_folder(self) -> None:
        selected = self._selected_task_folder()
        if not selected or selected.prefix == self.current_task_prefix:
            self._refresh_task_selector_state()
            return

        self.current_task_prefix = selected.prefix
        self._thumb_cache.clear()
        self._load_seq += 1
        seq = self._load_seq
        self._set_loading_state(True)
        self._set_stage_message("タスクを切り替え中...")
        self.count_var.set("")
        self._clear_thumbnails()

        worker = threading.Thread(
            target=self._load_preview_worker,
            args=(seq, self.current_file, selected.prefix),
            daemon=True,
        )
        worker.start()

    def _set_loading_state(self, is_loading: bool) -> None:
        self._is_loading = is_loading
        if is_loading:
            self.open_button.configure(state=tk.DISABLED)
            self.preview_limit_combo.configure(state="disabled")
            self.group_combo.configure(state="disabled")
            self.task_combo.configure(state="disabled")
            self.loading_frame.pack(anchor=tk.W, pady=(6, 0))
            self.progress.start(12)
        else:
            self.open_button.configure(state=tk.NORMAL)
            if self.all_bmp_paths:
                self.preview_limit_combo.configure(state="readonly")
            self._refresh_task_selector_state()
            self.progress.stop()
            self.loading_frame.pack_forget()
            self.stage_var.set("")

    def _set_stage_message(self, message: str) -> None:
        self.stage_var.set(message)
        self.status_var.set(message)

    def _load_preview_worker(
        self,
        seq: int,
        task_file_path: str,
        task_prefix: Optional[str],
    ) -> None:
        try:
            # Tk のUI更新はメインスレッド限定なので、ワーカースレッドからは after() 経由で反映する。
            self.root.after(0, lambda: self._set_stage_if_current(seq, "ZIP構造を確認中..."))
            task_folders = list_task_folders(task_file_path)
            selected_task_prefix = task_prefix
            if selected_task_prefix is None and task_folders:
                selected_task_prefix = task_folders[0].prefix
            all_bmp_paths = extract_ordered_bmp_paths(
                task_file_path, selected_task_prefix
            )
            task_meta = extract_task_zip_metadata(task_file_path, selected_task_prefix)

            self.root.after(0, lambda: self._set_stage_if_current(seq, "代表画像を選定中..."))
            selected = pick_sample_paths(all_bmp_paths, max_images=self._preview_limit)

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
                            # 1枚目だけ先に出すことで「固まっている感」を減らす。
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
                    seq,
                    all_bmp_paths,
                    preview_items,
                    task_meta,
                    task_folders,
                    selected_task_prefix,
                    None,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            self.root.after(
                0,
                lambda: self._on_preview_loaded(
                    seq, [], [], None, [], None, str(exc)
                ),
            )

    def _reload_preview_worker(
        self,
        seq: int,
        task_file_path: str,
        all_bmp_paths: List[str],
        preview_limit: Optional[int],
    ) -> None:
        try:
            self.root.after(0, lambda: self._set_stage_if_current(seq, "代表画像を再選定中..."))
            selected = pick_sample_paths(all_bmp_paths, max_images=preview_limit)
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
                    self.task_folders,
                    self.current_task_prefix,
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
                    self.task_folders,
                    self.current_task_prefix,
                    str(exc),
                ),
            )

    def _set_stage_if_current(self, seq: int, message: str) -> None:
        # 読み込み中に別ファイルが選ばれたら古いワーカーの表示更新は破棄する。
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
        task_folders: List[TaskFolder],
        task_prefix: Optional[str],
        error: Optional[str],
    ) -> None:
        if seq != self._load_seq:
            return

        if error:
            self.status_var.set("読み込み失敗")
            self.count_var.set("")
            self.current_task_version = None
            self.current_task_prefix = None
            self.task_folders = []
            self.group_var.set("")
            self.task_var.set("")
            self.group_combo.configure(values=(), state="disabled")
            self.task_combo.configure(values=(), state="disabled")
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
        self._apply_task_folders_to_ui(task_folders, task_prefix)
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

    def _apply_task_folders_to_ui(
        self,
        task_folders: List[TaskFolder],
        task_prefix: Optional[str],
    ) -> None:
        self.task_folders = task_folders
        self.current_task_prefix = task_prefix
        group_labels = self._group_labels()
        self.group_combo.configure(values=group_labels)
        selected_group = ""
        selected_task = ""
        for folder in task_folders:
            if folder.prefix == task_prefix:
                selected_group = self._task_folder_group(folder)
                selected_task = self._task_folder_task(folder)
                break
        self.group_var.set(selected_group)
        task_labels = self._task_labels_for_group(selected_group)
        self.task_combo.configure(values=task_labels)
        self.task_var.set(selected_task)
        self._refresh_task_selector_state()

    def _group_labels(self) -> List[str]:
        labels: List[str] = []
        for folder in self.task_folders:
            group = self._task_folder_group(folder)
            if group and group not in labels:
                labels.append(group)
        return labels

    def _task_labels_for_group(self, group: str) -> List[str]:
        return [
            self._task_folder_task(folder)
            for folder in self.task_folders
            if self._task_folder_group(folder) == group
        ]

    def _selected_task_folder(self) -> Optional[TaskFolder]:
        group = self.group_var.get()
        task = self.task_var.get()
        for folder in self.task_folders:
            if (
                self._task_folder_group(folder) == group
                and self._task_folder_task(folder) == task
            ):
                return folder
        return None

    def _task_folder_group(self, folder: TaskFolder) -> str:
        group, _, _task = folder.label.partition("/")
        return group

    def _task_folder_task(self, folder: TaskFolder) -> str:
        _group, _sep, task = folder.label.partition("/")
        return task

    def _refresh_task_selector_state(self) -> None:
        if self._is_loading:
            self.group_combo.configure(state="disabled")
            self.task_combo.configure(state="disabled")
            return

        group_labels = self._group_labels()
        task_labels = self._task_labels_for_group(self.group_var.get())
        if len(group_labels) > 1:
            self.group_combo.configure(state="readonly")
        else:
            self.group_combo.configure(state="disabled")
        if len(task_labels) > 1:
            self.task_combo.configure(state="readonly")
        else:
            self.task_combo.configure(state="disabled")

    def _apply_metadata_to_ui(self, metadata: Optional[TaskZipMetadata]) -> None:
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

    def _make_preview_item(
        self, zf: zipfile.ZipFile, full_path: str
    ) -> Optional[PreviewItem]:
        cached = self._thumb_cache.get(full_path)
        if cached is not None:
            return PreviewItem(full_path_in_zip=full_path, thumb_bytes=cached)
        try:
            with zf.open(full_path) as image_data:
                src = image_data.read()
            with Image.open(io.BytesIO(src)) as image:
                # 一覧は軽量優先。原寸表示はビューア側で都度読み直す。
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
        self._clear_thumbnails()
        if not self.preview_items:
            ttk.Label(
                self.thumb_frame,
                text="表示可能なサムネイルがありません。",
                padding=12,
            ).grid(row=0, column=0, sticky="w")
            return

        canvas_width = self.canvas.winfo_width()
        columns = self._calculate_thumbnail_columns(canvas_width)
        self._thumbnail_columns = columns
        for idx, item in enumerate(self.preview_items):
            row = idx // columns
            col = idx % columns

            pil_img = Image.open(io.BytesIO(item.thumb_bytes))
            tk_img = ImageTk.PhotoImage(pil_img)
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

    def _calculate_thumbnail_columns(self, available_width: int) -> int:
        # サムネイル180px + frame padding/label余白を見込んだ1セル幅。
        cell_width = 220
        if available_width <= 1:
            return self._thumbnail_columns
        return max(1, available_width // cell_width)

    def open_viewer_for_path(self, selected_path: str) -> None:
        if not self.all_bmp_paths:
            return
        try:
            self.current_index = self.all_bmp_paths.index(selected_path)
        except ValueError:
            self.current_index = 0
        self._open_viewer_window()

    def _open_viewer_window(self) -> None:
        viewer = tk.Toplevel(self.root)
        apply_window_icon(viewer)
        viewer.title("画像プレビュー")
        viewer.geometry("920x700")
        viewer.minsize(760, 560)

        top = ttk.Frame(viewer, padding=10)
        top.pack(fill=tk.X)

        index_var = tk.StringVar()
        name_var = tk.StringVar()
        resize_after_id: dict[str, Optional[str]] = {"id": None}

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

        viewer.update_idletasks()
        self._render_large_image(viewer, image_label, index_var, name_var)

        viewer.bind("<Left>", lambda _e: self._move_index(-1, index_var, name_var, image_label))
        viewer.bind("<Right>", lambda _e: self._move_index(1, index_var, name_var, image_label))
        viewer.bind(
            "<Configure>",
            lambda event: self._on_viewer_resized(
                event,
                viewer,
                image_label,
                index_var,
                name_var,
                resize_after_id,
            ),
        )

    def _on_viewer_resized(
        self,
        event: tk.Event,
        viewer: tk.Toplevel,
        image_label: tk.Label,
        index_var: tk.StringVar,
        name_var: tk.StringVar,
        resize_after_id: dict[str, Optional[str]],
    ) -> None:
        if event.widget is not viewer:
            return
        if resize_after_id["id"] is not None:
            viewer.after_cancel(resize_after_id["id"])
        resize_after_id["id"] = viewer.after(
            120,
            lambda: self._render_large_image(viewer, image_label, index_var, name_var),
        )

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
        if not self.current_file or not self.all_bmp_paths:
            return

        path_in_zip = self.all_bmp_paths[self.current_index]
        try:
            with zipfile.ZipFile(self.current_file, "r") as zf:
                with zf.open(path_in_zip) as img_data:
                    src = img_data.read()
            with Image.open(io.BytesIO(src)) as image:
                max_w = image_label.winfo_width() - 4
                max_h = image_label.winfo_height() - 4
                if max_w <= 1 or max_h <= 1:
                    max_w = viewer.winfo_width() - 70
                    max_h = viewer.winfo_height() - 170
                max_w = max(1, max_w)
                max_h = max(1, max_h)
                image.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
                tk_img = ImageTk.PhotoImage(image.convert("RGB"))
            self._viewer_ref = tk_img
            image_label.config(image=tk_img)
            index_var.set(f"{self.current_index + 1} / {len(self.all_bmp_paths)}")
            name_var.set(path_in_zip)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("エラー", f"画像表示に失敗しました。\n{exc}")


def main() -> None:
    set_windows_app_id()
    if TkinterDnD is not None:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    app = TaskFilePreviewerApp(root)

    startup_path = _get_startup_file_from_argv()
    if startup_path:
        root.after(0, lambda p=startup_path: app.load_task_file(p))

    root.mainloop()


def _get_startup_file_from_argv() -> Optional[str]:
    if len(sys.argv) <= 1:
        return None

    path = sys.argv[1].strip().strip('"')
    if path.startswith("{") and path.endswith("}"):
        path = path[1:-1]
    if not os.path.isfile(path):
        return None
    if not is_supported_task_archive(path):
        return None
    return path


if __name__ == "__main__":
    main()
