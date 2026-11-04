# ローカルでインストーラーをビルドする（Windows）。1行ずつでなくスクリプトとして実行:
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
# 前提: venv 有効化済み、vendor\ndlkotenocr-lite を clone 済み、Inno Setup 6 インストール済み
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$version = (python -c "import kobun; print(kobun.__version__)").Trim()
pip install -q pyinstaller
if (Test-Path dist) { Remove-Item dist -Recurse -Force }
pyinstaller --noconfirm --clean packaging\komonjo.spec
$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
& $iscc "/DAppVersion=$version" packaging\installer.iss
Write-Host "出来上がり: dist\installer\Komonjo-Daro-Setup.exe (v$version)"
