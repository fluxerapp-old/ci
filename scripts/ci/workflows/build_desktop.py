#!/usr/bin/env python3

# Copyright (C) 2026 Fluxer Contributors
#
# This file is part of Fluxer.
#
# Fluxer is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Fluxer is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with Fluxer. If not, see <https://www.gnu.org/licenses/>.

import json
import pathlib
import sys
from datetime import datetime, timezone

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from ci_steps import INSTALL_RCLONE_SCRIPT, rclone_config_script
from ci_workflow import EnvArg, parse_step_env_args
from ci_utils import pwsh_step, require_env, run_step, write_github_output


PLATFORMS = [
    {"platform": "windows", "arch": "x64", "os": "windows-latest", "electron_arch": "x64"},
    {"platform": "windows", "arch": "arm64", "os": "windows-11-arm", "electron_arch": "arm64"},
    {"platform": "macos", "arch": "x64", "os": "macos-15-intel", "electron_arch": "x64"},
    {"platform": "macos", "arch": "arm64", "os": "macos-15", "electron_arch": "arm64"},
    {"platform": "linux", "arch": "x64", "os": "ubuntu-24.04", "electron_arch": "x64"},
    {"platform": "linux", "arch": "arm64", "os": "ubuntu-24.04-arm", "electron_arch": "arm64"},
]


def parse_bool(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


def set_metadata_step(channel: str) -> None:
    require_env(["GITHUB_RUN_NUMBER"])
    import os

    run_number = int(os.environ.get("GITHUB_RUN_NUMBER", "1"))
    version_offset = 8
    version = f"0.0.{run_number + version_offset}"
    pub_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    build_channel = "canary" if channel == "canary" else "stable"

    write_github_output(
        {
            "version": version,
            "pub_date": pub_date,
            "channel": channel,
            "build_channel": build_channel,
        }
    )


def set_matrix_step(flags: dict[str, bool]) -> None:
    filtered: list[dict[str, str]] = []
    for platform in PLATFORMS:
        plat = platform["platform"]
        arch = platform["arch"]
        skip = False
        if plat == "windows":
            skip = flags["skip_windows"] or (
                (arch == "x64" and flags["skip_windows_x64"])
                or (arch == "arm64" and flags["skip_windows_arm64"])
            )
        elif plat == "macos":
            skip = flags["skip_macos"] or (
                (arch == "x64" and flags["skip_macos_x64"])
                or (arch == "arm64" and flags["skip_macos_arm64"])
            )
        elif plat == "linux":
            skip = flags["skip_linux"] or (
                (arch == "x64" and flags["skip_linux_x64"])
                or (arch == "arm64" and flags["skip_linux_arm64"])
            )
        if not skip:
            filtered.append(platform)

    matrix = {"include": filtered}
    write_github_output({"matrix": json.dumps(matrix, separators=(",", ":"))})


STEPS = {
    "windows_paths": pwsh_step(
        r"""
$target = if ($env:SUBST_TARGET) { $env:SUBST_TARGET } else { $env:GITHUB_WORKSPACE }
subst W: "$target"
"WORKDIR=W:" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8

New-Item -ItemType Directory -Force "C:\t" | Out-Null
New-Item -ItemType Directory -Force "C:\sq" | Out-Null
New-Item -ItemType Directory -Force "C:\ebcache" | Out-Null
"TEMP=C:\t" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
"TMP=C:\t" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
"SQUIRREL_TEMP=C:\sq" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
"ELECTRON_BUILDER_CACHE=C:\ebcache" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8

New-Item -ItemType Directory -Force "C:\pnpm-store" | Out-Null
"NPM_CONFIG_STORE_DIR=C:\pnpm-store" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
"npm_config_store_dir=C:\pnpm-store" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8

"store-dir=C:\pnpm-store" | Set-Content -Path "W:\.npmrc" -Encoding ascii
git config --global core.longpaths true
"""
    ),
    "set_workdir_unix": "echo \"WORKDIR=${SUBST_TARGET:-$GITHUB_WORKSPACE}\" >> \"$GITHUB_ENV\"\n",
    "resolve_pnpm_store_windows": pwsh_step(
        r"""
$store = pnpm store path --silent
"PNPM_STORE_PATH=$store" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
New-Item -ItemType Directory -Force $store | Out-Null
"""
    ),
    "resolve_pnpm_store_unix": """
set -euo pipefail
store="$(pnpm store path --silent)"
echo "PNPM_STORE_PATH=$store" >> "$GITHUB_ENV"
mkdir -p "$store"
""",
    "install_setuptools_windows_arm64": pwsh_step(
        r"""
python -m pip install --upgrade pip
python -m pip install "setuptools>=69" wheel
"""
    ),
    "install_setuptools_macos": "brew install python-setuptools\n",
    "install_linux_deps": """
set -euo pipefail
sudo apt-get update
sudo apt-get install -y \
  libx11-dev libxtst-dev libxt-dev libxinerama-dev libxkbcommon-dev libxrandr-dev \
  ruby ruby-dev build-essential rpm \
  libpixman-1-dev libcairo2-dev libpango1.0-dev libjpeg-dev libgif-dev librsvg2-dev
sudo gem install --no-document fpm
""",
    "install_dependencies": "pnpm install --frozen-lockfile\n",
    "update_version": "pnpm version \"${VERSION}\" --no-git-tag-version --allow-same-version\n",
    "set_build_channel": "pnpm set-channel\n",
    "build_electron_main": "pnpm build\n",
    "build_app_macos": 'ELECTRON_ARCH="${ELECTRON_ARCH}" pnpm exec electron-builder --config electron-builder.config.cjs --mac --${ELECTRON_ARCH}\n',
    "verify_bundle_id": """
set -euo pipefail
DIST="dist-electron"
ZIP="$(ls -1 "$DIST"/*"${ELECTRON_ARCH}"*.zip | head -n1)"
tmp="$(mktemp -d)"
ditto -xk "$ZIP" "$tmp"
APP="$(find "$tmp" -maxdepth 2 -name "*.app" -print -quit)"
INFO_PLIST="$APP/Contents/Info.plist"
PROFILE="$APP/Contents/embedded.provisionprofile"
WEBAUTHN_PACKAGE="$APP/Contents/Resources/app.asar.unpacked/node_modules/@electron-webauthn/native-darwin-${ELECTRON_ARCH}/package.json"
BID=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$INFO_PLIST")

expected="app.fluxer"
expected_profile="3G5837T29K.app.fluxer"
if [[ "${BUILD_CHANNEL:-stable}" == "canary" ]]; then
  expected="app.fluxer.canary"
  expected_profile="3G5837T29K.app.fluxer.canary"
fi
echo "Bundle id in zip: $BID (expected: $expected)"
test "$BID" = "$expected"

test -f "$PROFILE"
decoded_profile="$tmp/embedded.provisionprofile.plist"
security cms -D -i "$PROFILE" > "$decoded_profile"
profile_app_id=$(/usr/libexec/PlistBuddy -c 'Print :Entitlements:com.apple.application-identifier' "$decoded_profile")
echo "Provisioning profile app id: $profile_app_id (expected: $expected_profile)"
test "$profile_app_id" = "$expected_profile"

test -f "$WEBAUTHN_PACKAGE"
echo "Found WebAuthn runtime package: $WEBAUTHN_PACKAGE"

codesign --verify --deep --strict --verbose=4 "$APP"
""",
    "build_app_windows": 'ELECTRON_ARCH="${ELECTRON_ARCH}" pnpm exec electron-builder --config electron-builder.config.cjs --win --${ELECTRON_ARCH}\n',
    "analyse_squirrel_paths": pwsh_step(
        r"""
$primaryDir = if ($env:ARCH -eq "arm64") { "dist-electron/squirrel-windows-arm64" } else { "dist-electron/squirrel-windows" }
$fallbackDir = if ($env:ARCH -eq "arm64") { "dist-electron/squirrel-windows" } else { "dist-electron/squirrel-windows-arm64" }
$dirs = @($primaryDir, $fallbackDir)

if ($env:ARCH -eq "arm64") {
  Write-Host "Skipping Squirrel path analysis for Windows arm64; Squirrel.Windows is only built for x64."
  exit 0
}

$nupkg = $null
foreach ($d in $dirs) {
  if (Test-Path $d) {
    $nupkg = Get-ChildItem -Path "$d/*.nupkg" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($nupkg) { break }
  }
}

if (-not $nupkg) {
  throw "No Squirrel nupkg found in: $($dirs -join ', ')"
}

Write-Host "Analyzing Windows installer $($nupkg.FullName)"
$env:NUPKG_PATH = $nupkg.FullName

$lines = @(
  'import os'
  'import zipfile'
  ''
  'path = os.environ["NUPKG_PATH"]'
  'build_ver = os.environ["BUILD_VERSION"]'
  'prefix = os.path.join(os.environ["LOCALAPPDATA"], "fluxer_app", f"app-{build_ver}", "resources", "app.asar.unpacked")'
  'max_len = int(os.environ.get("MAX_WINDOWS_PATH_LEN", "260"))'
  'headroom = int(os.environ.get("PATH_HEADROOM", "10"))'
  'limit = max_len - headroom'
  ''
  'with zipfile.ZipFile(path) as archive:'
  '    entries = []'
  '    for info in archive.infolist():'
  '        normalized = info.filename.lstrip("/\\\\")'
  '        total_len = len(os.path.join(prefix, normalized)) if normalized else len(prefix)'
  '        entries.append((total_len, info.filename))'
  ''
  'if not entries:'
  '    raise SystemExit("nupkg archive contains no entries")'
  ''
  'entries.sort(reverse=True)'
  'print(f"Assumed install prefix: {prefix} ({len(prefix)} chars). Maximum allowed path length: {limit} (total reserve {max_len}, headroom {headroom}).")'
  'print("Top 20 longest archived paths (length includes prefix):")'
  'for length, name in entries[:20]:'
  '    print(f"{length:4d} {name}")'
  ''
  'longest_len, longest_name = entries[0]'
  'if longest_len > limit:'
  '    raise SystemExit(f"Longest path {longest_len} for {longest_name} exceeds limit {limit}")'
  'print(f"Longest archived path {longest_len} is within the limit of {limit}.")'
)

$scriptPath = Join-Path $env:TEMP "nupkg-long-path-check.py"
Set-Content -Path $scriptPath -Value $lines -Encoding utf8
python $scriptPath
"""
    ),
    "build_app_linux": 'ELECTRON_ARCH="${ELECTRON_ARCH}" pnpm exec electron-builder --config electron-builder.config.cjs --linux --${ELECTRON_ARCH}\n',
    "prepare_artifacts_windows": pwsh_step(
        r"""
New-Item -ItemType Directory -Force upload_staging | Out-Null

$dist = Join-Path $env:WORKDIR "fluxer_desktop/dist-electron"
$sqDirName = if ($env:ARCH -eq "arm64") { "squirrel-windows-arm64" } else { "squirrel-windows" }
$sqFallbackName = if ($sqDirName -eq "squirrel-windows") { "squirrel-windows-arm64" } else { "squirrel-windows" }

$sq = Join-Path $dist $sqDirName
$sqFallback = Join-Path $dist $sqFallbackName

$picked = $null
if (Test-Path $sq) { $picked = $sq }
elseif (Test-Path $sqFallback) { $picked = $sqFallback }

if ($picked) {
  Copy-Item -Force -ErrorAction SilentlyContinue "$picked\*.exe" "upload_staging\"
  Copy-Item -Force -ErrorAction SilentlyContinue "$picked\*.exe.blockmap" "upload_staging\"
  Copy-Item -Force -ErrorAction SilentlyContinue "$picked\RELEASES*" "upload_staging\"
  Copy-Item -Force -ErrorAction SilentlyContinue "$picked\*.nupkg" "upload_staging\"
  Copy-Item -Force -ErrorAction SilentlyContinue "$picked\*.nupkg.blockmap" "upload_staging\"
} elseif ($env:ARCH -eq "arm64" -and (Test-Path $dist)) {
  Copy-Item -Force -ErrorAction SilentlyContinue "$dist\*.exe" "upload_staging\"
  Copy-Item -Force -ErrorAction SilentlyContinue "$dist\*.exe.blockmap" "upload_staging\"
}

if (Test-Path $dist) {
  Copy-Item -Force -ErrorAction SilentlyContinue "$dist\*.yml" "upload_staging\"
  Copy-Item -Force -ErrorAction SilentlyContinue "$dist\*.zip" "upload_staging\"
  Copy-Item -Force -ErrorAction SilentlyContinue "$dist\*.zip.blockmap" "upload_staging\"
}

if (-not (Get-ChildItem upload_staging -Filter *.exe -ErrorAction SilentlyContinue)) {
  throw "No installer .exe staged."
}

Get-ChildItem -Force upload_staging | Format-Table -AutoSize
"""
    ),
    "prepare_artifacts_unix": """
set -euo pipefail
mkdir -p upload_staging
DIST="${WORKDIR}/fluxer_desktop/dist-electron"

cp -f "$DIST"/*.dmg upload_staging/ 2>/dev/null || true
cp -f "$DIST"/*.zip upload_staging/ 2>/dev/null || true
cp -f "$DIST"/*.zip.blockmap upload_staging/ 2>/dev/null || true
cp -f "$DIST"/*.yml upload_staging/ 2>/dev/null || true

cp -f "$DIST"/*.AppImage upload_staging/ 2>/dev/null || true
cp -f "$DIST"/*.deb upload_staging/ 2>/dev/null || true
cp -f "$DIST"/*.rpm upload_staging/ 2>/dev/null || true
cp -f "$DIST"/*.tar.gz upload_staging/ 2>/dev/null || true

ls -la upload_staging/
""",
    "normalise_updater_yaml": """
set -euo pipefail
cd upload_staging
[[ "${PLATFORM}" == "macos" && "${ARCH}" == "arm64" && -f latest-mac.yml && ! -f latest-mac-arm64.yml ]] && mv latest-mac.yml latest-mac-arm64.yml || true
""",
    "generate_checksums_unix": """
set -euo pipefail
cd upload_staging
for file in *.exe *.dmg *.zip *.AppImage *.deb *.rpm *.tar.gz; do
  [ -f "$file" ] || continue
  sha256sum "$file" | awk '{print $1}' > "${file}.sha256"
  echo "Generated checksum for $file"
done
ls -la *.sha256 2>/dev/null || echo "No checksum files generated"
""",
    "generate_checksums_windows": pwsh_step(
        r"""
cd upload_staging
$extensions = @('.exe', '.nupkg')
Get-ChildItem -File | Where-Object { $extensions -contains $_.Extension } | ForEach-Object {
  $hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
  Set-Content -Path "$($_.FullName).sha256" -Value $hash -NoNewline
  Write-Host "Generated checksum for $($_.Name)"
}
Get-ChildItem -Filter "*.sha256" -ErrorAction SilentlyContinue | Format-Table -AutoSize
"""
    ),
    "install_rclone": INSTALL_RCLONE_SCRIPT,
    "configure_rclone": rclone_config_script(
        endpoint="https://ewr1.vultrobjects.com",
        acl="private",
    ),
    "build_payload": """
set -euo pipefail

mkdir -p s3_payload

shopt -s nullglob
for dir in artifacts/fluxer-desktop-${CHANNEL}-*; do
  [ -d "$dir" ] || continue

  base="$(basename "$dir")"
  if [[ "$base" =~ ^fluxer-desktop-[a-z]+-([a-z]+)-([a-z0-9]+)$ ]]; then
    platform="${BASH_REMATCH[1]}"
    arch="${BASH_REMATCH[2]}"
  else
    echo "Skipping unrecognised artifact dir: $base"
    continue
  fi

  case "$platform" in
    windows) plat="win32" ;;
    macos) plat="darwin" ;;
    linux) plat="linux" ;;
    *)
      echo "Unknown platform: $platform"
      continue
      ;;
  esac

  dest="s3_payload/desktop/${CHANNEL}/${plat}/${arch}"
  mkdir -p "$dest"
  cp -av "$dir"/* "$dest/" || true

  if [[ "$plat" == "darwin" ]]; then
    zip_file=""
    for z in "$dest"/*-"$arch".zip; do
      zip_file="$z"
      break
    done
    if [[ -z "$zip_file" ]]; then
      for z in "$dest"/*.zip; do
        zip_file="$z"
        break
      done
    fi

    if [[ -z "$zip_file" ]]; then
      echo "No .zip found for macOS $arch in $dest (auto-update requires zip artifacts)."
    else
      zip_name="$(basename "$zip_file")"
      url="${PUBLIC_DL_BASE}/desktop/${CHANNEL}/${plat}/${arch}/${zip_name}"

      cat > "$dest/RELEASES.json" <<EOF
{
  "currentRelease": "${VERSION}",
  "releases": [
    {
      "version": "${VERSION}",
      "updateTo": {
        "version": "${VERSION}",
        "pub_date": "${PUB_DATE}",
        "notes": "",
        "name": "${VERSION}",
        "url": "${url}"
      }
    }
  ]
}
EOF
      cp -f "$dest/RELEASES.json" "$dest/releases.json"
    fi
  fi

  setup_file=""
  dmg_file=""
  zip_file2=""
  appimage_file=""
  deb_file=""
  rpm_file=""
  targz_file=""

  if [[ "$plat" == "win32" ]]; then
    setup_file="$(ls -1 "$dest"/*.exe 2>/dev/null | grep -i 'setup' | head -n1 || true)"
    if [[ -z "$setup_file" ]]; then
      setup_file="$(ls -1 "$dest"/*.exe 2>/dev/null | head -n1 || true)"
    fi
  fi

  if [[ "$plat" == "darwin" ]]; then
    dmg_file="$(ls -1 "$dest"/*-"$arch".dmg 2>/dev/null | head -n1 || true)"
    if [[ -z "$dmg_file" ]]; then
      dmg_file="$(ls -1 "$dest"/*.dmg 2>/dev/null | head -n1 || true)"
    fi
    zip_file2="$(ls -1 "$dest"/*-"$arch".zip 2>/dev/null | head -n1 || true)"
    if [[ -z "$zip_file2" ]]; then
      zip_file2="$(ls -1 "$dest"/*.zip 2>/dev/null | head -n1 || true)"
    fi
  fi

  if [[ "$plat" == "linux" ]]; then
    appimage_file="$(ls -1 "$dest"/*.AppImage 2>/dev/null | head -n1 || true)"
    deb_file="$(ls -1 "$dest"/*.deb 2>/dev/null | head -n1 || true)"
    rpm_file="$(ls -1 "$dest"/*.rpm 2>/dev/null | head -n1 || true)"
    targz_file="$(ls -1 "$dest"/*.tar.gz 2>/dev/null | head -n1 || true)"
  fi

  read_sha256() {
    local file="$1"
    if [[ -n "$file" && -f "${file}.sha256" ]]; then
      awk '{print $1}' "${file}.sha256"
    else
      echo ""
    fi
  }

  setup_sha256="$(read_sha256 "$setup_file")"
  dmg_sha256="$(read_sha256 "$dmg_file")"
  zip_sha256="$(read_sha256 "$zip_file2")"
  appimage_sha256="$(read_sha256 "$appimage_file")"
  deb_sha256="$(read_sha256 "$deb_file")"
  rpm_sha256="$(read_sha256 "$rpm_file")"
  targz_sha256="$(read_sha256 "$targz_file")"

  jq -n \
    --arg channel "${CHANNEL}" \
    --arg platform "${plat}" \
    --arg arch "${arch}" \
    --arg version "${VERSION}" \
    --arg pub_date "${PUB_DATE}" \
    --arg setup "$(basename "${setup_file:-}")" \
    --arg setup_sha256 "${setup_sha256}" \
    --arg dmg "$(basename "${dmg_file:-}")" \
    --arg dmg_sha256 "${dmg_sha256}" \
    --arg zip "$(basename "${zip_file2:-}")" \
    --arg zip_sha256 "${zip_sha256}" \
    --arg appimage "$(basename "${appimage_file:-}")" \
    --arg appimage_sha256 "${appimage_sha256}" \
    --arg deb "$(basename "${deb_file:-}")" \
    --arg deb_sha256 "${deb_sha256}" \
    --arg rpm "$(basename "${rpm_file:-}")" \
    --arg rpm_sha256 "${rpm_sha256}" \
    --arg tar_gz "$(basename "${targz_file:-}")" \
    --arg tar_gz_sha256 "${targz_sha256}" \
    '{
      channel: $channel,
      platform: $platform,
      arch: $arch,
      version: $version,
      pub_date: $pub_date,
      files: (
        {}
        | if ($setup | length) > 0 then
            . + {setup: (if ($setup_sha256 | length) > 0 then {filename: $setup, sha256: $setup_sha256} else $setup end)}
          else . end
        | if ($dmg | length) > 0 then
            . + {dmg: (if ($dmg_sha256 | length) > 0 then {filename: $dmg, sha256: $dmg_sha256} else $dmg end)}
          else . end
        | if ($zip | length) > 0 then
            . + {zip: (if ($zip_sha256 | length) > 0 then {filename: $zip, sha256: $zip_sha256} else $zip end)}
          else . end
        | if ($appimage | length) > 0 then
            . + {appimage: (if ($appimage_sha256 | length) > 0 then {filename: $appimage, sha256: $appimage_sha256} else $appimage end)}
          else . end
        | if ($deb | length) > 0 then
            . + {deb: (if ($deb_sha256 | length) > 0 then {filename: $deb, sha256: $deb_sha256} else $deb end)}
          else . end
        | if ($rpm | length) > 0 then
            . + {rpm: (if ($rpm_sha256 | length) > 0 then {filename: $rpm, sha256: $rpm_sha256} else $rpm end)}
          else . end
        | if ($tar_gz | length) > 0 then
            . + {tar_gz: (if ($tar_gz_sha256 | length) > 0 then {filename: $tar_gz, sha256: $tar_gz_sha256} else $tar_gz end)}
          else . end
      )
    }' > "$dest/manifest.json"
done

echo "Payload tree:"
find s3_payload -maxdepth 6 -type f | sort
""",
    "upload_payload": """
set -euo pipefail

payload_filter="$(mktemp)"
metadata_filter="$(mktemp)"
trap 'rm -f "$payload_filter" "$metadata_filter"' EXIT

cat > "$payload_filter" <<'EOF'
- **/manifest.json
- **/*.yml
- **/RELEASES*
- **/releases.json
+ **
EOF

cat > "$metadata_filter" <<'EOF'
+ **/manifest.json
+ **/*.yml
+ **/RELEASES*
+ **/releases.json
- **
EOF

echo "Uploading desktop binaries and checksums first..."
rclone copy s3_payload/desktop "ovh:${S3_BUCKET}/desktop" \
  --filter-from "$payload_filter" \
  --transfers 32 \
  --checkers 16 \
  --fast-list \
  --s3-upload-concurrency 8 \
  --s3-chunk-size 16M \
  -v

echo "Uploading manifests and updater metadata last..."
rclone copy s3_payload/desktop "ovh:${S3_BUCKET}/desktop" \
  --filter-from "$metadata_filter" \
  --transfers 8 \
  --checkers 8 \
  --fast-list \
  --s3-upload-concurrency 4 \
  --s3-chunk-size 16M \
  -v
""",
    "build_summary": """
{
  echo "## Desktop ${DISPLAY_CHANNEL^} Upload Complete"
  echo ""
  echo "**Version:** ${VERSION}"
  echo ""
  echo "**S3 prefix:** desktop/${CHANNEL}/"
  echo ""
  echo "**Redirect endpoint shape:** /dl/desktop/${CHANNEL}/{plat}/{arch}/{format}"
} >> "$GITHUB_STEP_SUMMARY"
""",
}


SKIP_FLAG_ENV_MAP = {
    "skip_windows": "SKIP_WINDOWS",
    "skip_windows_x64": "SKIP_WINDOWS_X64",
    "skip_windows_arm64": "SKIP_WINDOWS_ARM64",
    "skip_macos": "SKIP_MACOS",
    "skip_macos_x64": "SKIP_MACOS_X64",
    "skip_macos_arm64": "SKIP_MACOS_ARM64",
    "skip_linux": "SKIP_LINUX",
    "skip_linux_x64": "SKIP_LINUX_X64",
    "skip_linux_arm64": "SKIP_LINUX_ARM64",
}

ENV_ARGS = [
    EnvArg("--channel", "CHANNEL"),
    EnvArg("--skip-windows", "SKIP_WINDOWS"),
    EnvArg("--skip-windows-x64", "SKIP_WINDOWS_X64"),
    EnvArg("--skip-windows-arm64", "SKIP_WINDOWS_ARM64"),
    EnvArg("--skip-macos", "SKIP_MACOS"),
    EnvArg("--skip-macos-x64", "SKIP_MACOS_X64"),
    EnvArg("--skip-macos-arm64", "SKIP_MACOS_ARM64"),
    EnvArg("--skip-linux", "SKIP_LINUX"),
    EnvArg("--skip-linux-x64", "SKIP_LINUX_X64"),
    EnvArg("--skip-linux-arm64", "SKIP_LINUX_ARM64"),
]


def main() -> int:
    import os

    args = parse_step_env_args(ENV_ARGS)

    if args.step == "set_metadata":
        channel = os.environ.get("CHANNEL", "") or "stable"
        set_metadata_step(channel)
        return 0

    if args.step == "set_matrix":
        flags = {
            key: parse_bool(os.environ.get(env_name, "false"))
            for key, env_name in SKIP_FLAG_ENV_MAP.items()
        }
        set_matrix_step(flags)
        return 0

    run_step(STEPS, args.step)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
