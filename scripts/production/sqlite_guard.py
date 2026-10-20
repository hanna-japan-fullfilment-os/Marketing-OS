"""Offline deployment utilities. Never imports the application or restores a DB."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from datetime import datetime, timezone, timedelta


def absolute(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute() or any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise ValueError("Absolute, non-symlink path required")
    return path.resolve(strict=True)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


@contextlib.contextmanager
def readonly(path: Path):
    path = absolute(path)
    # immutable is safe only without a live WAL. Normal production WAL reads
    # use SQLite's read-only connection and existing WAL/SHM infrastructure.
    wal = Path(str(path) + "-wal")
    live_wal = wal.exists() and wal.stat().st_size > 0
    if live_wal and not Path(str(path) + "-shm").exists():
        raise ValueError("Live WAL without SHM: refuse sidecar creation")
    uri = path.as_uri() + "?mode=ro" + ("" if live_wal else "&immutable=1")
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    try:
        conn.execute("PRAGMA query_only=ON")
        yield conn
    finally:
        conn.close()


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def snapshot(conn: sqlite3.Connection) -> dict:
    schema = conn.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    ).fetchall()
    fingerprint = hashlib.sha256(json.dumps(schema, ensure_ascii=False,
        separators=(",", ":")).encode("utf-8")).hexdigest().upper()
    counts = {name: conn.execute("SELECT count(*) FROM " + quote(name)).fetchone()[0]
              for kind, name, _, _ in schema if kind == "table"}
    # Sorted row encodings preserve duplicate multiplicity and avoid relying on
    # rowid or a particular primary-key layout. Hashes, never row values, leave here.
    data = {}
    for table in counts:
        encodings = []
        for row in conn.execute("SELECT * FROM " + quote(table)):
            encoded = json.dumps([{"blob": x.hex()} if isinstance(x, bytes) else x
                                  for x in row], ensure_ascii=False,
                                 separators=(",", ":")).encode("utf-8")
            encodings.append(hashlib.sha256(encoded).digest())
        data[table] = hashlib.sha256(b"".join(sorted(encodings))).hexdigest().upper()
    return {"schema_sha256": fingerprint, "row_counts": counts, "data_sha256": data}


def inspect(path: Path, revision: str, contract: dict | None = None) -> dict:
    with readonly(path) as conn:
        conn.execute("BEGIN")
        quick = [r[0] for r in conn.execute("PRAGMA quick_check")]
        if quick != ["ok"]:
            raise ValueError("SQLite quick_check failed")
        rows = conn.execute("SELECT version_num FROM alembic_version").fetchall()
        if rows != [(revision,)]:
            raise ValueError("Exactly one approved Alembic revision required")
        result = snapshot(conn)
        if contract:
            if result["schema_sha256"] != contract["schema_sha256"]:
                raise ValueError("Schema contract mismatch")
            if not set(contract.get("required_tables", [])).issubset(result["row_counts"]):
                raise ValueError("Missing prerequisite table")
            for key, expected in contract.get("expected_settings", {}).items():
                setting = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
                if setting is None:
                    raise ValueError("Required effective root setting absent")
                value = json.loads(setting[0]) if isinstance(setting[0], str) else setting[0]
                if isinstance(value, dict):
                    value = value.get("v")
                if value != expected:
                    raise ValueError("Effective source/output root changed")
        result.update(revision=revision, quick_check="ok")
        return result


def backup(source: Path, destination: Path, revision: str, contract: dict) -> dict:
    source = absolute(source)
    parent = absolute(destination.parent)
    if destination.exists() or destination.is_symlink() or destination.resolve() == source:
        raise ValueError("Backup must be a new distinct file")
    before = inspect(source, revision, contract)
    # Exclusive reservation prevents clobbering any existing backup.
    descriptor = os.open(parent / destination.name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    try:
        with readonly(source) as src:
            dst = sqlite3.connect(destination)
            try:
                deadline = time.monotonic() + 120
                def progress(status, remaining, total):
                    if time.monotonic() > deadline:
                        raise TimeoutError("Backup time limit exceeded")
                src.backup(dst, pages=256, sleep=0.01, progress=progress)
            finally:
                dst.close()
        copied = inspect(destination, revision, contract)
        after = inspect(source, revision, contract)
        if before != copied or before != after:
            raise ValueError("Source changed or backup schema/data comparison failed")
        return {"source": str(source), "source_sha256": sha256(source),
                "backup": str(destination), "sha256": sha256(destination),
                "size_bytes": destination.stat().st_size, "verified": True,
                "utc": datetime.now(timezone.utc).isoformat(), **copied}
    except Exception:
        # Partial backup is evidence. Never automatically delete or restore it.
        raise


def retention_candidates(manifests: list[dict]) -> list[str]:
    """Keep union of 14 daily, 8 weekly and 12 monthly verified snapshots."""
    keep = set()
    records = sorted(manifests, key=lambda m: m["utc"], reverse=True)
    for limit, bucket in [(14, lambda d: d.date()),
                          (8, lambda d: d.isocalendar()[:2]),
                          (12, lambda d: (d.year, d.month))]:
        buckets = set()
        for record in records:
            if record.get("verified") is not True:
                raise ValueError("Unverified retention manifest")
            stamp = datetime.fromisoformat(record["utc"])
            if stamp.tzinfo is None:
                raise ValueError("Retention timestamps need timezone")
            period = bucket(stamp.astimezone(timezone(timedelta(hours=9))))
            if period not in buckets and len(buckets) < limit:
                buckets.add(period)
                keep.add(record["backup"])
    return [r["backup"] for r in records if r["backup"] not in keep]


def compare_preserved(reference: Path, database: Path) -> dict:
    """Verify old columns/rows survived an additive migration (excluding revision)."""
    with readonly(reference) as before, readonly(database) as after:
        before.execute("BEGIN"); after.execute("BEGIN")
        tables = [r[0] for r in before.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name!='alembic_version'")]
        for table in tables:
            columns = [r[1] for r in before.execute("PRAGMA table_info(" + quote(table) + ")")]
            after_columns = [r[1] for r in after.execute("PRAGMA table_info(" + quote(table) + ")")]
            if not set(columns).issubset(after_columns):
                raise ValueError("Pre-existing table/column removed")
            query = "SELECT " + ",".join(map(quote, columns)) + " FROM " + quote(table)
            def digest(conn):
                rows = [hashlib.sha256(json.dumps([{"blob": x.hex()} if isinstance(x, bytes) else x for x in row],
                       ensure_ascii=False, separators=(",", ":")).encode()).digest() for row in conn.execute(query)]
                return sorted(rows)
            if digest(before) != digest(after):
                raise ValueError("Pre-existing data changed during migration")
        return {"preserved": True, "table_count": len(tables)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["inspect", "backup", "retention", "compare"])
    parser.add_argument("--database", type=Path)
    parser.add_argument("--revision")
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--manifests", type=Path)
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args()
    if args.operation == "retention":
        result = retention_candidates(json.loads(absolute(args.manifests).read_text(encoding="utf-8")))
    elif args.operation == "compare":
        if not args.reference or not args.database:
            parser.error("reference and database required")
        result = compare_preserved(args.reference, args.database)
    else:
        if not args.database or not args.revision or not args.contract:
            parser.error("database, revision and contract are required")
        contract = json.loads(absolute(args.contract).read_text(encoding="utf-8"))["schema_contract"]
        if args.operation == "backup":
            if not args.destination or not args.destination.is_absolute():
                parser.error("absolute destination required")
            result = backup(args.database, args.destination, args.revision, contract)
        else:
            result = inspect(args.database, args.revision, contract)
    print(json.dumps(result, sort_keys=True, ensure_ascii=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Do not print SQL values, environment, connection strings or tracebacks.
        print(json.dumps({"ok": False, "error_type": type(exc).__name__}), file=sys.stderr)
        sys.exit(1)
