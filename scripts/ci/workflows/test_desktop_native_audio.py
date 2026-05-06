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

from __future__ import annotations

import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from ci_utils import pwsh_step, run_step
from ci_workflow import parse_step_env_args


ENSURE_ELECTRON_BINARY = """
if ! node -e "const electron = require('electron'); if (typeof electron !== 'string') process.exit(1);" >/dev/null 2>&1; then
  ELECTRON_SKIP_BINARY_DOWNLOAD= pnpm rebuild electron
fi
node -e "const electron = require('electron'); if (typeof electron !== 'string') throw new Error('electron package did not resolve to a binary path'); console.log('electron binary=' + electron);"
"""


STEPS = {
    "windows_paths": pwsh_step(
        r"""
$target = if ($env:SUBST_TARGET) { $env:SUBST_TARGET } else { $env:GITHUB_WORKSPACE }
subst W: "$target"
"WORKDIR=W:" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8

New-Item -ItemType Directory -Force "C:\t" | Out-Null
New-Item -ItemType Directory -Force "C:\pnpm-store" | Out-Null
"TEMP=C:\t" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
"TMP=C:\t" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
"NPM_CONFIG_STORE_DIR=C:\pnpm-store" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
"npm_config_store_dir=C:\pnpm-store" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8

"store-dir=C:\pnpm-store" | Set-Content -Path "W:\.npmrc" -Encoding ascii
git config --global core.longpaths true
"""
    ),
    "set_workdir_unix": """
set -euo pipefail
echo "WORKDIR=${GITHUB_WORKSPACE}/source" >> "$GITHUB_ENV"
""",
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
    "install_zig_unix": """
set -euo pipefail
: "${ZIG_VERSION:?ZIG_VERSION is required}"

case "$(uname -s)-$(uname -m)" in
  Linux-x86_64) zig_os="linux"; zig_arch="x86_64" ;;
  Linux-aarch64|Linux-arm64) zig_os="linux"; zig_arch="aarch64" ;;
  Darwin-x86_64) zig_os="macos"; zig_arch="x86_64" ;;
  Darwin-arm64) zig_os="macos"; zig_arch="aarch64" ;;
  *) echo "Unsupported Zig host: $(uname -s)-$(uname -m)" >&2; exit 1 ;;
esac

tool_dir="${RUNNER_TOOL_CACHE:-$RUNNER_TEMP}/zig/${ZIG_VERSION}-pypi-${zig_os}-${zig_arch}"
pkg_dir="${tool_dir}/py"
zig_bin="${pkg_dir}/ziglang/zig"

if [ ! -x "$zig_bin" ]; then
  rm -rf "$tool_dir"
  mkdir -p "$pkg_dir"
  python3 -m pip install \
    --disable-pip-version-check \
    --no-input \
    --no-compile \
    --only-binary=:all: \
    --target "$pkg_dir" \
    "ziglang==${ZIG_VERSION}"
fi

echo "${pkg_dir}/ziglang" >> "$GITHUB_PATH"
"$zig_bin" version
""",
    "install_zig_windows": pwsh_step(
        r"""
if (-not $env:ZIG_VERSION) {
  throw "ZIG_VERSION is required."
}

$arch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "aarch64" } else { "x86_64" }
$toolRoot = if ($env:RUNNER_TOOL_CACHE) { $env:RUNNER_TOOL_CACHE } else { $env:RUNNER_TEMP }
$toolDir = Join-Path $toolRoot "zig\$($env:ZIG_VERSION)-pypi-windows-$arch"
$pkgDir = Join-Path $toolDir "py"
$zigBinDir = Join-Path $pkgDir "ziglang"
$zigExe = Join-Path $zigBinDir "zig.exe"

if (-not (Test-Path $zigExe)) {
  if (Test-Path $toolDir) {
    Remove-Item -Recurse -Force $toolDir
  }
  New-Item -ItemType Directory -Force $pkgDir | Out-Null
  python -m pip install `
    --disable-pip-version-check `
    --no-input `
    --no-compile `
    --only-binary=:all: `
    --target $pkgDir `
    "ziglang==$($env:ZIG_VERSION)"
}

$zigBinDir | Out-File -FilePath $env:GITHUB_PATH -Append -Encoding utf8
& $zigExe version
"""
    ),
    "install_linux_deps": """
set -euo pipefail
sudo apt-get update
sudo apt-get install -y \
  build-essential pkg-config \
  libpipewire-0.3-dev libspa-0.2-dev pipewire pipewire-bin wireplumber \
  dbus-x11 xvfb weston xwayland
""",
    "install_windows_deps": pwsh_step(
        r"""
python -m pip install --upgrade pip
python -m pip install "setuptools>=69" wheel
"""
    ),
    "install_macos_deps": """
set -euo pipefail
brew install python-setuptools
""",
    "install_dependencies": """
set -euo pipefail
pnpm install --frozen-lockfile
""",
    "prepare_node_headers": """
set -euo pipefail
pnpm exec node-gyp install --target "$(node -p 'process.versions.node')"
""",
    "run_shared_tests": """
set -euo pipefail
if [ "${PLATFORM:-}" = "windows" ] && [ "${ARCH:-}" = "arm64" ]; then
  pnpm test:linux-audio-helpers
  pnpm --dir native/linux-audio-capture test
  (
    cd native/win-process-loopback
    zig test -fno-emit-bin src/windows_version.zig
    zig test -fno-emit-bin src/audio_contract.zig
  )
else
  pnpm test:native-audio
fi
pnpm typecheck
""",
    "build_linux_native": """
set -euo pipefail
pnpm --dir native/linux-audio-capture build
installed="node_modules/@fluxer/linux-audio-capture"
if [ -d "$installed" ]; then
  case "${ARCH:-$(uname -m)}" in
    x64|x86_64) artifact="native/linux-audio-capture/linux-audio-capture.linux-x64-gnu.node" ;;
    arm64|aarch64) artifact="native/linux-audio-capture/linux-audio-capture.linux-arm64-gnu.node" ;;
    *) echo "Unsupported Linux architecture for artifact sync: ${ARCH:-$(uname -m)}" >&2; exit 1 ;;
  esac
  dest="$installed/$(basename "$artifact")"
  if [ ! -f "$artifact" ]; then
    echo "Linux native artifact was not produced: $artifact" >&2
    exit 1
  fi
  if [ ! -e "$dest" ] || [ ! "$artifact" -ef "$dest" ]; then
    cp -f "$artifact" "$installed"/
  fi
fi
""",
    "smoke_linux_native": """
set -euo pipefail
node - <<'NODE'
const direct = require('./native/linux-audio-capture');
const installed = require('./node_modules/@fluxer/linux-audio-capture');

for (const [label, addon] of [['direct', direct], ['installed', installed]]) {
  if (typeof addon.pipeWireAvailable !== 'function') {
    throw new Error(`${label}: pipeWireAvailable export missing`);
  }
  if (typeof addon.AudioBridge !== 'function') {
    throw new Error(`${label}: AudioBridge export missing`);
  }
  const bridge = new addon.AudioBridge();
  const inventory = bridge.inventory(['media.class', 'node.name', 'object.id']);
  if (!Array.isArray(inventory)) {
    throw new Error(`${label}: inventory did not return an array`);
  }
  if (bridge.apply({include: [{applicationProcessBinary: '__definitely_missing__'}]})) {
    bridge.release();
  }
  bridge.release();
  console.log(`${label}: PipeWire available=${addon.pipeWireAvailable()} inventory=${inventory.length}`);
}
NODE
""",
    "pipewire_session_smoke": """
set -euo pipefail

runtime="${RUNNER_TEMP}/xdg-runtime"
rm -rf "$runtime"
mkdir -p "$runtime"
chmod 700 "$runtime"

dbus-run-session -- bash -lc '
set -euo pipefail
export XDG_RUNTIME_DIR="'"$runtime"'"

pipewire >"${RUNNER_TEMP}/pipewire.log" 2>&1 &
pipewire_pid=$!
wireplumber >"${RUNNER_TEMP}/wireplumber.log" 2>&1 &
wireplumber_pid=$!
trap "kill $wireplumber_pid $pipewire_pid 2>/dev/null || true; wait $wireplumber_pid $pipewire_pid 2>/dev/null || true" EXIT

for _ in $(seq 1 80); do
  if pw-cli info 0 >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

if ! pw-cli info 0 >/dev/null 2>&1; then
  echo "::group::pipewire.log"
  cat "${RUNNER_TEMP}/pipewire.log" || true
  echo "::endgroup::"
  echo "::group::wireplumber.log"
  cat "${RUNNER_TEMP}/wireplumber.log" || true
  echo "::endgroup::"
  exit 1
fi

node - <<'"'"'NODE'"'"'
const addon = require("./native/linux-audio-capture");
if (!addon.pipeWireAvailable()) {
  throw new Error("PipeWire should be reachable inside dbus-run-session");
}
const bridge = new addon.AudioBridge();
const inventory = bridge.inventory(["media.class", "node.name", "object.id"]);
const ok = bridge.apply({onlySpeakers: true});
bridge.release();
if (!ok) {
  throw new Error("AudioBridge.apply failed against live PipeWire session");
}
console.log(`live PipeWire inventory=${inventory.length}`);
NODE
'
""",
    "build_windows_native": """
set -euo pipefail
pnpm --dir native/win-process-loopback build
""",
    "smoke_windows_native": """
set -euo pipefail
node - <<'NODE'
const addon = require('./native/win-process-loopback');

if (typeof addon.isSupported !== 'function') throw new Error('isSupported export missing');
if (typeof addon.pidFromHwnd !== 'function') throw new Error('pidFromHwnd export missing');
if (typeof addon.resolveAudioRootPid !== 'function') throw new Error('resolveAudioRootPid export missing');
if (typeof addon.ProcessLoopback !== 'function') throw new Error('ProcessLoopback export missing');

const supported = addon.isSupported();
const rootPid = addon.resolveAudioRootPid(process.pid);
const nullWindowPid = addon.pidFromHwnd(0n);
if (supported !== true) {
  throw new Error('process loopback support probe returned false on a supported Windows runner');
}
if (!Number.isInteger(rootPid) || rootPid <= 0) {
  throw new Error(`resolveAudioRootPid returned invalid pid: ${rootPid}`);
}
if (nullWindowPid !== 0) {
  throw new Error(`pidFromHwnd(0n) returned ${nullWindowPid}, expected 0`);
}
try {
  new addon.ProcessLoopback(process.pid, {sampleRate: 44100}, () => {}, () => {}, () => {});
  throw new Error('invalid sampleRate was accepted');
} catch (error) {
  if (!(error instanceof RangeError)) {
    throw error;
  }
}

const loopback = new addon.ProcessLoopback(process.pid, {sampleRate: 48000, channels: 2}, () => {}, () => {}, () => {});
loopback.stop();
console.log(`process loopback supported=${supported} rootPid=${rootPid}`);
NODE
""",
    "build_macos_native": """
set -euo pipefail
pnpm --dir native/mac-app-audio typecheck
pnpm --dir native/mac-app-audio build:ts
pnpm --dir native/mac-app-audio exec cmake-js compile
""",
    "smoke_macos_native": """
set -euo pipefail
node - <<'NODE'
(async () => {
  const addon = require('./native/mac-app-audio');
  if (typeof addon.getBackendAvailability !== 'function') {
    throw new Error('getBackendAvailability export missing');
  }
  if (typeof addon.listAudibleApplications !== 'function') {
    throw new Error('listAudibleApplications export missing');
  }
  if (typeof addon.pidFromWindowId !== 'function') {
    throw new Error('pidFromWindowId export missing');
  }
  if (typeof addon.ProcessLoopback !== 'function') {
    throw new Error('ProcessLoopback export missing');
  }
  const availability = await addon.getBackendAvailability();
  if (!availability || typeof availability !== 'object') {
    throw new Error('getBackendAvailability did not return an object');
  }
  const loopback = new addon.ProcessLoopback(process.pid);
  await loopback.stop();
  console.log(JSON.stringify(availability));
})();
NODE
""",
    "electron_smoke_linux": f"""
set -euo pipefail
{ENSURE_ELECTRON_BINARY}
ELECTRON_RUN_AS_NODE=1 pnpm exec electron -e "const addon = require('./native/linux-audio-capture'); const bridge = new addon.AudioBridge(); bridge.release(); console.log('electron linux native load ok');"
""",
    "electron_smoke_windows": f"""
set -euo pipefail
{ENSURE_ELECTRON_BINARY}
ELECTRON_RUN_AS_NODE=1 pnpm exec electron -e "const addon = require('./native/win-process-loopback'); if (typeof addon.isSupported !== 'function') throw new Error('missing isSupported'); console.log('electron windows native load ok');"
""",
    "electron_smoke_macos": f"""
set -euo pipefail
{ENSURE_ELECTRON_BINARY}
ELECTRON_RUN_AS_NODE=1 pnpm exec electron -e "const addon = require('./native/mac-app-audio'); if (typeof addon.getBackendAvailability !== 'function') throw new Error('missing getBackendAvailability'); console.log('electron macos native load ok');"
""",
}


def main() -> int:
    args = parse_step_env_args()
    run_step(STEPS, args.step)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
