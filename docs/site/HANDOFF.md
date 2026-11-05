# Komonjo-Daro　HP 掲載 引き渡し資料（yorozusolutions.com/apps/ 用）

更新: 2026-11-05　／　対象バージョン: v0.4.1　／　連絡: hidetako（GitHub）

## 1. 掲載位置と形式

- ページ: https://www.yorozusolutions.com/apps/ の「デスクトップアプリ（Windows）」セクション
- 位置: 「文献蔵 デスクトップ版」の直後、「PC TuneUp」の前
- 形式: 既存の `<article class="app-card">` と同じ。直前の記事が `.reverse` なら通常、そうでなければ `.reverse` を付けて交互にする
- 画像配置: PDF Page Editor と同じ「横長 1 枚 + 2 枚」（`app-shots-3` / 1 枚目に `wide`）
- 詳細ページ: `/apps/komonjo-daro/`（PC TuneUp の詳細ページと同じ構成）
- フッター: 「文献蔵」「PC TuneUp」の並びに `Komonjo-Daro` を追加
- コピペ用 HTML はこのリポジトリの `docs/site/apps-card.html`（カード・JSON-LD・フッター）と `docs/site/komonjo-daro/index.html`（詳細ページ丸ごと）にある。文言を変える場合は下の原稿が正

## 2. 原稿（一覧ページのカード）

| 項目 | 文言 |
|---|---|
| 分類ラベル（app-label） | 読む・訳す道具 |
| アプリ名（h3） | Komonjo-Daro |
| 説明（app-desc） | くずし字の古典籍を、翻刻して現代語で読む Windows アプリ。版本・写本のページ画像や PDF を読み込む（画面の切り取りを Ctrl+V で貼り付けても可）と、国立国会図書館の NDL古典籍OCR-Lite がパソコンの中だけで文字を起こし、AI（Claude または GPT。設定で選択）が画像と見比べて誤読を直し、現代語訳・語注・要約を付けます。判読できない字は ■、推定は〔 〕で示し、自信のない箇所は「不確実」として別に列挙。左右／上下のレイアウト切替、縦書き表示、過去の資料のサムネイル一覧と全文検索、Markdown 書き出し。 |
| メタ行（app-meta） | Windows 10／11（64bit）・v0.4.1・アプリ本体は無料（MIT）・現代語訳／注釈は利用者自身の API キー（Anthropic または OpenAI）で動作・OCR はオフラインで動作 |
| ボタン1（btn-blue） | ダウンロード（Windows）↓　→ https://github.com/hidetako/Komonjo-Daro/releases/latest/download/Komonjo-Daro-Setup.exe |
| ボタン2（btn-ink） | GitHub ↗　→ https://github.com/hidetako/Komonjo-Daro |
| リンク（intro-card-more） | くわしく見る →　→ /apps/komonjo-daro/ |
| 注意書き（card-notice） | 初回起動時に「Windows によって PC が保護されました」と出た場合は「詳細情報」→「実行」。現代語訳の費用はご本人の API キーに請求されます（OCR のみなら通信も費用も発生しません）。注意事項 → /apps/komonjo-daro/#download |
| 画像キャプション（figcaption） | 翻刻（左右レイアウト）／現代語訳／一覧・検索　※資料画像は国立国会図書館デジタルコレクション『竹取物語』上（dl.ndl.go.jp/pid/1287221/1/2） |

## 3. 画像

すべて https://raw.githubusercontent.com/hidetako/Komonjo-Daro/main/docs/images/ 以下。サイトの `/assets/apps/` にコピーして使っても、raw URL のまま参照してもよい（MD Viewer は raw 参照）。

| ファイル | サイズ | 用途 | alt |
|---|---|---|---|
| komonjo-01-layout-h.png | 3200×2000 | カード 1 枚目（wide）／詳細ページ 1 枚目 | Komonjo-Daro の画面。左に竹取物語の版本ページ、右に校訂済みの翻刻が行ごとに並ぶ |
| komonjo-02-gendaigo.png | 3200×2000 | カード 2 枚目／詳細ページ 2 枚目 | 現代語訳タブ。翁が光る竹を見つける場面の現代語訳 |
| komonjo-04-jobs.png | 3200×2000 | カード 3 枚目 | 一覧・検索画面。読み込んだ資料がサムネイル付きのカードで並び、上に検索欄 |
| komonjo-03-layout-v.png | 3200×2000 | 詳細ページ 3 枚目 | 上下レイアウト。上に古文書、下に OCR からの修正箇所と根拠の表 |
| icon-1024.png | 1024×1024 | アイコン（必要なら。文献蔵と同じ `icon-media` 形式でも可） | Komonjo-Daro のアイコン。深紅の角丸に白い縦線 |

資料画像の出典表記（キャプションに入れる）: 国立国会図書館デジタルコレクション『竹取物語』上、https://dl.ndl.go.jp/pid/1287221/1/2（保護期間満了・インターネット公開）

## 4. 原稿（詳細ページ /apps/komonjo-daro/）

- タイトルタグ: Komonjo-Daro｜くずし字の古典籍を翻刻して現代語で読む Windows アプリ — NDL古典籍OCR-Lite × Claude／GPT・MIT｜よろづソリューションズ
- meta description: Komonjo-Daro は、版本・写本のページ画像からくずし字を翻刻し、現代語訳と注釈を付ける Windows アプリ。OCR は国立国会図書館の NDL古典籍OCR-Lite がパソコンの中だけで実行。校訂・現代語訳は利用者自身の API キーで Claude（Anthropic）または GPT（OpenAI）が行います。本体は無料（MIT）。
- 分類ラベル: 読む・訳す道具　／　h1: Komonjo-Daro
- リード（detail-lead）: くずし字を起こし、／現代語で読む。
- メタ行: Windows 10／11（64bit）・v0.4.1・アプリ本体は無料・オープンソース（MIT）・OCR はオフライン・現代語訳は利用者自身の API キー（Anthropic／OpenAI）で動作
- 注記（detail-note）: インストーラー Komonjo-Daro-Setup.exe は管理者権限なしで入ります。新しい版が出ると起動時に知らせ、「今すぐ更新」で入れ替わります。

本文の各セクション（見出し → 内容）は `docs/site/komonjo-daro/index.html` の通り。要点:

1. **Komonjo-Daro — 古典籍のページを、読める文章に**: 二段構えの説明（OCR はオフライン／校訂・現代語訳は選んだ AI）。レイアウト 2 種、縦書き、拡大。
2. **できること**: 翻刻／校訂（修正は行・OCR・校訂・根拠の表）／現代語訳・注釈・要約／不確実な箇所の明示／手直しして再実行／一覧・検索／Markdown 書き出し
3. **データの置き場所**: 既定「ドキュメント\Komonjo-Daro」。設定で変更、既存データごと移動。ログイン不要。
4. **ダウンロード（無料）**: 最新版 0.4.1。設定で API キー入力。注意事項 3 点（SmartScreen 警告／API 費用は本人負担、1 ページ数円〜数十円／手書き文書は精度が落ちる）
5. **詳細（折りたたみ）**: 仕組み／動作要件／通信について（Anthropic または OpenAI API、GitHub の更新確認のみ。テレメトリなし）／アップデート／出典・ライセンス
6. **よくある質問**: 料金／翻刻の正確さ／手書き文書／画像は外部に送られるか／保存場所
7. **免責**: MIT・無保証。学術引用は原本で確認。

## 5. 構造化データ（JSON-LD）

一覧ページ ItemList への追加分と、詳細ページの SoftwareApplication は `docs/site/apps-card.html` と `docs/site/komonjo-daro/index.html` に記載済み。要素:
name=Komonjo-Daro, operatingSystem=Windows, applicationCategory=EducationalApplication, softwareVersion=0.4.1, license=MIT, offers price 0 JPY, downloadUrl=上記固定リンク, codeRepository=https://github.com/hidetako/Komonjo-Daro

## 6. 運用ルール（版が上がったとき）

- ダウンロードリンクは `releases/latest/download/Komonjo-Daro-Setup.exe` 固定。版が上がっても変更不要
- 変更が必要なのはバージョン表記のみ: カードのメタ行、詳細ページのメタ行、「最新版 x.y.z」、JSON-LD の softwareVersion（2 か所）
- スクリーンショットは同名で `docs/images/` を上書きすれば、raw 参照なら自動で差し替わる

## 7. 確認してほしい点

- 分類ラベル「読む・訳す道具」とリード「くずし字を起こし、現代語で読む。」は仮置き。サイトの語感に合わせて調整可
- アプリ名は英字「Komonjo-Daro」。和名を併記する場合は h3・JSON-LD name・フッターの 3 か所
- スクリーンショットの現代語訳・注釈部分はデモ用に作成した文章（翻刻は実際の OCR 出力）。公開前に実機の画面に差し替える予定
