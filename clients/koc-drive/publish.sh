#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")" && pwd)"
dotnet_bin="${DOTNET:-}"
if [[ -z "$dotnet_bin" ]]; then
  if command -v dotnet >/dev/null 2>&1; then
    dotnet_bin="$(command -v dotnet)"
  elif [[ -x "${HOME}/.dotnet/dotnet" ]]; then
    dotnet_bin="${HOME}/.dotnet/dotnet"
  else
    echo "dotnet SDK 8이 필요합니다." >&2
    exit 1
  fi
fi

export DOTNET_ROOT="$(dirname "$dotnet_bin")"
export PATH="${DOTNET_ROOT}:${PATH}"
export DOTNET_CLI_TELEMETRY_OPTOUT=1

out="${root}/dist/win-x64"
rm -rf "$out"
"$dotnet_bin" publish "${root}/src/KocDrive.App/KocDrive.App.csproj" \
  -c Release \
  -r win-x64 \
  --self-contained true \
  -p:PublishSingleFile=true \
  -p:IncludeNativeLibrariesForSelfExtract=true \
  -p:EnableCompressionInSingleFile=true \
  -p:SatelliteResourceLanguages=ko \
  -p:DebugType=none \
  -p:DebugSymbols=false \
  -o "$out"

archive="${root}/dist/KocDrive-win-x64.zip"
rm -f "$archive"
python3 - "$root" << 'PY'
import shutil
import sys
import zipfile
from pathlib import Path

root = Path(sys.argv[1])
folder = root / "dist" / "win-x64"
exe = folder / "KOC ERP.exe"
source = folder / "KocDrive.exe"
if source.exists():
    source.replace(exe)
for path in list(folder.iterdir()):
    if path.resolve() == exe.resolve():
        continue
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
archive = root / "dist" / "KocDrive-win-x64.zip"
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
    package.write(exe, exe.name)
print(archive)
print(exe)
PY
version="$(sed -n 's/.*<Version>\([^<]*\)<\/Version>.*/\1/p' "${root}/src/KocDrive.App/KocDrive.App.csproj" | head -n 1)"
echo "버전 ${version}. 관리자 화면 Drive 릴리스에 dist/win-x64/KOC ERP.exe 를 올리세요. zip은 올리지 않습니다."
