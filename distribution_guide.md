# TaskFilePreviewer 配布手順

## 配布するもの

推奨の配布物は次の ZIP です。

- `dist\TaskFilePreviewer_portable_onedir_v<version>.zip`

この ZIP には以下が含まれます。

- `TaskFilePreviewer.exe`
- 実行に必要な `_internal` フォルダ
- `register_task_file_previewer_context_menu.bat`
- `register_task_file_previewer_context_menu_include_zip.bat`
- `register_task_file_previewer_context_menu.ps1`
- `unregister_task_file_previewer_context_menu.bat`
- `unregister_task_file_previewer_context_menu_include_zip.bat`
- `unregister_task_file_previewer_context_menu.ps1`
- この手順書 (`distribution_guide.md`)

補足:

- `OneDir` 版は起動が速く、配布先でも扱いやすいため推奨です。
- `TaskFilePreviewer.exe` だけを単独で配布せず、ZIP をそのまま渡してください。

## 配布先 PC での導入手順

1. `TaskFilePreviewer_portable_onedir_v<version>.zip` を任意のフォルダに展開します。
2. 展開先のフォルダ構成を崩さず、そのまま保管します。
3. `TaskFilePreviewer.exe` をダブルクリックして起動確認します。

例:

- `C:\Tools\TaskFilePreviewer\`
- `D:\Apps\TaskFilePreviewer\`

注意:

- `TaskFilePreviewer.exe` と `_internal` フォルダは同じ場所に必要です。
- 後から別の場所へ移動した場合は、右クリック連携を再登録してください。

## 右クリック連携の登録手順

### 方法1: BAT をダブルクリック

展開先フォルダで、次のいずれかをダブルクリックします。

- `register_task_file_previewer_context_menu.bat`
  - 対象: `.ziq` / `.zit` / `.zii`
- `register_task_file_previewer_context_menu_include_zip.bat`
  - 対象: `.ziq` / `.zit` / `.zii` / `.zip`

処理完了後に黒い画面が表示されたままになるので、結果を確認してキーを押して閉じてください。
`bat` は同じフォルダにある `TaskFilePreviewer.exe` を自動で参照します。

### 方法2: PowerShell から実行

展開先フォルダで PowerShell を開き、次を実行しても登録できます。

```powershell
powershell -ExecutionPolicy Bypass -File .\register_task_file_previewer_context_menu.ps1
```

`.zip` も対象にしたい場合:

```powershell
powershell -ExecutionPolicy Bypass -File .\register_task_file_previewer_context_menu.ps1 -IncludeZip
```

## 解除手順

### 方法1: BAT をダブルクリック

展開先フォルダで、次のいずれかをダブルクリックします。

- `unregister_task_file_previewer_context_menu.bat`
  - 対象: `.ziq` / `.zit` / `.zii`
- `unregister_task_file_previewer_context_menu_include_zip.bat`
  - 対象: `.ziq` / `.zit` / `.zii` / `.zip`

### 方法2: PowerShell から実行

展開先フォルダで次を実行します。

```powershell
powershell -ExecutionPolicy Bypass -File .\unregister_task_file_previewer_context_menu.ps1
```

`.zip` も解除する場合:

```powershell
powershell -ExecutionPolicy Bypass -File .\unregister_task_file_previewer_context_menu.ps1 -IncludeZip
```

## 仕様メモ

- 右クリック連携は `HKCU` 配下へ登録するため、通常は管理者権限不要です。
- 右クリックメニューは、登録時に指定された `TaskFilePreviewer.exe` の絶対パスを参照します。
- 展開先を変更した場合は、古い登録を解除するか、そのまま上書きで再登録してください。

## 問題が起きたとき

- 右クリックメニューが出ない:
  - 登録後にエクスプローラーを開き直してください。
  - 対象拡張子が `.ziq` / `.zit` / `.zii` か確認してください。
- 起動しない:
  - `TaskFilePreviewer.exe` と `_internal` フォルダが同じフォルダにあるか確認してください。
- 展開先を移動した:
  - 移動先で `register_task_file_previewer_context_menu.ps1` を再実行してください。
