"""Komonjo-Daro Web アプリ（自分用・ローカル）。

開発時:  python app.py        （http://127.0.0.1:5000）
配布版:  desktop.py から起動（空きポート・ブラウザ自動起動・トレイアイコン）
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, send_file, url_for

from kobun import __version__
from kobun import config as config_mod
from kobun import jibo as jibo_mod
from kobun import llm, pdf, worker
from kobun.ocr_ndl import NdlLiteNotFound, looks_unreliable, run_ocr
from kobun.store import Store
from kobun.updater import UpdateState, exit_app

load_dotenv()

app = Flask(__name__, template_folder=str(config_mod.ROOT / "templates"))  # 固めた版でも templates を確実に見つける
app.config["MAX_CONTENT_LENGTH"] = 80 * 1024 * 1024
app.secret_key = os.environ.get("KOBUN_SECRET", "komonjo-daro-local")
updates = UpdateState()


def cfg() -> dict:
    return config_mod.load()


def store() -> Store:
    return Store(cfg()["data_dir"])


@app.context_processor
def inject_globals():
    return {"version": __version__, "updates": updates, "is_frozen": config_mod.IS_FROZEN}


@app.get("/favicon.png")
def favicon():
    return send_file(str(config_mod.ROOT / "packaging" / "icon.png"), max_age=86400)


@app.get("/ping")
def ping():
    """多重起動チェック用。"""
    return f"komonjo-daro {__version__}", 200, {"Content-Type": "text/plain; charset=utf-8"}


# ---------- 読み込み ----------
@app.get("/")
def index():
    recent = store().list()[:8]
    c = cfg()
    prov, model, key = config_mod.active(c)
    return render_template("index.html", recent=recent, device=c["device"], has_key=bool(key),
                           provider_label=llm.PROVIDERS[prov]["label"], model=model)


@app.post("/ocr")
def ocr():
    file = request.files.get("image")
    if not file or not file.filename:
        return redirect(url_for("index"))
    c = cfg()
    tmp = Path(tempfile.gettempdir()) / f"komonjo_{uuid.uuid4().hex}{Path(file.filename).suffix.lower() or '.jpg'}"
    file.save(tmp)
    st = store()
    if tmp.suffix == ".pdf":
        return ocr_pdf(tmp, file.filename, st, c)
    direct = request.form.get("direct") == "on"
    try:
        job_id = st.create(tmp, file.filename, title=request.form.get("title", ""), context=request.form.get("context", ""))
        job = st.load(job_id)
        if direct:
            # 書作品・散らし書き: OCR を飛ばして AI に画像から直接翻刻させる
            job["ocr"] = {"text": "", "lines": [], "width": 0, "height": 0, "viz_path": None}
            job["from_image"] = True
            st.save(job_id, job)
            return redirect(url_for("annotate_job_direct", job_id=job_id))
        result = run_ocr(st.media_path(job_id, job["original"]), device=c["device"], merge_lines=c.get("merge_lines", False))
    except NdlLiteNotFound as e:
        return render_template("error.html", message=str(e)), 500
    except Exception as e:  # noqa: BLE001
        return render_template("error.html", message=f"OCRに失敗しました: {e}"), 500
    finally:
        tmp.unlink(missing_ok=True)
    job["ocr"] = result.to_dict()
    st.save(job_id, job)
    return redirect(url_for("review", job_id=job_id))


def ocr_pdf(tmp: Path, filename: str, st: Store, c: dict):
    """PDF をページ画像に展開して 1 ページ 1 件で登録し、OCR を裏で順に走らせる。"""
    title = request.form.get("title", "").strip() or Path(filename).stem
    context = request.form.get("context", "")
    try:
        total = pdf.page_count(tmp)
        pages = pdf.parse_page_range(request.form.get("pages", ""), total)
        if len(pages) > pdf.MAX_PAGES:
            raise ValueError(f"一度に扱えるのは {pdf.MAX_PAGES} ページまでです（{len(pages)} ページ指定）")
        group = uuid.uuid4().hex[:12]
        job_ids = []
        for p, im in pdf.render_pages(tmp, pages):
            job_ids.append(st.create_from_image(im, f"{title} p.{p}", group, p, total, filename, context))
    except Exception as e:  # noqa: BLE001
        return render_template("error.html", message=f"PDF を読み込めませんでした: {e}"), 500
    finally:
        tmp.unlink(missing_ok=True)
    try:
        worker.start_ocr(st, job_ids, group, c["device"], merge_lines=c.get("merge_lines", True))
    except Exception as e:  # noqa: BLE001
        return render_template("error.html", message=str(e)), 500
    return redirect(url_for("doc", group=group))


# ---------- 文書（PDF の全ページ） ----------
@app.get("/doc/<group>")
def doc(group):
    pages = store().list_group(group)
    if not pages:
        abort(404)
    prog = worker.get(group)
    title = pages[0]["title"].rsplit(" p.", 1)[0]
    return render_template("doc.html", group=group, pages=pages, prog=prog, title=title,
                           running=worker.running(group), send_image=cfg()["send_image"],
                           has_key=bool(config_mod.active(cfg())[2]))


@app.post("/doc/<group>/annotate")
def doc_annotate(group):
    st = store()
    pages = [j for j in st.list_group(group) if "ocr" in j and (request.form.get("redo") == "on" or "annotation" not in j)]
    if not pages:
        flash("現代語訳の対象ページがありません（OCR 未完了、または全ページ訳済み）")
        return redirect(url_for("doc", group=group))
    try:
        c = cfg()
        worker.start_annotate(st, [j["id"] for j in pages], group, request.form.get("use_image") == "on",
                              use_glossary=c["use_glossary"], carry_context=c["carry_context"], cfg=c)
    except RuntimeError as e:
        flash(str(e))
    return redirect(url_for("doc", group=group))


@app.post("/doc/<group>/retry_ocr")
def doc_retry_ocr(group):
    st = store()
    pages = [j["id"] for j in st.list_group(group) if "ocr" not in j]
    if pages:
        try:
            worker.start_ocr(st, pages, group, cfg()["device"], merge_lines=cfg().get("merge_lines", True))
        except RuntimeError as e:
            flash(str(e))
    return redirect(url_for("doc", group=group))


@app.post("/doc/<group>/delete")
def doc_delete(group):
    st = store()
    if worker.running(group):
        flash("処理中は削除できません")
        return redirect(url_for("doc", group=group))
    for j in st.list_group(group):
        st.delete(j["id"])
    flash("文書を削除しました")
    return redirect(url_for("jobs"))


@app.get("/doc/<group>/markdown")
def doc_markdown(group):
    from kobun.annotate import Annotation

    pages = store().list_group(group)
    if not pages:
        abort(404)
    title = pages[0]["title"].rsplit(" p.", 1)[0]
    out = [f"# {title}", ""]
    for j in pages:
        out.append(f"## p.{j.get('page')}")
        out.append("")
        if j.get("annotation"):
            out.append(Annotation(**j["annotation"]).to_markdown().replace("\n## ", "\n### "))
        elif j.get("ocr"):
            out += ["### 翻刻（OCR生）", "", j["ocr"]["text"], ""]
        else:
            out += ["（OCR 未完了）", ""]
    return "\n".join(out), 200, {"Content-Type": "text/markdown; charset=utf-8"}


# ---------- 一覧・検索 ----------
@app.get("/jobs")
def jobs():
    q = request.args.get("q", "")
    only = request.args.get("only") == "ann"
    return render_template("jobs.html", jobs=store().list(q, only), q=q, only=only)


# ---------- 個別ページ ----------
@app.get("/job/<job_id>")
def review(job_id):
    try:
        job = store().load(job_id)
    except KeyError:
        abort(404)
    prev_id = next_id = None
    if job.get("group"):
        pages = store().list_group(job["group"])
        ids = [j["id"] for j in pages]
        i = ids.index(job_id) if job_id in ids else -1
        if i > 0:
            prev_id = ids[i - 1]
        if 0 <= i < len(ids) - 1:
            next_id = ids[i + 1]
    unreliable = looks_unreliable((job.get("ocr") or {}).get("text", "")) if job.get("ocr") else False
    return render_template("review.html", job_id=job_id, job=job, send_image=cfg()["send_image"], prev_id=prev_id, next_id=next_id,
                           unreliable=unreliable)


@app.post("/job/<job_id>/reocr")
def reocr_job(job_id):
    """同じ画像で OCR をやり直す（行結合などの設定を変えたあと用）。現代語訳は残す。"""
    st = store()
    try:
        job = st.load(job_id)
    except KeyError:
        abort(404)
    c = cfg()
    try:
        result = run_ocr(st.media_path(job_id, job["original"]), device=c["device"], merge_lines=c.get("merge_lines", True))
    except Exception as e:  # noqa: BLE001
        return render_template("error.html", message=f"OCRに失敗しました: {e}"), 500
    job["ocr"] = result.to_dict()
    job.pop("edited_honkoku", None)
    st.save(job_id, job)
    flash(f"OCR をやり直しました（{len(result.lines)} 行）")
    return redirect(url_for("review", job_id=job_id))


@app.post("/job/<job_id>/title")
def set_title(job_id):
    st = store()
    job = st.load(job_id)
    job["title"] = request.form.get("title", "").strip() or job["title"]
    st.save(job_id, job)
    return redirect(url_for("review", job_id=job_id))


@app.post("/job/<job_id>/delete")
def delete_job(job_id):
    store().delete(job_id)
    flash("削除しました")
    return redirect(url_for("jobs"))


@app.post("/job/<job_id>/annotate")
def annotate_job(job_id):
    from kobun.annotate import annotate

    st = store()
    job = st.load(job_id)
    from_image = request.form.get("from_image") == "on"
    text = "" if from_image else request.form.get("honkoku", (job.get("ocr") or {}).get("text", ""))
    if not text.strip() and not from_image:
        return render_template("error.html", message="翻刻テキストが空です（OCR 未完了）。「画像だけで翻刻」を使うこともできます。"), 400
    context = request.form.get("context", job.get("context", ""))
    use_image = request.form.get("use_image") == "on" or from_image
    img = st.media_path(job_id, "preview.jpg") if use_image else None
    c = cfg()
    try:
        ann = annotate(text, img, context=context,
                       glossary=st.glossary() if c["use_glossary"] else None,
                       prior_pages=st.prior_pages(job) if c["carry_context"] else None)
    except Exception as e:  # noqa: BLE001
        return render_template("error.html", message=f"Claude API 呼び出しに失敗しました: {e}"), 500
    job["edited_honkoku"] = text
    job["context"] = context
    job["from_image"] = from_image
    job["annotation"] = ann.to_dict()
    st.save(job_id, job)
    if c.get("jibo_pass", True) and not from_image:
        try:
            jibo_mod.apply_to_job(st, job_id, c)
        except Exception as e:  # noqa: BLE001
            flash(f"本文は保存しましたが、字母の判定に失敗しました: {e}")
    return redirect(url_for("review", job_id=job_id))


@app.post("/job/<job_id>/jibo")
def jibo_job(job_id):
    """字母の第2パス（行切り出し）だけを実行し直す。"""
    st = store()
    try:
        job = st.load(job_id)
    except KeyError:
        abort(404)
    if not job.get("annotation"):
        flash("先に現代語訳を作成してください")
        return redirect(url_for("review", job_id=job_id))
    try:
        jibo_mod.apply_to_job(st, job_id, cfg())
    except Exception as e:  # noqa: BLE001
        return render_template("error.html", message=f"字母の判定に失敗しました: {e}"), 500
    return redirect(url_for("review", job_id=job_id))


@app.get("/job/<job_id>/direct")
def annotate_job_direct(job_id):
    """アップロード直後の直読み実行。処理中表示のあとフォームを自動送信する。"""
    try:
        job = store().load(job_id)
    except KeyError:
        abort(404)
    return render_template("direct.html", job_id=job_id, job=job)


@app.get("/job/<job_id>/markdown")
def markdown(job_id):
    from kobun.annotate import Annotation

    job = store().load(job_id)
    if "annotation" not in job:
        abort(404)
    md = f"# {job['title']}\n\n" + Annotation(**job["annotation"]).to_markdown()
    return md, 200, {"Content-Type": "text/markdown; charset=utf-8"}


@app.get("/media/<job_id>/<name>")
def media(job_id, name):
    try:
        p = store().media_path(job_id, name)
    except KeyError:
        abort(404)
    if not p.exists():
        abort(404)
    return send_file(str(p), max_age=3600)


# ---------- 用語集 ----------
@app.get("/glossary")
def glossary():
    return render_template("glossary.html", entries=store().glossary(), c=cfg())


@app.post("/glossary/add")
def glossary_add():
    st = store()
    added = st.glossary_add(request.form.get("term", ""), request.form.get("reading", ""), request.form.get("note", ""))
    flash("追加しました" if added else "同じ表記があったので更新しました（または表記が空）")
    nxt = request.form.get("next") or url_for("glossary")
    return redirect(nxt)


@app.post("/glossary/<entry_id>/delete")
def glossary_delete(entry_id):
    store().glossary_delete(entry_id)
    return redirect(url_for("glossary"))


@app.post("/glossary/import")
def glossary_import():
    """1行1項目「表記,読み,注」または「表記（読み）: 注」のテキストをまとめて登録。"""
    st = store()
    n = 0
    for line in request.form.get("bulk", "").splitlines():
        line = line.strip().replace("，", ",")
        if not line:
            continue
        if "," in line:
            parts = [x.strip() for x in line.split(",", 2)] + ["", ""]
            term, reading, note = parts[0], parts[1], parts[2]
        else:
            import re
            m = re.match(r"^(.+?)(?:[（(](.+?)[）)])?\s*(?:[:：]\s*(.*))?$", line)
            term, reading, note = (m.group(1), m.group(2) or "", m.group(3) or "") if m else (line, "", "")
        n += int(st.glossary_add(term, reading, note))
    flash(f"{n} 件を追加しました")
    return redirect(url_for("glossary"))


# ---------- 設定 ----------
@app.get("/settings")
def settings():
    c = cfg()
    return render_template("settings.html", c=c, masked=config_mod.mask_key(c["api_key"]),
                           masked_openai=config_mod.mask_key(c["openai_api_key"]),
                           curated=llm.CURATED, providers=llm.PROVIDERS, config_path=str(config_mod.config_path()))


@app.post("/settings")
def settings_save():
    c = cfg()
    old_dir = c["data_dir"]
    c["provider"] = request.form.get("provider", c["provider"])
    if c["provider"] not in llm.PROVIDERS:
        c["provider"] = "anthropic"
    for form_key, cfg_key, clear in (("api_key", "api_key", "clear_key"), ("openai_api_key", "openai_api_key", "clear_openai_key")):
        v = request.form.get(form_key, "").strip()
        if v:
            c[cfg_key] = v
        if request.form.get(clear) == "on":
            c[cfg_key] = ""
    c["model"] = (request.form.get("model_custom", "").strip() or request.form.get("model", "").strip() or c["model"])
    c["openai_model"] = (request.form.get("openai_model_custom", "").strip() or request.form.get("openai_model", "").strip() or c["openai_model"])
    c["effort"] = request.form.get("effort", c["effort"])
    c["device"] = request.form.get("device", c["device"])
    c["send_image"] = request.form.get("send_image") == "on"
    c["use_glossary"] = request.form.get("use_glossary") == "on"
    c["carry_context"] = request.form.get("carry_context") == "on"
    c["jibo_pass"] = request.form.get("jibo_pass") == "on"
    c["merge_lines"] = request.form.get("merge_lines") == "on"
    c["auto_check_updates"] = request.form.get("auto_check_updates") == "on"
    new_dir = request.form.get("data_dir", "").strip() or old_dir
    moved = 0
    if Path(new_dir) != Path(old_dir):
        try:
            Path(new_dir).mkdir(parents=True, exist_ok=True)
            if request.form.get("move_data") == "on":
                moved = Store(old_dir).move_to(new_dir)
        except OSError as e:
            flash(f"保存先を変更できません: {e}")
            return redirect(url_for("settings"))
    c["data_dir"] = new_dir
    config_mod.save(c)
    flash("保存しました" + (f"（{moved} 件を移動）" if moved else ""))
    return redirect(url_for("settings"))


@app.post("/settings/browse")
def browse_folder():
    """OS のフォルダ選択ダイアログを開き、選ばれたパスを返す（ローカル実行前提）。"""
    start = request.form.get("start", "") or cfg()["data_dir"]
    path = pick_folder(start)
    return jsonify({"path": path})


def pick_folder(start: str) -> str:
    if sys.platform == "win32":
        ps = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
            "$d.Description = '保存フォルダを選んでください';"
            f"$d.SelectedPath = '{start.replace(chr(39), chr(39) * 2)}';"
            "$d.ShowNewFolderButton = $true;"
            "if ($d.ShowDialog() -eq 'OK') { [Console]::Out.Write($d.SelectedPath) }"
        )
        r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps], capture_output=True, text=True, encoding="utf-8", errors="replace")
        return r.stdout.strip()
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
        p = filedialog.askdirectory(initialdir=start) or ""
        root.destroy()
        return p
    except Exception:  # noqa: BLE001
        return ""


def _key_for(provider: str, entered: str) -> str:
    c = cfg()
    saved = c["openai_api_key"] if provider == "openai" else c["api_key"]
    return entered.strip() or saved


@app.post("/settings/test_key")
def test_key():
    """入力中（または保存済み）のキーで軽い呼び出しをして有効性を確認する。"""
    provider = request.form.get("provider", "anthropic")
    if provider not in llm.PROVIDERS:
        return jsonify({"ok": False, "message": "不明なプロバイダ"})
    key = _key_for(provider, request.form.get("api_key", ""))
    if not key:
        return jsonify({"ok": False, "message": "キーが未入力です"})
    ok, msg = llm.test_key(provider, key)
    return jsonify({"ok": ok, "message": msg})


@app.post("/settings/models")
def models_list():
    """各社 API からモデル一覧を取得する。"""
    provider = request.form.get("provider", "anthropic")
    if provider not in llm.PROVIDERS:
        return jsonify({"ok": False, "message": "不明なプロバイダ", "models": []})
    key = _key_for(provider, request.form.get("api_key", ""))
    if not key:
        return jsonify({"ok": False, "message": "キーが未入力です", "models": []})
    try:
        return jsonify({"ok": True, "models": llm.list_models(provider, key)})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "message": f"取得できませんでした: {e}", "models": []})


# ---------- 更新 ----------
@app.post("/update/check")
def update_check():
    updates.check()
    return redirect(url_for("settings"))


@app.post("/update/apply")
def update_apply():
    try:
        updates.start_update()
    except Exception as e:  # noqa: BLE001
        flash(str(e))
        return redirect(url_for("settings"))
    return redirect(url_for("update_progress"))


@app.get("/update/progress")
def update_progress():
    return render_template("update.html", p=updates.progress())


@app.get("/update/status")
def update_status():
    return jsonify(updates.progress())


@app.post("/quit")
def quit_app():
    exit_app(0.5)
    return render_template("message.html", title="終了", message="Komonjo-Daro を終了しました。このタブは閉じて構いません。")


def create_app():
    if cfg().get("auto_check_updates", True) and config_mod.IS_FROZEN:
        updates.check_async()
    return app


if __name__ == "__main__":
    create_app().run(host=os.environ.get("KOBUN_HOST", "127.0.0.1"), port=int(os.environ.get("KOBUN_PORT", "5000")), debug=False)
