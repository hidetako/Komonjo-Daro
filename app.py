"""自分用 Flask アプリ: 画像アップロード → OCR → 翻刻を手で直す → Claude で現代語訳・注釈。

起動:  python app.py        （http://127.0.0.1:5000）
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, abort, redirect, render_template, request, send_from_directory, url_for

from kobun.ocr_ndl import NdlLiteNotFound, run_ocr

load_dotenv()

ROOT = Path(__file__).resolve().parent
UPLOADS = ROOT / "data" / "uploads"
RESULTS = ROOT / "data" / "results"
UPLOADS.mkdir(parents=True, exist_ok=True)
RESULTS.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
DEVICE = os.environ.get("KOBUN_DEVICE", "cpu")


def load_job(job_id: str) -> dict:
    f = RESULTS / f"{job_id}.json"
    if not f.exists():
        abort(404)
    return json.loads(f.read_text(encoding="utf-8"))


def save_job(job_id: str, data: dict) -> None:
    (RESULTS / f"{job_id}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@app.get("/")
def index():
    jobs = []
    for f in sorted(RESULTS.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:30]:
        d = json.loads(f.read_text(encoding="utf-8"))
        jobs.append({"id": f.stem, "name": d.get("original_name", ""), "done": "annotation" in d})
    return render_template("index.html", jobs=jobs, device=DEVICE)


@app.post("/ocr")
def ocr():
    file = request.files.get("image")
    if not file or not file.filename:
        return redirect(url_for("index"))
    ext = Path(file.filename).suffix.lower() or ".jpg"
    job_id = uuid.uuid4().hex[:12]
    img_path = UPLOADS / f"{job_id}{ext}"
    file.save(img_path)
    try:
        result = run_ocr(img_path, device=DEVICE)
    except NdlLiteNotFound as e:
        return render_template("error.html", message=str(e)), 500
    except Exception as e:  # noqa: BLE001
        return render_template("error.html", message=f"OCRに失敗しました: {e}"), 500
    save_job(job_id, {
        "original_name": file.filename,
        "image": img_path.name,
        "context": request.form.get("context", ""),
        "ocr": result.to_dict(),
    })
    return redirect(url_for("review", job_id=job_id))


@app.get("/job/<job_id>")
def review(job_id):
    job = load_job(job_id)
    return render_template("review.html", job_id=job_id, job=job)


@app.post("/job/<job_id>/annotate")
def annotate_job(job_id):
    from kobun.annotate import annotate

    job = load_job(job_id)
    text = request.form.get("honkoku", job["ocr"]["text"])
    context = request.form.get("context", job.get("context", ""))
    use_image = request.form.get("use_image") == "on"
    img = UPLOADS / job["image"] if use_image else None
    try:
        ann = annotate(text, img, context=context)
    except Exception as e:  # noqa: BLE001
        return render_template("error.html", message=f"Claude API 呼び出しに失敗しました: {e}"), 500
    job["edited_honkoku"] = text
    job["context"] = context
    job["annotation"] = ann.to_dict()
    save_job(job_id, job)
    return redirect(url_for("review", job_id=job_id))


@app.get("/job/<job_id>/markdown")
def markdown(job_id):
    from kobun.annotate import Annotation

    job = load_job(job_id)
    if "annotation" not in job:
        abort(404)
    md = Annotation(**job["annotation"]).to_markdown()
    return md, 200, {"Content-Type": "text/markdown; charset=utf-8"}


@app.get("/uploads/<name>")
def uploads(name):
    return send_from_directory(UPLOADS, name)


if __name__ == "__main__":
    app.run(host=os.environ.get("KOBUN_HOST", "127.0.0.1"), port=int(os.environ.get("KOBUN_PORT", "5000")), debug=False)
