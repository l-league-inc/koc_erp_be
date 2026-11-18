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

csproj="${root}/src/KocDrive.App/KocDrive.App.csproj"
if [[ -n "${VERSION:-}" ]]; then
  version="$VERSION"
else
  version="$(sed -n 's/.*<Version>\([^<]*\)<\/Version>.*/\1/p' "$csproj" | head -n 1)"
fi
if [[ ! "$version" =~ ^[0-9]+(\.[0-9]+){1,3}$ ]]; then
  echo "버전은 1.2.0 형식이어야 합니다. 예: make drive VERSION=1.2.0" >&2
  exit 1
fi
IFS='.' read -r major minor patch revision <<<"$version"
file_version="${major}.${minor}.${patch:-0}.${revision:-0}"
if [[ -n "${VERSION:-}" ]]; then
  python3 - "$csproj" "$version" "$file_version" << 'PY'
import pathlib, re, sys
path, version, file_version = sys.argv[1:]
file = pathlib.Path(path)
text = file.read_text()
replacements = {
    "Version": version,
    "AssemblyVersion": file_version,
    "FileVersion": file_version,
    "InformationalVersion": version,
}
for tag, value in replacements.items():
    pattern = rf"<{tag}>[^<]*</{tag}>"
    updated, count = re.subn(pattern, f"<{tag}>{value}</{tag}>", text, count=1)
    if count != 1:
        raise SystemExit(f"{tag} 태그를 찾지 못했습니다.")
    text = updated
file.write_text(text)
PY
fi

out="${root}/dist/win-x64"
rm -rf "$out"
"$dotnet_bin" publish "$csproj" \
  -c Release \
  -r win-x64 \
  --self-contained true \
  -p:Version="$version" \
  -p:AssemblyVersion="$file_version" \
  -p:FileVersion="$file_version" \
  -p:InformationalVersion="$version" \
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
echo "버전 ${version}. 관리자 화면 Drive 릴리스에도 같은 번호를 적으세요. 번호를 바꾸려면 make drive VERSION=1.2.0 입니다."
