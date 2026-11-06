# Komonjo-Daro (kobun-reader)

古典籍（和古書・版本・写本）の画像を読み込み、

1. **翻刻**: NDL古典籍OCR-Lite（国立国会図書館, CC BY 4.0）でくずし字をテキスト化（ローカル・CPUで動作）
2. **校訂・現代語訳・注釈**: Claude（Anthropic）または GPT（OpenAI）に画像と翻刻を渡し、構造化JSONで受け取る。設定画面でプロバイダとモデルを選択

という2段構成の自分用ツール。Windows 用インストーラー（自動アップデート付き）、開発用の Flask 起動、CLI の3通りで使える。

```
画像 ──▶ NDL古典籍OCR-Lite ──▶ 翻刻（手で修正可）──▶ Claude ──▶ 校訂翻刻 / 現代語訳 / 注釈 / 不確実箇所
          ローカル (ONNX, CPU/GPU)                        API（画像も一緒に送って誤認識を直させる）
```

## 構成

```
Komonjo-Daro/
├─ app.py                 Flask アプリ（アップロード → OCR → 確認・修正 → 現代語訳）
├─ kobun/
│   ├─ ocr_ndl.py         NDL-Lite を subprocess で呼ぶラッパー（.txt/.json を解釈）
│   ├─ annotate.py        Claude API 呼び出し（JSONスキーマ固定・画像同送）
│   └─ pipeline.py        CLI: python -m kobun.pipeline 画像.jpg
├─ templates/             画面
├─ tests/                 単体テスト（API・OCR本体なしで動く）
├─ vendor/ndlkotenocr-lite/   ← 自分で clone する（.gitignore 済み）
├─ data/{uploads,results,tmp} 実行時データ（.gitignore 済み）
├─ Dockerfile / docker-compose.yml
└─ requirements.txt / .env.example
```

## インストーラー版（Windows）

1. [Releases](https://github.com/hidetako/Komonjo-Daro/releases/latest) から `Komonjo-Daro-Setup.exe` をダウンロードして実行（管理者権限不要）。
   HP に貼る固定リンク: `https://github.com/hidetako/Komonjo-Daro/releases/latest/download/Komonjo-Daro-Setup.exe`
2. 起動すると Edge/Chrome のアプリウィンドウが開く。タスクトレイのアイコンから「開く」「終了」。
3. 右上「設定」で使う AI（Anthropic / OpenAI）を選び、API キーを入力（「キーを確認」で有効性チェック、「一覧を取得」で各社の現行モデルから選択）。保存フォルダもここで変更できる。
4. 新しいバージョンが出ると起動時に通知。「今すぐ更新」でダウンロードとサイレントインストールが走り、自動で再起動する。

設定は `%APPDATA%\Komonjo-Daro\config.json`、データは既定で `ドキュメント\Komonjo-Daro\jobs\<ID>\` に保存。

### リリース手順（開発者）

```bash
# kobun/__init__.py の __version__ を上げてコミットしてから
git tag v0.8.4
git push origin v0.8.4
```
GitHub Actions（`.github/workflows/release.yml`）が Windows でビルドし、Release に `Komonjo-Daro-Setup.exe` を添付する。
タグとソースのバージョンが違うとビルドは失敗する。ローカルで作るなら `packaging\build.ps1`（Inno Setup 6 が必要）。

## 開発版セットアップ（Windows, C:\dev）

PowerShell で1行ずつ実行。

```powershell
cd C:\dev
```
```powershell
git clone https://github.com/hidetako/Komonjo-Daro C:\dev\Komonjo-Daro
```
```powershell
cd C:\dev\Komonjo-Daro
```
```powershell
git clone https://github.com/ndl-lab/ndlkotenocr-lite vendor\ndlkotenocr-lite
```
```powershell
py -3 -m venv venv
```
```powershell
.\venv\Scripts\Activate.ps1
```
```powershell
pip install -r requirements.txt
```
```powershell
Copy-Item .env.example .env
```
`.env` をメモ帳で開き `ANTHROPIC_API_KEY` を入れる。

```powershell
python app.py
```
ブラウザで http://127.0.0.1:5000 を開く。

> パスに全角文字が含まれると NDL-Lite が起動しないことがある。`C:\dev\Komonjo-Daro` に置く。
> 一時ファイルもプロジェクト内 `data\tmp` に作るので、Windows のユーザー名が日本語でも動く。

### GPU（GTX 1650 4GB）で OCR を速くする場合（任意）

CPU でも1ページ数秒〜数十秒で動くので必須ではない。速くしたい場合のみ:

```powershell
pip uninstall -y onnxruntime
```
```powershell
pip install onnxruntime-gpu
```
`.env` の `KOBUN_DEVICE=cuda` にする。CUDA 12 系ランタイムと cuDNN が必要（GTX 1650 = Turing, compute 7.5 で対応範囲内）。
4GB でも NDL-Lite のモデル（約80MB）は余裕で載る。

## セットアップ（Ubuntu / Docker）

```bash
git clone https://github.com/hidetako/Komonjo-Daro && cd Komonjo-Daro
```
```bash
cp .env.example .env   # APIキーを記入
```
```bash
docker compose up --build
```
Dockerfile 内で NDL-Lite を clone するので vendor の手動取得は不要。http://127.0.0.1:5000

## Web 画面の使い方

- **読み込む**: 画像または PDF をドラッグ＆ドロップ、ファイル選択、または Ctrl+V の貼り付け（PrintScreen / Win+Shift+S で切り取った画面をそのまま）でOCR。PDF は 1 ページ 1 件として登録され、OCR は裏で順に実行（ページ範囲 `1-5, 8, 12-` の指定可）。文書ページで進み具合を見ながら、未訳ページの一括現代語訳と全ページの Markdown 取得ができる。
- **一覧・検索**: 過去の資料をサムネイル付きで一覧。タイトル・翻刻・現代語訳・注釈を横断検索（空白区切りでAND）。
- **用語集**: 表記・読み・注を登録すると毎回 AI に渡され、人名・地名の表記が揃う。注釈タブから「用語集に追加」も可。同じ文書（PDF）の前ページの翻刻・注釈語も自動で参考に渡す（設定で切替）。
- **設定**: APIキー、モデル、思考の深さ、保存フォルダ（「参照…」でフォルダ選択）、OCRデバイス、更新確認。

- **レイアウト切替**（右上）: 「左右」= 左に古文書・右に読み取りと解説、「上下」= 上に古文書・下に読み取りと解説。選択はブラウザに記憶される。
- **拡大**: スライダー、または画像の上で Ctrl+ホイール。「原寸で開く」で別タブに原画像。
- **タブ**: 翻刻 / 現代語訳 / 注釈 / 修正・不確実（OCRからの修正と根拠、判読が怪しい箇所）/ 要約 / 再実行。
- **再実行**: OCR テキストを手で直してから Claude に送り直せる。画像同送のチェックを外すと費用が下がる。
- **縦書き**: 翻刻タブのボタンで縦書き表示に切替。
- **Markdown**: 右上のボタンで校訂翻刻・現代語訳・注釈をまとめて取得（Evernote 等に貼る用）。

## CLI

```bash
python -m kobun.pipeline 画像.jpg                   # OCR → Claude、data/results/ に .json と .md
python -m kobun.pipeline 画像.jpg --no-llm          # OCR だけ（APIキー不要、動作確認用）
python -m kobun.pipeline 画像.jpg --no-image        # Claude に画像を送らない（通信量・費用節約）
python -m kobun.pipeline 画像.jpg --context "竹取物語 上 江戸前期刊"
python -m kobun.pipeline 資料.pdf --pages 1-5 --no-llm       # PDF はページごとに処理
```

## AI 側の設計

- プロバイダは Anthropic（既定 `claude-opus-5-5`）と OpenAI（既定 `gpt-6.1-sol`）。`kobun/llm.py` が両者を同じ呼び出しに揃える。思考の深さは共通の low〜max で、OpenAI は各モデルが受け付ける範囲（GPT-6 系は max まで、GPT-5.5 系は xhigh まで）に丸める。
- モデル一覧は設定画面の「一覧を取得」で各社 API から取る。候補リスト（`CURATED`）は取得できないときの既定。
- 出力は JSON スキーマで固定（`kobun/annotate.py` の `OUTPUT_SCHEMA`）。
  `honkoku`（校訂翻刻）/ `corrections`（OCRからの修正と根拠）/ `gendaigo` / `annotations` / `uncertain`（不確実な箇所）/ `summary` / `era_guess`
- 画像を同送すると、OCR誤認識を画像で確認して直してくれる。費用を抑えたいときは画面のチェックを外す。OpenAI は Responses API の構造化出力（strict）、Anthropic は output_config の JSON スキーマで、同じスキーマを使う。
- 判読できない字は「■」、推定は〔 〕で囲むようシステムプロンプトで指示。不確実なものは `uncertain` に必ず列挙させる。
- **字母（変体仮名のもとの漢字）は第2パス**（`kobun/jibo.py`）。NDL-Lite の行座標で原寸画像から行を切り出し、数行ずつ候補表つきで AI に判定させる。全体画像では字形が潰れて誤りが増えるため。設定で自動実行を切替、字母タブから手動実行も可。

## 精度についての注意

- **横長・縦長の画像（巻子、横に広い写真）** は自動で区画に分けて行検出し、結果を結合する（NDL-Lite の検出器は 1280px 四方に縮めるため、そのままだと行が切れ切れになる）。長辺/短辺 > 1.6 で発動。
- **散らし書き・書作品・写真** は OCR の学習範囲外で、行数が合わない・読めない文字列になることがある。その場合は「再実行」タブの「OCR の結果を使わず、画像だけから翻刻する」で AI に直接読ませる。

NDL-Lite の学習データは主に版本・整った写本。**手書きの書状・証文（近世文書）は精度が大きく落ちる。**
その領域に進むなら、`vendor/ndlkotenocr-lite/train/README.md` の手順で自前データを追加学習する（GTX 1650 4GB では学習は厳しく、Colab 等が現実的）。

## テスト

```bash
python -m pytest -q tests
```
API キーも NDL-Lite 本体もなしで通る（ラッパーの解釈部分とプロンプト組み立てのみ検証）。

## ライセンス・出典

- NDL古典籍OCR-Lite: 国立国会図書館, CC BY 4.0 — https://github.com/ndl-lab/ndlkotenocr-lite
- 本リポジトリのコード: MIT
