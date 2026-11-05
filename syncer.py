#!/usr/bin/env python3
"""
alliance_sync.py — Mirror remote alliance JSON → local file → git push.

Polls the remote /data/<uuid> endpoint every N seconds. When the JSON
changes (semantic dict comparison, not byte comparison), writes
alliance.json locally, stages it, commits, and pushes to the git remote.

Usage:
    python alliance_sync.py                     # every 60s (default)
    python alliance_sync.py --once              # single cycle
    python alliance_sync.py --interval 30       # every 30s
    python alliance_sync.py --dry-run           # write only, no git
    python alliance_sync.py --once --dry-run    # single, no git
    python alliance_sync.py --url <URL> --file <PATH>

Requirements:
    Python 3.9+
    A git repo in the current directory (or wherever --file lives)
    Push credentials already configured (SSH key or cached PAT) so that
    `git push` does NOT prompt for a password.
"""
from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


# ============================================================
#   Defaults (override with CLI flags)
# ============================================================
DEFAULT_URL = "https://test-ad8f2f6c.fastapicloud.dev/data/d32cfa20-bf96-4c8e-ae08-dbbae844e42f"
DEFAULT_FILE = "alliance.json"
DEFAULT_INTERVAL = 60          # seconds
DEFAULT_BRANCH = "main"
DEFAULT_REMOTE = "origin"
COMMIT_PREFIX = "sync: alliance.json"


# ============================================================
#   Helpers
# ============================================================
def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def fetch_remote(url: str, timeout: int = 20) -> dict:
    """Fetch JSON from the remote URL. Raises on any failure."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "AllianceSync/1.0",
        "Accept": "application/json",
        "Cache-Control": "no-cache, no-store, must-revalidate",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"Remote did not return valid JSON ({e}); "
                         f"first 120 bytes: {raw[:120]!r}") from e


def load_local(path: Path) -> dict | None:
    """Load local JSON. Returns None if missing or corrupt."""
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log(f"⚠️  Local {path.name} unreadable ({e}) — will overwrite")
        return None


def write_local(path: Path, data: dict) -> None:
    """Atomically write JSON (write to .tmp, then replace)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)


def git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run a git command, capturing output. Never raises."""
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


# ============================================================
#   Git operations
# ============================================================
def has_unpushed_commits(branch: str, remote: str, cwd: Path) -> bool:
    """True if local branch is ahead of remote branch."""
    r = git(["rev-list", "--count", f"{remote}/{branch}..{branch}"], cwd)
    if r.returncode != 0:
        # remote branch doesn't exist yet → first push
        return False
    try:
        return int(r.stdout.strip()) > 0
    except ValueError:
        return False


def push_pending(branch: str, remote: str, cwd: Path) -> bool:
    """Try to push any pending commits. Returns True on success."""
    r = git(["push", remote, branch], cwd)
    if r.returncode != 0:
        log(f"⚠️  git push failed:\n   {r.stderr.strip() or r.stdout.strip()}")
        return False
    if "Everything up-to-date" not in (r.stderr + r.stdout):
        log(f"✅ Pushed to {remote}/{branch}")
    return True


def commit_and_push(
    path: Path,
    branch: str,
    remote: str,
    dry_run: bool = False,
) -> bool:
    """git add → commit → push. Returns True if pushed."""
    cwd = path.parent
    rel = path.name

    if dry_run:
        log(f"🧪 [dry-run] would run: git add {rel} && git commit && git push {remote} {branch}")
        return True

    # 1) Stage the file
    r = git(["add", rel], cwd)
    if r.returncode != 0:
        log(f"❌ git add failed:\n   {r.stderr.strip()}")
        return False

    # 2) Anything actually staged?
    r = git(["diff", "--cached", "--quiet"], cwd)
    if r.returncode == 0:
        log("ℹ️  Nothing to commit (already identical)")
        return True
    if r.returncode not in (0, 1):
        log(f"❌ git diff --cached failed:\n   {r.stderr.strip()}")
        return False

    # 3) Commit
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    r = git(["commit", "-m", f"{COMMIT_PREFIX} @ {ts}"], cwd)
    if r.returncode != 0:
        log(f"❌ git commit failed:\n   {r.stderr.strip()}")
        return False
    log(f"📝 Committed: {COMMIT_PREFIX} @ {ts}")

    # 4) Push
    if not push_pending(branch, remote, cwd):
        return False
    return True


# ============================================================
#   One sync cycle
# ============================================================
def sync_once(
    url: str,
    path: Path,
    branch: str,
    remote: str,
    dry_run: bool = False,
) -> bool:
    """Returns True if the local file was updated this cycle."""
    cwd = path.parent

    # ── 0) Retry any pending push from a previous failed cycle ──
    if not dry_run and has_unpushed_commits(branch, remote, cwd):
        log("⏫ Pending commits from previous cycle — retrying push")
        push_pending(branch, remote, cwd)

    # ── 1) Fetch remote ──
    try:
        remote_data = fetch_remote(url)
    except urllib.error.HTTPError as e:
        log(f"❌ HTTP {e.code} {e.reason} — skipping this cycle")
        return False
    except urllib.error.URLError as e:
        log(f"❌ Network error: {e.reason} — skipping this cycle")
        return False
    except Exception as e:
        log(f"❌ Fetch failed: {e} — skipping this cycle")
        return False

    # ── 2) Compare (semantic dict equality) ──
    local_data = load_local(path)

    if local_data == remote_data:
        log(f"✓ No change ({path.name})")
        return False

    if local_data is None:
        log(f"🆕 Creating {path.name}")
    else:
        log(f"🔄 Change detected — updating {path.name}")

    # ── 3) Write ──
    try:
        write_local(path, remote_data)
    except OSError as e:
        log(f"❌ Write failed: {e}")
        return False

    # ── 4) Commit + push ──
    commit_and_push(path, branch, remote, dry_run=dry_run)
    return True


# ============================================================
#   Main loop
# ============================================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Poll remote alliance JSON and mirror it to git.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--url", default=DEFAULT_URL,
                        help=f"Remote JSON URL (default: {DEFAULT_URL})")
    parser.add_argument("--file", default=DEFAULT_FILE,
                        help=f"Local file to write (default: {DEFAULT_FILE})")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help=f"Seconds between polls (default: {DEFAULT_INTERVAL})")
    parser.add_argument("--branch", default=DEFAULT_BRANCH,
                        help=f"Git branch (default: {DEFAULT_BRANCH})")
    parser.add_argument("--remote", default=DEFAULT_REMOTE,
                        help=f"Git remote (default: {DEFAULT_REMOTE})")
    parser.add_argument("--once", action="store_true",
                        help="Run one cycle and exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="Write file but skip git add/commit/push")
    args = parser.parse_args()

    path = Path(args.file).resolve()
    cwd = path.parent

    # ── Sanity checks ──
    if not (cwd / ".git").exists():
        log(f"⚠️  No .git directory in {cwd} — git commands will fail.")
    if not cwd.exists():
        log(f"❌ Directory does not exist: {cwd}")
        return 1

    log("════════════════════════════════════════════════════════")
    log(f"🔄 Alliance sync starting")
    log(f"   URL:     {args.url}")
    log(f"   File:    {path}")
    log(f"   Git:     {args.remote}/{args.branch}")
    log(f"   Mode:    {'once' if args.once else f'every {args.interval}s'}"
        f"{' [dry-run]' if args.dry_run else ''}")
    log("════════════════════════════════════════════════════════")

    # ── One-shot mode ──
    if args.once:
        changed = sync_once(args.url, path, args.branch, args.remote, args.dry_run)
        return 0 if changed or True else 0

    # ── Continuous mode ──
    stop = {"flag": False}

    def _handle_signal(signum, frame):
        stop["flag"] = True
        log(f"🛑 Signal {signum} received — finishing current cycle…")

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    cycles = 0
    changes = 0

    while not stop["flag"]:
        cycles += 1
        try:
            if sync_once(args.url, path, args.branch, args.remote, args.dry_run):
                changes += 1
        except Exception as e:
            log(f"❌ Unexpected error in cycle {cycles}: {e}")

        # Sleep in 1s chunks so Ctrl+C / SIGTERM is responsive
        for _ in range(args.interval):
            if stop["flag"]:
                break
            time.sleep(1)

    log(f"👋 Stopped. Ran {cycles} cycles, {changes} update(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())