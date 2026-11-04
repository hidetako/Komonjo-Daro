# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 用スペック。リポジトリ直下で:  pyinstaller packaging/komonjo.spec
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

ROOT = Path(SPECPATH).resolve().parent
NDL = ROOT / "vendor" / "ndlkotenocr-lite" / "src"
assert (NDL / "ocr.py").exists(), "vendor/ndlkotenocr-lite を clone してください"

datas = [
    (str(ROOT / "templates"), "templates"),
    (str(ROOT / "packaging" / "icon.png"), "packaging"),
    (str(NDL), "ndlkotenocr-lite/src"),        # モデル(.onnx)・config(.yaml)・NDL のソース一式
]
datas += collect_data_files("onnxruntime")
datas += collect_data_files("reportlab")
datas += collect_data_files("pypdfium2")

hiddenimports = (
    collect_submodules("onnxruntime") + collect_submodules("networkx") + collect_submodules("lxml")
    + collect_submodules("reportlab") + collect_submodules("pystray") + collect_submodules("PIL")
    + ["yaml", "dill", "tqdm", "ordered_set", "pyparsing", "pypdfium2", "pypdfium2_raw", "dotenv", "anthropic"]
)

a = Analysis(
    [str(ROOT / "desktop.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    excludes=["tkinter", "matplotlib", "torch", "flet"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Komonjo-Daro",
    console=False,
    icon=str(ROOT / "packaging" / "icon.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Komonjo-Daro")
