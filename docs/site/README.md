# HP（yorozusolutions.com）掲載用の素材

| ファイル | 置き場所・使い方 |
|---|---|
| `apps-card.html` | `/apps/index.html` に貼るスニペット。`<article>` を「文献蔵 デスクトップ版」の直後に、JSON-LD の ListItem を ItemList 末尾に、`<li>` をフッターに |
| `komonjo-daro/index.html` | そのまま `/apps/komonjo-daro/index.html` として配置（`/apps/pc-tuneup/` と同じ構成） |
| `../images/komonjo-0*.png` | スクリーンショット（3200×2000）。HTML からは GitHub の raw URL で参照しているので、サイト側にコピーしなくても表示される。`/assets/apps/` に置くなら src を差し替え |
| `../images/icon-1024.png` | アイコン |

バージョン表記（v0.12.7）は `apps-card.html` の `app-meta` と JSON-LD、`komonjo-daro/index.html` の `detail-meta`・JSON-LD・「最新版 0.12.7」の 4 か所。
ダウンロードリンクは `releases/latest/download/Komonjo-Daro-Setup.exe` 固定なので、版が上がってもリンクの変更は不要。

スクリーンショットの差し替え: アプリで資料を開き、ウィンドウ幅 1600px 程度で撮る。`docs/images/` に同名で上書きして push すれば HP 側はそのまま。
