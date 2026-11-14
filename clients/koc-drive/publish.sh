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
  -p:DebugType=none \
  -p:DebugSymbols=false \
  -o "$out"

archive="${root}/dist/KocDrive-win-x64.zip"
rm -f "$archive"
python3 - "$root" << 'PY'
import sys
import zipfile
from pathlib import Path

root = Path(sys.argv[1])
folder = root / "dist" / "win-x64"
archive = root / "dist" / "KocDrive-win-x64.zip"
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
    for path in folder.rglob("*"):
        if path.is_file():
            package.write(path, Path("win-x64") / path.relative_to(folder))
print(archive)
PY
