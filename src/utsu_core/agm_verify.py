"""
Verify AGM voter RSVPs against uoft_data. Used by agm.py, and runnable on its own:

    python -m utsu_core.agm_verify --agm_file RSVP.csv --db path/to/db.sqlite [--output_dir DIR]
    python -m utsu_core.agm_verify --testing        # fake RSVPs from the last `main --testing` run, against its database

The standalone run only reports (agm_verification.csv); it writes no voter lists and no database rows.

The RSVP form has no student number, so a person is matched on their ACORN-registered name. A name shared by more
than one student cannot be decided and stays unverified until the form also supplies a "Student Number" column,
which is then used to tell them apart.
"""
import argparse
import csv
import logging
import sqlite3
from pathlib import Path

from utsu_std.utils import absfile
from utsu_std.parsing_utils import get_trunc_id

logger = logging.getLogger(__name__)

NAME_QUERY_CHUNK = 500
REPORT_FIELDS = ["uuid", "status", "reason", "match_method", "student_uuid", "full_name", "email", "flags"]


def is_yes(value: str) -> bool:
    """
    >>> is_yes(" Yes, I agree")
    True
    >>> is_yes("")
    False
    """
    return (value or "").strip().lower().startswith("yes")


def students_by_name(names: set[str], cursor: sqlite3.Cursor) -> dict[str, list[tuple[str, int]]]:
    """{full_name: [(uoft_data.uuid, trunc_id), ...]} for the given names."""
    found: dict[str, list[tuple[str, int]]] = {}
    names = sorted(names)
    for start in range(0, len(names), NAME_QUERY_CHUNK):
        chunk = names[start:start + NAME_QUERY_CHUNK]
        cursor.execute(f"SELECT uuid, trunc_id, full_name FROM uoft_data WHERE full_name IN "
                       f"({','.join('?' * len(chunk))})", chunk)
        for student_uuid, trunc_id, full_name in cursor.fetchall():
            found.setdefault(full_name, []).append((student_uuid, trunc_id))
    return found


def verify_rsvp(rsvp: dict, candidates: list[tuple[str, int]]) -> tuple[str | None, str, str]:
    """
    Decide one RSVP given the students sharing its name. Returns (student uuid or None, match method, reason).

    >>> verify_rsvp({"student_number": ""}, [("u1", 3161)])
    ('u1', 'name only', '')
    >>> verify_rsvp({"student_number": ""}, [("u1", 3161), ("u2", 1111)])
    (None, '', 'name shared by 2 students; a student number is needed')
    >>> verify_rsvp({"student_number": "1001231617"}, [("u1", 3161), ("u2", 1111)])
    ('u1', 'name + student number', '')
    >>> verify_rsvp({"student_number": "1001239999"}, [("u1", 3161)])
    (None, '', 'student number does not match')
    >>> verify_rsvp({"student_number": ""}, [])
    (None, '', 'name not found')
    """
    if not candidates:
        return None, "", "name not found"
    if rsvp.get("student_number"):
        trunc = get_trunc_id(rsvp["student_number"])
        trunc = int(trunc) if str(trunc).isdigit() else None
        hits = [c for c in candidates if c[1] == trunc]
        return (hits[0][0], "name + student number", "") if hits else (None, "", "student number does not match")
    if len(candidates) > 1:
        return None, "", f"name shared by {len(candidates)} students; a student number is needed"
    return candidates[0][0], "name only", ""


def review_flags(rsvp: dict, match_method: str, reason: str) -> str:
    flags = []
    if match_method == "name only":
        flags.append("name_only_match")
    if reason.startswith("name shared"):
        flags.append("ambiguous_name")
    if not is_yes(rsvp.get("data_confirmation", "")):
        flags.append("no_data_confirmation")
    if not rsvp.get("email"):
        flags.append("no_uoft_email")
    return ";".join(flags)


def verify_rsvps(rsvps: list[dict], cursor: sqlite3.Cursor) -> tuple[list[dict], list[dict]]:
    """
    Verify RSVPs (one per person) against uoft_data. Sets student_uuid, match_method, reason, status and flags on
    each and returns (verified, unverified).
    """
    candidates = students_by_name({r["full_name"] for r in rsvps}, cursor)
    verified, unverified = [], []
    for rsvp in rsvps:
        student_uuid, method, reason = verify_rsvp(rsvp, candidates.get(rsvp["full_name"], []))
        rsvp.update(student_uuid=student_uuid, match_method=method, reason=reason,
                    status="verified" if student_uuid else "unverified", flags=review_flags(rsvp, method, reason))
        (verified if student_uuid else unverified).append(rsvp)
        if not student_uuid:
            logger.warning(f"UNVERIFIED AGM RSVP {rsvp['uuid']}: {reason}")
    return verified, unverified


def verify_file(csv_file: Path | str, cursor: sqlite3.Cursor, output_dir: Path | str) -> list[dict]:
    """Read an RSVP export, verify it and write agm_verification.csv (private: names and emails) to output_dir."""
    from utsu_core.agm import keep_newest_rsvp, read_rsvps  # agm imports this module, so import it late

    cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'uoft_data'")
    if not cursor.fetchone():
        raise ValueError("The database has no uoft_data table; import the UofT student data first")
    rsvps = keep_newest_rsvp(read_rsvps(Path(csv_file)))
    verified, unverified = verify_rsvps(rsvps, cursor)

    out = Path(absfile(output_dir))
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "agm_verification.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REPORT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rsvps)
    logger.info(f"AGM verification: {len(verified)} verified, {len(unverified)} unverified of {len(rsvps)}; "
                f"report in {out / 'agm_verification.csv'}")
    return rsvps


def main():
    parser = argparse.ArgumentParser(description="Verify AGM voter RSVPs against the UofT student data")
    parser.add_argument("--agm_file", default="", help="AGM voter RSVP export (CSV)")
    parser.add_argument("--db", default="", help="Database holding the uoft_data table")
    parser.add_argument("--output_dir", default="secrets/output", help="Where agm_verification.csv is written")
    parser.add_argument("--testing", action="store_true",
                        help="Use testing/output/fake_agm.csv and the database from the last `main --testing` run")
    args = parser.parse_args()
    if args.testing:
        args.agm_file = args.agm_file or "testing/output/fake_agm.csv"
        args.db = args.db or "testing/output/test.sqlite"
        args.output_dir = "testing/output" if args.output_dir == "secrets/output" else args.output_dir
    if not args.agm_file or not args.db:
        parser.error("--agm_file and --db are required (or use --testing)")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    conn = sqlite3.connect(absfile(args.db))
    try:
        rows = verify_file(absfile(args.agm_file), conn.cursor(), args.output_dir)
    finally:
        conn.close()
    verified = sum(r["status"] == "verified" for r in rows)
    print(f"{verified} verified, {len(rows) - verified} unverified of {len(rows)} RSVPs")


if __name__ == "__main__":
    main()
