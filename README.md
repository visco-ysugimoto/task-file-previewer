# TaskFilePreviewer

このフォルダは `TaskFilePreviewer` 専用です。

## 主要ファイル

- `task_file_previewer.py`: Tk GUI・非同期読み込み（エントリ。ここから他モジュールを import）
- `models.py`: データクラス（`PreviewItem` / `TaskZipMetadata`）
- `task_info_parser.py`: `info.txt` の v1/v2 パース
- `task_zip_reader.py`: ZIP から BMP 参照順・ver/info メタデータ取得（Tk 非依存）
- `resources.py`: アイコン・Windows AppUserModelID・リソースパス
- `app_version.txt`: 配布版数（exe のバージョンリソース・ZIP 名に使用）
- `app.manifest`: Windows マニフェスト（DPI / Common Controls 6）
- `build_file_version_info.py`: PyInstaller 用 `file_version_info.txt` の生成
- `build_task_file_previewer.ps1`: ビルドスクリプト
- `register_task_file_previewer_context_menu.ps1`: 右クリック連携の登録
- `unregister_task_file_previewer_context_menu.ps1`: 右クリック連携の解除
- `task_file_previewer_flowchart.md`: フローチャート

## ビルド（Windows アプリケーション / exe）

`build_task_file_previewer.ps1` で PyInstaller を実行し、**ウィンドウアプリ（コンソールなし）**の `TaskFilePreviewer.exe` を生成します。exe のプロパティ（製品名・ファイルバージョンなど）は `app_version.txt` と同期するよう、`file_version_info.txt` をビルド直前に自動生成します。DPI は `app.manifest` で PerMonitorV2 を指定しています。

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
