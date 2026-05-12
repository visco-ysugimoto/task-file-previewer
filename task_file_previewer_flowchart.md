# task_file_previewer.py フローチャート

後から見た人が処理の流れを追いやすいように、主要フローを分割して記述します。  
（Mermaid対応ビューアで図として表示できます）

## 1. アプリ全体フロー（起動〜初回表示）

```mermaid
flowchart TD
    A[main起動] --> B{TkinterDnD利用可?}
    B -- Yes --> C[TkinterDnD.Tk生成]
    B -- No --> D[tk.Tk生成]
    C --> E[TaskFilePreviewerApp初期化]
    D --> E
    E --> F[_build_ui]
    F --> G[_install_drag_and_drop]
    G --> H[mainloop開始]

    H --> I{入力操作}
    I -- ファイル選択 --> J[pick_file]
    I -- D&D --> K[_on_drop_file]
    J --> L[load_task_file]
    K --> L

    L --> M{読み込み中?}
    M -- Yes --> N[ステータス更新して終了]
    M -- No --> O{拡張子対応?}
    O -- No --> P[警告表示して終了]
    O -- Yes --> Q[状態初期化/ローディング開始]
    Q --> R[ワーカースレッド開始 _load_preview_worker]

    R --> S[_extract_ordered_bmp_paths]
    S --> T[_pick_sample_paths]
    T --> U[サムネイル逐次生成 _make_preview_item]
    U --> V{先頭画像生成済み?}
    V -- 初回のみ --> W[_on_first_preview_ready]
    V -- それ以外 --> X[生成継続]
    W --> X
    X --> Y[_on_preview_loaded]

    Y --> Z{エラー?}
    Z -- Yes --> ZA[エラーダイアログ/終了]
    Z -- No --> ZB{画像参照あり?}
    ZB -- No --> ZC[画像なしステータスで終了]
    ZB -- Yes --> ZD[サムネイル描画 _render_thumbnails]
    ZD --> ZE[ローディング終了]
```

## 2. ZIP内画像参照の抽出フロー（_extract_ordered_bmp_paths）

```mermaid
flowchart TD
    A[ZipFileを開く] --> B[全エントリ名を正規化]
    B --> C[_find_img_prefix]
    C --> D{imgプレフィックスあり?}
    D -- No --> E[空リスト返却]
    D -- Yes --> F[img配下txt一覧を取得]
    F --> G{txtあり?}
    G -- No --> E
    G -- Yes --> H[先頭txtを1つ選択]
    H --> I[行ごとにFILE=を抽出]
    I --> J{参照名あり?}
    J -- No --> E
    J -- Yes --> K[bmp basename->fullpath辞書化]
    K --> L[参照順でfullpath解決]
    L --> M[解決済みpath配列返却]
```

## 3. 表示上限変更フロー（_on_preview_limit_changed）

```mermaid
flowchart TD
    A[Combobox選択変更] --> B{current_file/all_bmp_pathsあり?}
    B -- No --> X[何もしない]
    B -- Yes --> C{読み込み中?}
    C -- Yes --> Y[待機メッセージ表示]
    C -- No --> D[_parse_preview_limit]
    D --> E[ローディング状態ON]
    E --> F[_reload_preview_worker開始]
    F --> G[_pick_sample_paths]
    G --> H[サムネイル再生成]
    H --> I[_on_preview_loaded]
    I --> J[再描画/ローディングOFF]
```

## 4. 拡大ビューア表示フロー

```mermaid
flowchart TD
    A[サムネイルクリック] --> B[open_viewer_for_path]
    B --> C{all_bmp_pathsあり?}
    C -- No --> X[終了]
    C -- Yes --> D[current_index決定]
    D --> E[_open_viewer_window]
    E --> F[_render_large_image]
    F --> G{画像読み込み成功?}
    G -- No --> H[エラーダイアログ]
    G -- Yes --> I[画像/インデックス/ファイル名更新]
    I --> J[左右キー or 前へ次へ]
    J --> K[_move_index]
    K --> F
```

## 5. 統合図（簡略版・1枚）

```mermaid
flowchart TD
    A[アプリ起動 main] --> B[UI初期化 _build_ui / D&D設定]
    B --> C{ファイル入力}
    C -- 選択 or D&D --> D[load_task_file]
    D --> E{拡張子OKか}
    E -- No --> E1[警告表示して待機へ]
    E1 --> C
    E -- Yes --> F[非同期読込開始]

    F --> G[ZIP解析<br/>_extract_ordered_bmp_paths]
    G --> H[表示対象選定<br/>_pick_sample_paths]
    H --> I[サムネイル生成]
    I --> J{読み込み結果}
    J -- 失敗 --> J1[エラー表示]
    J1 --> C
    J -- 画像なし --> J2[画像なし表示]
    J2 --> C
    J -- 成功 --> K[サムネイル一覧表示]

    K --> L{ユーザー操作}
    L -- 表示上限変更 --> M[再選定/再描画]
    M --> K
    L -- サムネイルクリック --> N[拡大ビューア表示]
    N --> O[前後移動しながら閲覧]
    O --> L
```

## 補足（設計上のポイント）

- UIフリーズ回避のため、重い処理は `_load_preview_worker` / `_reload_preview_worker` で別スレッド実行。
- UI更新は `root.after(0, ...)` 経由でメインスレッドに戻して安全に反映。
- `_load_seq` で「古い読み込み結果」を無効化し、連続操作時の表示競合を防止。
- 先頭サムネイルを先出し表示し、体感待ち時間を短縮。
