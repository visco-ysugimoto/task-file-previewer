"""exe / 開発実行の両方で動くリソースパスと Windows 向けウィンドウ設定。"""

from __future__ import annotations

import ctypes
import os
import sys
from typing import TYPE_CHECKING

from PIL import Image, ImageTk

if TYPE_CHECKING:
    import tkinter as tk

APP_ID = "viscotech.TaskFilePreviewer"


def get_resource_path(filename: str) -> str:
    """PyInstaller 配布時と `python task_file_previewer.py` の両方で参照できるファイルパス。"""
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


def set_windows_app_id() -> None:
    """タスクバーで独自アイコンを使うための AppUserModelID（Windows のみ）。"""
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def apply_window_icon(window: "tk.Misc") -> None:
    """タイトルバー / タスクバー向けに icon_image.ico を適用する。"""
    icon_path = get_resource_path("icon_image.ico")
    if not os.path.exists(icon_path):
        return
    try:
        window.iconbitmap(icon_path)
    except Exception:
        pass
    try:
        with Image.open(icon_path) as icon_image:
            icon_photo = ImageTk.PhotoImage(icon_image.convert("RGBA"))
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
        wm_seticon = 0x0080
        hicon_small = ctypes.windll.user32.LoadImageW(
            None, icon_path, image_icon, 16, 16, lr_loadfromfile
        )
        hicon_big = ctypes.windll.user32.LoadImageW(
            None, icon_path, image_icon, 32, 32, lr_loadfromfile
        )
        if hicon_small:
            ctypes.windll.user32.SendMessageW(hwnd, wm_seticon, 0, hicon_small)
        if hicon_big:
            ctypes.windll.user32.SendMessageW(hwnd, wm_seticon, 1, hicon_big)
        setattr(window, "_task_file_previewer_hicon_small", hicon_small)
        setattr(window, "_task_file_previewer_hicon_big", hicon_big)
    except Exception:
        pass
