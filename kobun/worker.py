"""裏で動く処理（PDF のページ OCR、文書単位の一括現代語訳）。進捗はメモリ上に持ち、画面から参照する。"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from .store import Store


@dataclass
class Progress:
    kind: str                 # "ocr" | "annotate"
    group: str
    total: int
    done: int = 0
    current: str = ""
    errors: list[str] = field(default_factory=list)
    finished: bool = False
    started: float = field(default_factory=time.time)


_progress: dict[str, Progress] = {}
_lock = threading.Lock()


def get(group: str) -> Progress | None:
    return _progress.get(group)


def running(group: str) -> bool:
    p = _progress.get(group)
    return bool(p and not p.finished)


def start_ocr(store: Store, job_ids: list[str], group: str, device: str, merge_lines: bool = True) -> None:
    from .ocr_ndl import run_ocr

    def work():
        p = _progress[group]
        for jid in job_ids:
            try:
                job = store.load(jid)
                p.current = job.get("title", jid)
                result = run_ocr(store.source_image(jid, job), device=device, merge_lines=merge_lines)
                job = store.load(jid)
                job["ocr"] = result.to_dict()
                job.pop("error", None)
                store.save(jid, job)
            except Exception as e:  # noqa: BLE001
                p.errors.append(f"{p.current}: {e}")
                try:
                    job = store.load(jid); job["error"] = str(e); store.save(jid, job)
                except Exception:  # noqa: BLE001
                    pass
            p.done += 1
        p.finished = True

    _launch(group, Progress("ocr", group, len(job_ids)), work)


def start_annotate(store: Store, job_ids: list[str], group: str, send_image: bool,
                   use_glossary: bool = True, carry_context: bool = True, cfg: dict | None = None) -> None:
    from .annotate import annotate
    from . import jibo as _jibo

    def work():
        p = _progress[group]
        for jid in job_ids:
            try:
                job = store.load(jid)
                p.current = job.get("title", jid)
                if "ocr" not in job:
                    raise RuntimeError("OCR 未完了")
                text = job.get("edited_honkoku") or job["ocr"]["text"]
                img = store.media_path(jid, "preview.jpg") if send_image else None
                ann = annotate(text, img, context=job.get("context", ""),
                               glossary=store.glossary() if use_glossary else None,
                               prior_pages=store.prior_pages(job) if carry_context else None)
                job = store.load(jid)
                job["annotation"] = ann.to_dict()
                store.save(jid, job)
                if cfg and cfg.get("jibo_pass", True):
                    try:
                        _jibo.apply_to_job(store, jid, cfg)
                    except Exception as e:  # noqa: BLE001
                        p.errors.append(f"{p.current}: 字母判定に失敗（本文は保存済み）: {e}")
            except Exception as e:  # noqa: BLE001
                p.errors.append(f"{p.current}: {e}")
            p.done += 1
        p.finished = True

    _launch(group, Progress("annotate", group, len(job_ids)), work)


def _launch(group: str, progress: Progress, fn) -> None:
    with _lock:
        if running(group):
            raise RuntimeError("この文書は処理中です。終わるまで待ってください。")
        _progress[group] = progress
    threading.Thread(target=fn, daemon=True).start()
