"""処理結果の保存・一覧・検索。

保存先: <data_dir>/jobs/<job_id>/
  original.<ext>  アップロード原本
  preview.jpg     画面表示用（長辺2000px, EXIF回転済み。tif/jp2 でもブラウザで見える）
  thumb.jpg       一覧用サムネイル（長辺320px）
  job.json        OCR結果・校訂結果・タイトル等
"""
from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

PREVIEW_EDGE = 2000
THUMB_EDGE = 320


@dataclass
class JobSummary:
    id: str
    title: str
    created: float
    has_annotation: bool
    summary: str
    group: str = ""
    page: int = 0
    pages_total: int = 0
    has_ocr: bool = True

    @property
    def created_str(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.created))


class Store:
    def __init__(self, data_dir: str | Path):
        self.root = Path(data_dir)
        self.jobs_dir = self.root / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    # --- 個別ジョブ ---
    def job_dir(self, job_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{12}", job_id):
            raise KeyError(job_id)
        return self.jobs_dir / job_id

    def create(self, upload_path: Path, original_name: str, title: str = "", context: str = "") -> str:
        job_id = uuid.uuid4().hex[:12]
        d = self.job_dir(job_id)
        d.mkdir(parents=True)
        ext = Path(original_name).suffix.lower() or ".jpg"
        original = d / f"original{ext}"
        shutil.move(str(upload_path), original)
        make_derivatives(original, d)
        job = {
            "id": job_id,
            "title": title.strip() or Path(original_name).stem,
            "original_name": original_name,
            "original": original.name,
            "context": context,
            "created": time.time(),
        }
        self.save(job_id, job)
        return job_id

    def create_from_image(self, image: Image.Image, title: str, group: str, page: int, pages_total: int,
                          original_name: str, context: str = "") -> str:
        """PDF から展開したページ画像を 1 件として登録する。"""
        job_id = uuid.uuid4().hex[:12]
        d = self.job_dir(job_id)
        d.mkdir(parents=True)
        original = d / "original.jpg"
        image.convert("RGB").save(original, quality=92)
        make_derivatives(original, d)
        job = {
            "id": job_id, "title": title, "original_name": original_name, "original": original.name,
            "context": context, "created": time.time() + page / 1000.0,   # ページ順に並ぶよう微調整
            "group": group, "page": page, "pages_total": pages_total,
        }
        self.save(job_id, job)
        return job_id

    def list_group(self, group: str) -> list[dict]:
        """同じ文書（PDF）から出たページを、ページ順に job 辞書で返す。"""
        out = []
        for p in self.jobs_dir.glob("*/job.json"):
            try:
                job = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if job.get("group") == group:
                out.append(job)
        out.sort(key=lambda j: j.get("page", 0))
        return out

    def load(self, job_id: str) -> dict:
        p = self.job_dir(job_id) / "job.json"
        if not p.exists():
            raise KeyError(job_id)
        return json.loads(p.read_text(encoding="utf-8"))

    def save(self, job_id: str, job: dict) -> None:
        (self.job_dir(job_id) / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")

    def delete(self, job_id: str) -> None:
        shutil.rmtree(self.job_dir(job_id), ignore_errors=True)

    def media_path(self, job_id: str, name: str) -> Path:
        if name not in ("preview.jpg", "thumb.jpg") and not name.startswith("original."):
            raise KeyError(name)
        return self.job_dir(job_id) / name

    # --- 一覧・検索 ---
    def list(self, query: str = "", only_annotated: bool = False) -> list[JobSummary]:
        q = query.strip().lower()
        out: list[JobSummary] = []
        for p in self.jobs_dir.glob("*/job.json"):
            try:
                job = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            ann = job.get("annotation") or {}
            if only_annotated and not ann:
                continue
            if q and not _matches(job, q):
                continue
            out.append(JobSummary(
                id=job["id"], title=job.get("title") or job.get("original_name", ""),
                created=float(job.get("created", p.stat().st_mtime)),
                has_annotation=bool(ann), summary=ann.get("summary", ""),
                group=job.get("group", ""), page=int(job.get("page", 0)), pages_total=int(job.get("pages_total", 0)),
                has_ocr="ocr" in job,
            ))
        out.sort(key=lambda j: j.created, reverse=True)
        return out

    def move_to(self, new_dir: str | Path) -> int:
        """保存先を変更し、既存ジョブを移動する。移動した件数を返す。"""
        new_root = Path(new_dir)
        new_jobs = new_root / "jobs"
        new_jobs.mkdir(parents=True, exist_ok=True)
        if new_jobs.resolve() == self.jobs_dir.resolve():
            return 0
        n = 0
        for d in self.jobs_dir.iterdir():
            if d.is_dir() and not (new_jobs / d.name).exists():
                shutil.move(str(d), new_jobs / d.name)
                n += 1
        self.root, self.jobs_dir = new_root, new_jobs
        return n


def _matches(job: dict, q: str) -> bool:
    ann = job.get("annotation") or {}
    hay = " ".join([
        job.get("title", ""), job.get("original_name", ""), job.get("context", ""),
        (job.get("ocr") or {}).get("text", ""), job.get("edited_honkoku", ""),
        ann.get("honkoku", ""), ann.get("gendaigo", ""), ann.get("summary", ""),
        " ".join(a.get("term", "") + " " + a.get("note", "") for a in ann.get("annotations", [])),
    ]).lower()
    return all(term in hay for term in q.split())


def make_derivatives(original: Path, d: Path) -> None:
    with Image.open(original) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        pv = im.copy(); pv.thumbnail((PREVIEW_EDGE, PREVIEW_EDGE)); pv.save(d / "preview.jpg", quality=88)
        th = im.copy(); th.thumbnail((THUMB_EDGE, THUMB_EDGE)); th.save(d / "thumb.jpg", quality=80)
