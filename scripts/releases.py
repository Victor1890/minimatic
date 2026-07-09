#!/usr/bin/env python3
"""
Release script for minimatic.

Translates the release workflow to the Python ecosystem:
  - Reads / bumps the version from pyproject.toml
  - Generates a changelog from git history
  - Creates a release commit + tag
  - Pushes to GitHub and creates a GH release

Usage:
    python scripts/releases.py <patch|minor|major>
"""

from __future__ import annotations

import re
import signal
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT
VERSION_FILE = ROOT / "pyproject.toml"
CHANGELOG_PATH = ROOT / "CHANGELOG.md"
TEMP_RELEASE_NOTES_PATH = ROOT / ".release-notes-tmp.md"

VALID_BUMPS = ("patch", "minor", "major")

EXIT_CODES = {
    "invalid_usage": 1,
    "sigint": 130,
    "sigterm": 143,
}

# ── Version helpers ──────────────────────────────────────────────────────────
VERSION_RE = re.compile(r'version\s*=\s*"(\d+\.\d+\.\d+)"')


def read_version() -> str:
    """Extract the current version string from pyproject.toml."""
    content = VERSION_FILE.read_text(encoding="utf-8")
    m = VERSION_RE.search(content)
    if not m:
        fail("Could not find version string in pyproject.toml")
        return ""
    return m.group(1)


def write_version(new_version: str) -> None:
    """Replace the version string inside pyproject.toml."""
    content = VERSION_FILE.read_text(encoding="utf-8")
    updated = VERSION_RE.sub(f'version = "{new_version}"', content, count=1)
    VERSION_FILE.write_text(updated, encoding="utf-8")


def bump_version(version: str, bump_type: str) -> str:
    major, minor, patch = (int(x) for x in version.split("."))
    if bump_type == "major":
        return f"{major + 1}.0.0"
    if bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


# ── Shell helpers ────────────────────────────────────────────────────────────


def run(cmd: str, *, cwd: Path = ROOT, capture: bool = True) -> str:
    """Run a shell command and return its stripped stdout."""
    result = subprocess.run(
        cmd,
        shell=True,
        cwd=cwd,
        text=True,
        capture_output=capture,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else ""
        raise RuntimeError(f"Command failed: {cmd}\n{stderr}")
    return (result.stdout or "").strip()


def run_visible(cmd: str, *, cwd: Path = ROOT) -> None:
    """Run a shell command with inherited stdio."""
    subprocess.run(cmd, shell=True, cwd=cwd, check=True)


def fail(msg: str) -> None:
    print(f"\n❌ {msg}", file=sys.stderr)
    sys.exit(EXIT_CODES["invalid_usage"])


def normalize_repo_url(raw_url: str | None) -> str:
    """Normalize git remote URLs into browser-safe HTTPS URLs."""

    DEFAULT_REPO_URL = "https://github.com/gabrielebaez/minimatic"

    if not raw_url or not isinstance(raw_url, str):
        return DEFAULT_REPO_URL

    url = raw_url.strip()

    if url.startswith("git+https://"):
        url = re.sub(r"^git\+", "", url)

    if re.match(r"^git@github\.com:", url):
        url = re.sub(r"^git@github\.com:", "https://github.com/", url)

    if re.match(r"^ssh://git@github\.com/", url):
        url = re.sub(r"^ssh://git@github\.com/", "https://github.com/", url)

    url = re.sub(r"\.git$", "", url)
    url = re.sub(r"/+$", "", url)

    if not re.match(r"^https?://", url):
        return DEFAULT_REPO_URL

    return url


# ── Temp file cleanup ────────────────────────────────────────────────────────


def cleanup_temp_release_notes() -> None:
    try:
        TEMP_RELEASE_NOTES_PATH.unlink(missing_ok=True)
    except OSError:
        print("⚠️  Could not delete the temporary release notes file", file=sys.stderr)


# ── Git helpers ──────────────────────────────────────────────────────────────


def get_last_tag() -> str | None:
    try:
        return run("git describe --tags --abbrev=0", cwd=REPO_ROOT)
    except RuntimeError:
        return None


def get_repo_url() -> str:
    try:
        raw_url = run("git config --get remote.origin.url", cwd=REPO_ROOT)
    except RuntimeError:
        raw_url = ""
    return normalize_repo_url(raw_url)


def get_commits_since_tag(tag: str | None) -> list[dict[str, str]]:
    range_spec = f"{tag}..HEAD" if tag else "HEAD"
    log = run(
        f'git log {range_spec} --pretty=format:"%s|%h" -- .',
        cwd=REPO_ROOT,
    )
    if not log:
        return []
    commits = []
    for line in log.splitlines():
        line = line.strip().strip('"')
        if not line:
            continue
        parts = line.split("|", 1)
        if len(parts) == 2:
            commits.append({"message": parts[0], "hash": parts[1]})
    return commits


def get_people_since_tag(tag: str | None) -> dict[str, list[str]]:
    range_spec = f"{tag}..HEAD" if tag else "HEAD"

    def to_unique_people(raw: str) -> list[str]:
        people = [line.strip() for line in raw.splitlines() if line.strip()]
        return list(dict.fromkeys(people))

    authors_raw = run(
        f'git log {range_spec} --pretty=format:"%an <%ae>" -- .',
        cwd=REPO_ROOT,
    )
    committers_raw = run(
        f'git log {range_spec} --pretty=format:"%cn <%ce>" -- .',
        cwd=REPO_ROOT,
    )

    authors = to_unique_people(authors_raw)
    committers = to_unique_people(committers_raw)
    contributors = [person for person in committers if person not in authors]

    return {
        "authors": authors,
        "contributors": contributors,
    }


def build_release_people_section(people: dict[str, list[str]]) -> str:
    md = ""

    if people["authors"]:
        md += "### Authors\n\n"
        for author in people["authors"]:
            md += f"- {author}\n"
        md += "\n"

    if people["contributors"]:
        md += "### Contributors\n\n"
        for contributor in people["contributors"]:
            md += f"- {contributor}\n"
        md += "\n"

    return md


# ── Changelog ────────────────────────────────────────────────────────────────


def categorize_commits(commits: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    categories: dict[str, list[dict[str, str]]] = {
        "breaking": [],
        "feat": [],
        "fix": [],
        "other": [],
    }
    for commit in commits:
        lower = commit["message"].lower()
        if lower.startswith("feat") or "add " in lower or "add:" in lower:
            categories["feat"].append(commit)
        elif lower.startswith("fix") or "fix " in lower or "fix:" in lower:
            categories["fix"].append(commit)
        elif "breaking" in lower or "!:" in lower:
            categories["breaking"].append(commit)
        else:
            categories["other"].append(commit)
    return categories


def build_changelog(
    version: str, categories: dict[str, list[dict[str, str]]], repo_url: str
) -> str:
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    md = f"## [{version}]({repo_url}/releases/tag/v{version}) ({date})\n\n"

    sections = [
        ("breaking", "⚠️ Breaking Changes"),
        ("feat", "✨ Features"),
        ("fix", "🐛 Bug Fixes"),
        ("other", "📦 Other Changes"),
    ]

    for key, title in sections:
        items = categories[key]
        if items:
            md += f"### {title}\n\n"
            for c in items:
                md += f"- {c['message']} [`{c['hash']}`]({repo_url}/commit/{c['hash']})\n"
            md += "\n"

    return md


def update_changelog(new_entry: str) -> None:
    if CHANGELOG_PATH.exists():
        existing = CHANGELOG_PATH.read_text(encoding="utf-8")
        header_pos = existing.find("\n## ")
        if header_pos != -1:
            header = existing[: header_pos + 1]
            rest = existing[header_pos + 1 :]
            CHANGELOG_PATH.write_text(f"{header}{new_entry}{rest}", encoding="utf-8")
        else:
            lines = existing.split("\n")
            header_lines = "\n".join(lines[:2]) + "\n\n"
            CHANGELOG_PATH.write_text(f"{header_lines}{new_entry}", encoding="utf-8")
    else:
        CHANGELOG_PATH.write_text(f"# Changelog\n\n{new_entry}", encoding="utf-8")


# ── Release context / state ─────────────────────────────────────────────────
@dataclass
class ReleaseContext:
    bump: str
    repo_url: str
    current_version: str
    new_version: str
    original_version_file_content: str
    original_changelog_content: str | None
    release_start_head: str


@dataclass
class ReleaseState:
    commit_created: bool = False
    tag_created: bool = False
    remote_publish_started: bool = False
    branch_pushed: bool = False
    tag_pushed: bool = False
    rollback_started: bool = False
    release_finished: bool = False


def create_release_context(bump: str) -> ReleaseContext:
    current_version = read_version()
    return ReleaseContext(
        bump=bump,
        repo_url=get_repo_url(),
        current_version=current_version,
        new_version=bump_version(current_version, bump),
        original_version_file_content=VERSION_FILE.read_text(encoding="utf-8"),
        original_changelog_content=(
            CHANGELOG_PATH.read_text(encoding="utf-8") if CHANGELOG_PATH.exists() else None
        ),
        release_start_head=run("git rev-parse HEAD", cwd=REPO_ROOT),
    )


# ── Release steps ───────────────────────────────────────────────────────────
def check_gh_cli() -> None:
    try:
        run("gh --version", cwd=REPO_ROOT)
    except RuntimeError:
        fail(
            "GitHub CLI (gh) is not installed or not on PATH."
            " Install it: https://cli.github.com"
        )
    try:
        run("gh auth status", cwd=REPO_ROOT)
    except RuntimeError:
        fail(
            "GitHub CLI is not authenticated."
            " Run `gh auth login` and retry the release."
        )


def ensure_release_preconditions() -> None:
    current_branch = run("git branch --show-current", cwd=REPO_ROOT)
    if current_branch != "master":
        fail(f"The release can only be run on master. Current branch: {current_branch}")

    status = run("git status --porcelain -- .", cwd=REPO_ROOT)
    dirty = [f for f in status.splitlines() if f.strip()]
    if dirty:
        fail("There are uncommitted changes:\n" + "\n".join(dirty))


def run_tests() -> None:
    print("\n🧪 Running tests...")
    # ponytail: prefer `uv run pytest` since uv.lock is present; fall back to bare pytest.
    try:
        has_uv = bool(run("uv --version", cwd=REPO_ROOT))
    except RuntimeError:
        has_uv = False
    cmd = "uv run pytest" if has_uv else "pytest"
    try:
        run_visible(cmd, cwd=REPO_ROOT)
    except (subprocess.CalledProcessError, RuntimeError):
        fail("Tests failed. Release aborted before any tag or commit was created.")
    print("✅ Tests passed")


def generate_release_notes(ctx: ReleaseContext) -> tuple[str, str]:
    print("\n📝 Generating changelog...")
    last_tag = get_last_tag()
    commits = get_commits_since_tag(last_tag)

    if not commits:
        fail(f"No new commits since the last tag was {last_tag}.")

    categories = categorize_commits(commits)
    changelog_entry = build_changelog(ctx.new_version, categories, ctx.repo_url)
    people = get_people_since_tag(last_tag)
    release_notes_entry = f"{changelog_entry}{build_release_people_section(people)}"
    print(release_notes_entry)
    return changelog_entry, release_notes_entry


def update_release_files(ctx: ReleaseContext, changelog_entry: str) -> None:
    write_version(ctx.new_version)
    print(f"✅ pyproject.toml updated to {ctx.new_version}")

    update_changelog(changelog_entry)
    print("✅ CHANGELOG.md updated")


def create_release_commit_and_tag(ctx: ReleaseContext, state: ReleaseState) -> None:
    print("\n🔖 Creating commit and tag...")
    run("git add pyproject.toml CHANGELOG.md", cwd=ROOT)
    run(f'git commit -m "release: v{ctx.new_version}"', cwd=REPO_ROOT)
    state.commit_created = True
    run(f'git tag -a v{ctx.new_version} -m "v{ctx.new_version}"', cwd=REPO_ROOT)
    state.tag_created = True


def publish_release(state: ReleaseState) -> None:
    print("\n📤 Publish to GitHub...")
    state.remote_publish_started = True
    run("git push", cwd=REPO_ROOT)
    state.branch_pushed = True
    run("git push --tags", cwd=REPO_ROOT)
    state.tag_pushed = True


def create_github_release(ctx: ReleaseContext, release_notes_entry: str) -> None:
    print("\n🏷️  Creating GitHub Release...")
    release_notes = re.sub(r"^## .*\n\n", "", release_notes_entry, count=1)
    TEMP_RELEASE_NOTES_PATH.write_text(release_notes, encoding="utf-8")

    try:
        run_visible(
            f"gh release create v{ctx.new_version} "
            f'--title "v{ctx.new_version}" '
            f"--notes-file .release-notes-tmp.md",
            cwd=ROOT,
        )
        print(f"✅ Release v{ctx.new_version} created on GitHub")
    except (subprocess.CalledProcessError, RuntimeError):
        print(
            "⚠️  Could not create the release on GitHub"
            " (do you have gh installed and authenticated?)",
            file=sys.stderr,
        )
        print(
            f"   You can create it manually: {ctx.repo_url}/releases/new?tag=v{ctx.new_version}",
            file=sys.stderr,
        )
    finally:
        cleanup_temp_release_notes()


# ── Rollback ─────────────────────────────────────────────────────────────────
def rollback_release(ctx: ReleaseContext, state: ReleaseState) -> None:
    if state.rollback_started or state.release_finished:
        return

    state.rollback_started = True
    print("\n↩️  Reverting local changes from failed release...")

    cleanup_temp_release_notes()

    if state.remote_publish_started or state.branch_pushed or state.tag_pushed:
        print(
            "⚠️  Remote publication already started."
            " Skipping local history rollback to avoid divergence.",
            file=sys.stderr,
        )
        if state.tag_pushed and not state.branch_pushed:
            print(
                f"⚠️  Remote tag v{ctx.new_version} may need manual cleanup.",
                file=sys.stderr,
            )
        return

    if state.tag_created:
        try:
            run(f"git tag -d v{ctx.new_version}", cwd=REPO_ROOT)
            print(f"✅ Tag v{ctx.new_version} deleted")
        except RuntimeError:
            print(f"⚠️  Could not delete tag v{ctx.new_version}", file=sys.stderr)

    if state.commit_created:
        try:
            run(f"git reset --hard {ctx.release_start_head}", cwd=REPO_ROOT)
            print("✅ Release commit reverted")
            return
        except RuntimeError:
            print("⚠️  Could not revert release commit automatically", file=sys.stderr)

    # If no release commit was created, restore touched files directly.
    try:
        VERSION_FILE.write_text(ctx.original_version_file_content, encoding="utf-8")

        if ctx.original_changelog_content is None:
            if CHANGELOG_PATH.exists():
                CHANGELOG_PATH.unlink()
        else:
            CHANGELOG_PATH.write_text(ctx.original_changelog_content, encoding="utf-8")

        run("git restore --staged pyproject.toml CHANGELOG.md", cwd=ROOT)
        print("✅ pyproject.toml and CHANGELOG.md restored")
    except (OSError, RuntimeError):
        print("⚠️  Could not restore all files automatically", file=sys.stderr)


# ── CLI ──────────────────────────────────────────────────────────────────────
def get_requested_bump() -> str:
    if len(sys.argv) < 2 or sys.argv[1] not in VALID_BUMPS:
        fail(f"Usage: python scripts/release.py <{'|'.join(VALID_BUMPS)}>")
    return sys.argv[1]


# ── Main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    bump = get_requested_bump()
    ctx = create_release_context(bump)
    state = ReleaseState()

    # ── Signal handling ──────────────────────────────────────────────────
    def handle_signal(signum: int, _frame: object) -> None:
        sig_name = signal.Signals(signum).name
        if state.release_finished:
            sys.exit(0)
        if state.rollback_started:
            print(
                f"\n⚠️  Received {sig_name} while rollback was already running."
                " Exiting immediately.",
                file=sys.stderr,
            )
            sys.exit(EXIT_CODES.get("sigint" if signum == signal.SIGINT else "sigterm", 1))
        print(f"\n⚠️  Received {sig_name}. Canceling release...", file=sys.stderr)
        rollback_release(ctx, state)
        print("\n❌ Release canceled by user.", file=sys.stderr)
        sys.exit(EXIT_CODES.get("sigint" if signum == signal.SIGINT else "sigterm", 1))

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    print(f"\n📦 minimatic {ctx.current_version} → {ctx.new_version} ({ctx.bump})\n")

    # 0. Verify GitHub CLI is installed and authenticated.
    check_gh_cli()

    # 1. Ensure release is run only on main and from a fully clean working tree.
    ensure_release_preconditions()

    # 2. Run tests
    run_tests()

    # 3. Generate changelog
    changelog_entry, release_notes_entry = generate_release_notes(ctx)

    try:
        # 4. Update version in pyproject.toml + CHANGELOG.md
        update_release_files(ctx, changelog_entry)

        # 5. Git commit + tag
        create_release_commit_and_tag(ctx, state)

        # 6. Push to GitHub
        publish_release(state)
    except Exception as exc:
        rollback_release(ctx, state)
        fail(f"The release failed.\n{exc}")

    # 7. Create GitHub release
    create_github_release(ctx, release_notes_entry)

    state.release_finished = True
    print(f"\n🎉 Release v{ctx.new_version} completed!\n")


if __name__ == "__main__":
    main()
