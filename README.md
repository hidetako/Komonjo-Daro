# Komonjo-Daro (kobun-reader)

古典籍（和古書・版本・写本）の画像を読み込み、

1. **翻刻**: NDL古典籍OCR-Lite（国立国会図書館, CC BY 4.0）でくずし字をテキスト化（ローカル・CPUで動作）
2. **校訂・現代語訳・注釈**: Claude API に画像と翻刻を渡し、構造化JSONで受け取る

という2段構成の自分用ツール。Flask の Web 画面と CLI の両方がある。

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

## セットアップ（Windows, C:\dev）

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
py -3.12 -m venv venv
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
```

## Claude 側の設計

- モデルは既定 `claude-opus-5-5`（`.env` の `KOBUN_MODEL` で変更可）。思考は常時オン、深さは `KOBUN_EFFORT`（既定 high）。
- 出力は JSON スキーマで固定（`kobun/annotate.py` の `OUTPUT_SCHEMA`）。
  `honkoku`（校訂翻刻）/ `corrections`（OCRからの修正と根拠）/ `gendaigo` / `annotations` / `uncertain`（不確実な箇所）/ `summary` / `era_guess`
- 画像を同送すると、OCR誤認識を画像で確認して直してくれる。費用を抑えたいときは画面のチェックを外す。
- 判読できない字は「■」、推定は〔 〕で囲むようシステムプロンプトで指示。不確実なものは `uncertain` に必ず列挙させる。

## 精度についての注意

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
