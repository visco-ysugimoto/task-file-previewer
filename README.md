# TaskFilePreviewer

このフォルダは `TaskFilePreviewer` 専用です。

## 主要ファイル

- `task_file_previewer.py`: アプリ本体
- `app_version.txt`: 配布版数
- `build_task_file_previewer.ps1`: ビルドスクリプト
- `register_task_file_previewer_context_menu.ps1`: 右クリック連携の登録
- `unregister_task_file_previewer_context_menu.ps1`: 右クリック連携の解除
- `task_file_previewer_flowchart.md`: フローチャート

## ビルド

```powershell
.\build_task_file_previewer.ps1
```

配布 ZIP 名の版数は `app_version.txt` の先頭行を使用します。
例: `1.0.0` の場合は `TaskFilePreviewer_portable_onedir_v1.0.0.zip`

単一exe:

```powershell
.\build_task_file_previewer.ps1 -BuildMode OneFile
```

## 右クリック連携

```powershell
.\register_task_file_previewer_context_menu.ps1
```

コマンド入力を避けたい場合は、以下の `bat` をダブルクリックでも登録できます。

- `register_task_file_previewer_context_menu.bat`
- `register_task_file_previewer_context_menu_include_zip.bat`

解除:

```powershell
.\unregister_task_file_previewer_context_menu.ps1
```

解除用の `bat`:

- `unregister_task_file_previewer_context_menu.bat`
- `unregister_task_file_previewer_context_menu_include_zip.bat`

## 配布

推奨配布物は `dist\TaskFilePreviewer_portable_onedir_v<version>.zip` です。

配布先 PC での導入手順は `distribution_guide.md` を参照してください。
