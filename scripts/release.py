#!/usr/bin/env python3
"""Release a new version: `just release X.Y.Z` (runs `uv run scripts/release.py X.Y.Z`).

Order of operations (nothing is modified until every check has passed):

1. version is valid, tag does not exist yet (locally and on origin)
2. working tree is clean, on a release branch, not behind upstream
3. `just test` passes and leaves the working tree clean
4. preflight commands (opt-in publishing) pass
5. ALL version statements are edited: pyproject.toml, package.json files,
   Cargo.toml manifests (+ Cargo.lock), extra files, then post-bump commands
6. only the expected files are committed, tagged and pushed atomically

Any failure before the commit restores the edited files.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

# -- Per-repo configuration ----------------------------------------------------

TAG_PREFIX = ""  # "" -> tag `1.2.3`; "v" -> tag `v1.2.3`
RELEASE_BRANCHES = ("main", "master")
TEST_COMMAND = ["just", "test"]

# Directories with a package.json to bump. Default: ["."] if there is one.
NPM_DIRS: list[str] = []  # e.g. ["desktop", "frontend"]
# Cargo manifests whose [package]/[workspace.package] version is bumped.
# Default: ["Cargo.toml"] if it has a version. List every crate that carries the
# repo version; leave out generated crates, which keep their own versions.
CARGO_MANIFESTS: list[
    str
] = []  # e.g. ["server/Cargo.toml", "desktop/src-tauri/Cargo.toml"]
# Other version statements as (path, regex). The regex needs three groups:
# (text before version)(old version)(text after version)
EXTRA_VERSION_FILES: list[tuple[str, str]] = [
    # ("desktop/src-tauri/tauri.conf.json", r'("version":\s*")([^"]+)(")'),
]
# Commands run after the version edits, e.g. regenerating a committed file that
# embeds the version: [["cargo", "run", "--release", "--", "openapi", "-o", "openapi.json"]]
POST_BUMP_COMMANDS: list[list[str]] = []
# Files those commands may change (besides manifests, lock files and EXTRA_VERSION_FILES)
ALLOWED_CHANGES: list[str] = []  # e.g. ["server/openapi.json"]

# Opt-in publishing (see standards/ci.md). Preflight commands run after the
# tests and before any file is changed, so a release that could not be
# published fails early, e.g. [["just", "check-bitrix"]].
PREFLIGHT_COMMANDS: list[list[str]] = []
# Create a GitHub release after pushing (a workflow attaches the artifacts)
GITHUB_RELEASE = False

# ------------------------------------------------------------------------------

VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
# Files that version bumps legitimately change, wherever they are
VERSION_FILE_NAMES = {
    "pyproject.toml",
    "uv.lock",
    "package.json",
    "package-lock.json",
    "Cargo.toml",
    "Cargo.lock",
}


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def run(*command: str, cwd: str | None = None) -> None:
    subprocess.run(list(command), check=True, cwd=cwd)


def abort(message: str) -> None:
    sys.exit(f"Release aborted: {message}")


def check_preconditions(version: str, tag: str) -> None:
    if not VERSION_PATTERN.match(version):
        abort(f"`{version}` is not a version of the form X.Y.Z")
    if git("status", "--porcelain"):
        abort("working tree is dirty, commit or stash your changes first")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch not in RELEASE_BRANCHES:
        abort(f"on branch `{branch}`, release from {RELEASE_BRANCHES}")
    run("git", "fetch", "--tags", "--quiet")
    if git("tag", "--list", tag):
        abort(f"tag `{tag}` already exists")
    try:
        if int(git("rev-list", "--count", "HEAD..@{u}")) > 0:
            abort("branch is behind its upstream, pull first")
    except subprocess.CalledProcessError:
        abort("branch has no upstream")


def bump_cargo_manifest(path: Path, version: str) -> bool:
    """Set the first `version = "…"` in [package] or [workspace.package]"""
    lines = path.read_text().splitlines(keepends=True)
    section = ""
    for index, line in enumerate(lines):
        header = re.match(r"\s*\[([^\]]+)\]\s*$", line)
        if header:
            section = header.group(1).strip()
            continue
        if section in ("package", "workspace.package"):
            match = re.match(r'(\s*version\s*=\s*")([^"]+)(".*)$', line, re.S)
            if match:
                lines[index] = f"{match.group(1)}{version}{match.group(3)}"
                path.write_text("".join(lines))
                return True
    return False


def bump(version: str) -> None:
    """Edit all version statements and run the post-bump commands"""
    edited = False
    if Path("pyproject.toml").exists():
        run("uv", "version", version)
        edited = True
    for directory in NPM_DIRS or (
        ["."] if Path("package.json").exists() else []
    ):
        run(
            "npm",
            "version",
            version,
            "--no-git-tag-version",
            "--allow-same-version",
            cwd=directory,
        )
        edited = True
    manifests = CARGO_MANIFESTS or (
        ["Cargo.toml"] if Path("Cargo.toml").exists() else []
    )
    for manifest in manifests:
        if bump_cargo_manifest(Path(manifest), version):
            run("cargo", "update", "--workspace", "--manifest-path", manifest)
            edited = True
        elif CARGO_MANIFESTS:
            raise RuntimeError(f"no [package] version found in {manifest}")
    for path, pattern in EXTRA_VERSION_FILES:
        text = Path(path).read_text()
        new_text, count = re.subn(
            pattern, rf"\g<1>{version}\g<3>", text, count=1
        )
        if count != 1:
            raise RuntimeError(f"no version statement found in {path}")
        Path(path).write_text(new_text)
        edited = True
    if not edited:
        raise RuntimeError("no known version file found, edit release.py")
    for command in POST_BUMP_COMMANDS:
        run(*command)


def changed_files() -> list[str]:
    return [line for line in git("diff", "--name-only").splitlines() if line]


def new_files() -> list[str]:
    """Untracked, not ignored files (the tree was clean before the bump)"""
    return [
        line
        for line in git(
            "ls-files", "--others", "--exclude-standard"
        ).splitlines()
        if line
    ]


def main() -> None:  # noqa: C901
    if len(sys.argv) != 2:
        sys.exit("Usage: release.py X.Y.Z")
    version = sys.argv[1]
    tag = f"{TAG_PREFIX}{version}"

    os.chdir(git("rev-parse", "--show-toplevel"))
    check_preconditions(version, tag)

    print("Running tests …")
    if subprocess.run(TEST_COMMAND, check=False).returncode != 0:
        abort("tests failed, no files were changed")
    if git("status", "--porcelain"):
        abort("tests left a dirty working tree (e.g. updated lock file)")
    for command in PREFLIGHT_COMMANDS:
        print(f"Preflight: {' '.join(command)}")
        if subprocess.run(command, check=False).returncode != 0:
            abort(f"preflight `{' '.join(command)}` failed, no files changed")

    try:
        bump(version)
        allowed = {path for path, _ in EXTRA_VERSION_FILES} | set(
            ALLOWED_CHANGES
        )
        files = changed_files()
        unexpected = [
            f
            for f in files
            if Path(f).name not in VERSION_FILE_NAMES and f not in allowed
        ] + new_files()
        if unexpected:
            raise RuntimeError(f"unexpected changes: {unexpected}")
        run("git", "add", "--", *files)
        run("git", "commit", "-m", f"Release: Release version {version}")
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        subprocess.run(
            ["git", "reset", "--quiet", "HEAD", "--", "."], check=False
        )
        changed = changed_files()
        if changed:
            run("git", "checkout", "--", *changed)
        for created in new_files():  # the tree was clean, so these are ours
            Path(created).unlink()
        abort(f"{error}; version files restored")

    run("git", "tag", tag)
    try:
        run("git", "push", "--atomic", "origin", "HEAD", tag)
    except subprocess.CalledProcessError:
        sys.exit(
            f"Push failed. Local commit and tag `{tag}` exist; retry with "
            f"`git push --atomic origin HEAD {tag}` or undo with "
            f"`git tag -d {tag} && git reset --hard HEAD~1`."
        )
    if GITHUB_RELEASE:
        run("gh", "release", "create", tag, "--title", tag, "--generate-notes")
    print(f"Released {version} (tag `{tag}`)")


if __name__ == "__main__":
    main()
