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

import os
import subprocess
import sys
from typing import Callable, Iterable, Mapping, Sequence

Step = str | Callable[[], None]


def run(cmd: Sequence[str], *, env: Mapping[str, str] | None = None) -> None:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    subprocess.run(cmd, check=True, env=merged_env)


def run_bash(script: str, *, env: Mapping[str, str] | None = None) -> None:
    run(["bash", "-lc", script], env=env)


def run_pwsh(script: str, *, env: Mapping[str, str] | None = None) -> None:
    run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", script], env=env)


def require_env(keys: Iterable[str]) -> None:
    missing = [key for key in keys if not os.environ.get(key)]
    if missing:
        joined = ", ".join(missing)
        raise SystemExit(f"Missing required environment variables: {joined}")


def write_github_env(pairs: Mapping[str, str]) -> None:
    path = os.environ.get("GITHUB_ENV")
    if not path:
        raise SystemExit("GITHUB_ENV is not set")
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in pairs.items():
            handle.write(f"{key}={value}\n")


def write_github_output(pairs: Mapping[str, str]) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        raise SystemExit("GITHUB_OUTPUT is not set")
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in pairs.items():
            handle.write(f"{key}={value}\n")


def write_github_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        raise SystemExit("GITHUB_STEP_SUMMARY is not set")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(text)


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def main_error(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def run_step(steps: Mapping[str, Step], step: str) -> None:
    selected = steps.get(step)
    if selected is None:
        main_error(f"Unknown step: {step}")
    if isinstance(selected, str):
        run_bash(selected)
        return
    selected()


def pwsh_step(script: str) -> Step:
    return lambda: run_pwsh(script)
