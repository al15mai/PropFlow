"""Ordered DB migration runner (task D2m).

Until now the numbered scripts under ``scripts/migrations/`` were run by hand and
their applied/not-applied state was tracked in prose in ``scripts/README.md``.
That is fine for a human at a keyboard but leaves a hole in the ``D5b``
owner-driven update flow: a prod ``POST /admin/update`` fast-forwards the code but
never runs a migration the new code needs, so the schema silently lags until
someone SSHes in.

This module closes that:

  - a ``schema_migrations`` table records which migrations have run (id + UTC ts +
    the sha256 of the script, so an edited-after-apply migration is visible);
  - ``pending()`` diffs the ``scripts/migrations/NNN_*.py`` files against that
    table;
  - ``run_pending()`` takes a backup, then imports and runs each pending
    migration **in numeric order**, recording each as it succeeds. It stops at
    the first failure (the backup is the rollback).

Migrations whose ``run()`` needs arguments beyond ``db_path`` (currently 006's
``write_files`` and 009's owner-seed ``email``/``password``) are **not**
auto-runnable — their schema effect is already in ``db.py::initialize()`` and was
applied to live by hand. ``mark_applied()`` / the ``--baseline`` CLI flag records
them as done without re-running so they never show up as pending.

The migration scripts stay the source of truth and keep working standalone
(``python scripts/migrations/00N_x.py --apply``); this runner is an orchestration
layer on top, not a replacement.

CLI::

    cd PropFlow
    uv run python migrations_runner.py --status              # what's applied / pending
    uv run python migrations_runner.py --baseline            # record every existing migration as applied (one-time, for the live DB)
    uv run python migrations_runner.py --run                  # back up, then run pending migrations against the live DB
    uv run python migrations_runner.py --run --db /path/to/copy.db   # against a copy

Read ../CLAUDE.md. ``--run`` writes the live DB but always backs up first.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import inspect
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

# scripts/ lives at the frontend-repo root, one level above PropFlow/.
_BACKEND_DIR = Path(__file__).resolve().parent
MIGRATIONS_DIR = _BACKEND_DIR.parent / "scripts" / "migrations"

# The live DB, same anchoring rule as api.py: $PROPFLOW_DB wins, else next to this
# file. Resolved lazily so importing this module never pins a path.
def _live_db() -> Path:
    return Path(os.environ.get("PROPFLOW_DB") or (_BACKEND_DIR / "data.db"))


_NAME_RE = re.compile(r"^(\d{3})_[a-z0-9_]+\.py$")


class Migration:
    __slots__ = ("id", "path", "number", "_mod")

    def __init__(self, path: Path):
        self.path = path
        m = _NAME_RE.match(path.name)
        if not m:
            raise ValueError(f"not a migration filename: {path.name}")
        self.number = int(m.group(1))
        self.id = path.stem  # "009_auth_tables_and_owner"
        self._mod: ModuleType | None = None

    def sha256(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def _load(self) -> ModuleType:
        if self._mod is not None:
            return self._mod
        # scripts/migrations/ scripts do `sys.path.insert(0, parents[1])` (the
        # scripts/ dir) for `_dbcommon`; make sure that's importable here too.
        scripts_dir = str(MIGRATIONS_DIR.parent)
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        spec = importlib.util.spec_from_file_location(f"_migration_{self.id}", self.path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self._mod = mod
        return mod

    def run_fn(self) -> Callable[..., Any]:
        fn = getattr(self._load(), "run", None)
        if not callable(fn):
            raise AttributeError(f"{self.id} has no run() function")
        return fn

    def auto_runnable(self) -> bool:
        """True iff ``run(db_path)`` can be called with just the db path — i.e.
        every other parameter has a default."""
        try:
            sig = inspect.signature(self.run_fn())
        except (AttributeError, OSError, ImportError):
            return False
        params = [
            p for p in sig.parameters.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
        ]
        if not params:
            return False
        # first param is the db path; the rest must be optional
        return all(p.default is not inspect.Parameter.empty for p in params[1:])


def discover() -> list[Migration]:
    if not MIGRATIONS_DIR.is_dir():
        return []
    out = [Migration(p) for p in MIGRATIONS_DIR.iterdir() if _NAME_RE.match(p.name)]
    out.sort(key=lambda m: m.number)
    return out


# --- the tracking table -----------------------------------------------------

def _ensure_table(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id        TEXT PRIMARY KEY,
            appliedAt TEXT NOT NULL,
            sha256    TEXT,
            via       TEXT
        )
        """
    )


def applied_ids(db_path: Path | str) -> set[str]:
    con = sqlite3.connect(str(db_path))
    try:
        _ensure_table(con)
        con.commit()
        return {r[0] for r in con.execute("SELECT id FROM schema_migrations")}
    finally:
        con.close()


def applied_rows(db_path: Path | str) -> list[dict]:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        _ensure_table(con)
        con.commit()
        return [
            dict(r)
            for r in con.execute(
                "SELECT id, appliedAt, sha256, via FROM schema_migrations ORDER BY id"
            )
        ]
    finally:
        con.close()


def mark_applied(db_path: Path | str, mig: Migration, *, via: str = "manual") -> None:
    con = sqlite3.connect(str(db_path))
    try:
        _ensure_table(con)
        con.execute(
            "INSERT OR IGNORE INTO schema_migrations (id, appliedAt, sha256, via) "
            "VALUES (?, ?, ?, ?)",
            (mig.id, datetime.now(timezone.utc).isoformat(), mig.sha256(), via),
        )
        con.commit()
    finally:
        con.close()


def pending(db_path: Path | str) -> list[Migration]:
    done = applied_ids(db_path)
    return [m for m in discover() if m.id not in done]


# --- running ----------------------------------------------------------------

class MigrationError(RuntimeError):
    def __init__(self, mig_id: str, cause: BaseException):
        super().__init__(f"migration {mig_id} failed: {cause}")
        self.mig_id = mig_id
        self.cause = cause


def _backup(db_path: Path, reason: str) -> Path | None:
    """Snapshot ``db_path`` next to the backups dir. Best-effort: returns the
    path, or None if the backup machinery isn't importable (e.g. a bare test
    DB with no repo around it)."""
    try:
        scripts_dir = str(MIGRATIONS_DIR.parent)
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from _dbcommon import BACKUP_DIR, sqlite_copy  # type: ignore
    except Exception:
        return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = Path(BACKUP_DIR) / f"data.db.{ts}.{reason}"
    try:
        sqlite_copy(db_path, dest)
        return dest
    except Exception:
        return None


def run_pending(
    db_path: Path | str | None = None, *, backup: bool = True, via: str = "cli"
) -> dict:
    """Run every pending, auto-runnable migration in order against ``db_path``
    (default: the live DB).

    Returns ``{applied: [...], skipped_manual: [...], backup: str|None,
    up_to_date: bool}``. Raises :class:`MigrationError` on the first failure
    (nothing after it runs; the backup is the rollback).
    """
    target = Path(db_path) if db_path else _live_db()
    if not target.exists():
        raise FileNotFoundError(f"DB not found: {target}")

    todo = pending(target)
    if not todo:
        return {"applied": [], "skipped_manual": [], "backup": None, "up_to_date": True}

    runnable = [m for m in todo if m.auto_runnable()]
    manual = [m for m in todo if not m.auto_runnable()]

    backup_path = _backup(target, "pre-migrations") if (backup and runnable) else None

    applied: list[str] = []
    for mig in runnable:
        try:
            mig.run_fn()(target)
        except BaseException as e:  # noqa: BLE001 - stop the chain, surface it
            raise MigrationError(mig.id, e) from e
        mark_applied(target, mig, via=via)
        applied.append(mig.id)

    return {
        "applied": applied,
        "skipped_manual": [m.id for m in manual],
        "backup": str(backup_path) if backup_path else None,
        "up_to_date": False,
    }


def baseline(db_path: Path | str | None = None, *, through: int | None = None) -> list[str]:
    """Record existing migrations as applied **without running them** — the
    one-time bootstrap for a DB whose schema is already current.

    ``through`` caps it at migration number N inclusive; migrations after N stay
    pending. The live DB needs ``through=9``: 001–009 were applied by hand, but
    010 (``stamp_legacy_project``) has NOT been — it must run through the normal
    ``--run`` path so its data change is backed up and recorded properly.

    Idempotent."""
    target = Path(db_path) if db_path else _live_db()
    done = applied_ids(target)
    newly = []
    for mig in discover():
        if through is not None and mig.number > through:
            continue
        if mig.id not in done:
            mark_applied(target, mig, via="baseline")
            newly.append(mig.id)
    return newly


# --- CLI -------------------------------------------------------------------

def _status(db_path: Path) -> int:
    rows = {r["id"]: r for r in applied_rows(db_path)}
    print(f"DB: {db_path}")
    print(f"migrations dir: {MIGRATIONS_DIR}\n")
    for mig in discover():
        row = rows.get(mig.id)
        if row:
            drift = ""
            if row["sha256"] and row["sha256"] != mig.sha256():
                drift = "  ⚠ script changed since apply"
            print(f"  [x] {mig.id}  (applied {row['appliedAt'][:19]}, via {row['via']}){drift}")
        else:
            kind = "auto" if mig.auto_runnable() else "MANUAL — needs args"
            print(f"  [ ] {mig.id}  (pending, {kind})")
    extra = set(rows) - {m.id for m in discover()}
    for eid in sorted(extra):
        print(f"  [x] {eid}  (recorded, script missing)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", help="target DB (default: $PROPFLOW_DB or PropFlow/data.db)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--status", action="store_true", help="show applied / pending (default)")
    g.add_argument("--baseline", action="store_true",
                   help="record existing migrations as applied WITHOUT running them")
    g.add_argument("--run", action="store_true",
                   help="back up, then run pending auto-runnable migrations")
    ap.add_argument("--through", type=int, metavar="N",
                    help="with --baseline: only record migrations up to number N (e.g. --through 9)")
    ap.add_argument("--no-backup", action="store_true", help="with --run: skip the pre-run backup")
    args = ap.parse_args(argv)

    db_path = Path(args.db) if args.db else _live_db()

    if args.baseline:
        if not db_path.exists():
            print(f"ERROR: DB not found: {db_path}", file=sys.stderr)
            return 1
        newly = baseline(db_path, through=args.through)
        cap = f" (through {args.through:03d})" if args.through is not None else ""
        print(f"baselined {len(newly)} migration(s){cap}: "
              f"{', '.join(newly) or '(none — already recorded)'}")
        return 0

    if args.run:
        try:
            result = run_pending(db_path, backup=not args.no_backup, via="cli")
        except MigrationError as e:
            print(f"FAILED: {e}", file=sys.stderr)
            print("The pre-run backup is your rollback (restore_db.py).", file=sys.stderr)
            return 2
        except FileNotFoundError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        if result["up_to_date"]:
            print("up to date — nothing pending.")
        else:
            if result["backup"]:
                print(f"backup : {result['backup']}")
            print(f"applied: {', '.join(result['applied']) or '(none)'}")
            if result["skipped_manual"]:
                print(f"skipped (need args, run by hand): {', '.join(result['skipped_manual'])}")
        return 0

    return _status(db_path)


if __name__ == "__main__":
    raise SystemExit(main())
