import csv
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from utsu_core.verification import setup_reader, bulk_check_for_students
from utsu_std.utils import absfile, generate_uuid, get_trunc_id, normalize_case

logger = logging.getLogger(__name__)

OUTPUT_FIELDS = ["uuid", "submission_ts", "full_name", "id", "email", "personal_email", "division", "delegated"]
PREF_PREFIX = "pref:"
_PREF_COLUMN = re.compile(r"^\s*Constituency Choice \[(.+)\]\s*$")


def division_code(division: str) -> str:
    """
    The code in a form division such as 'TRIN - Trinity College'.

    >>> division_code("TRIN - Trinity College")
    'TRIN'
    >>> division_code(" uc ")
    'UC'
    """
    return division.split(" - ")[0].strip().upper()


def read_preferences(row: dict[str, str]) -> dict[str, str]:
    """
    Pull the 'Constituency Choice [...]' answers out of a mapped form row. They are not in the lookup table,
    so they keep their original headers.

    >>> read_preferences({"id": "1", "Constituency Choice [Commuter]": " First-choice "})
    {'pref:Commuter': 'First-choice'}
    """
    prefs = {}
    for col, value in row.items():
        if isinstance(col, str) and (m := _PREF_COLUMN.match(col)):
            prefs[PREF_PREFIX + m.group(1)] = (value or "").strip()
    return prefs


def parse_submission_ts(value: str) -> datetime | None:
    """
    Parse a form timestamp such as '2026/08/14 1:30:47 p.m. AST'. The timezone label is ignored.

    >>> parse_submission_ts("2026/08/14 1:30:47 p.m. AST")
    datetime.datetime(2026, 8, 14, 13, 30, 47)
    >>> parse_submission_ts("2026/08/14 12:05:00 a.m. AST")
    datetime.datetime(2026, 8, 14, 0, 5)
    >>> parse_submission_ts("garbage") is None
    True
    """
    m = re.match(r"\s*(\d{4}/\d{2}/\d{2})\s+(\d{1,2}:\d{2}:\d{2})\s*([ap])\.?m\.?", value or "", re.I)
    if not m:
        return None
    date, time, meridiem = m.groups()
    return datetime.strptime(f"{date} {time} {meridiem.upper()}M", "%Y/%m/%d %I:%M:%S %p")


def application_uuid(row: dict[str, str]) -> str:
    """Deterministic id for an application, so re-running on the same form yields the same uuid."""
    return generate_uuid("|".join(row.get(k, "").strip() for k in ("submission_ts", "id", "email")))


def keep_newest(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """
    Keep only the newest application per student (keyed by student number, else email).
    Rows with an unparseable timestamp are ordered by their position in the file.
    """
    newest: dict[str, tuple[tuple, dict[str, str]]] = {}
    for position, row in enumerate(rows):
        key = row.get("id", "").strip() or row.get("email", "").strip().lower()
        rank = (parse_submission_ts(row.get("submission_ts", "")) or datetime.min, position)
        if key not in newest or rank > newest[key][0]:
            newest[key] = (rank, row)
    return [row for _, row in sorted(newest.values(), key=lambda item: item[0][1])]


def _match_key(full_name: str, trunc_id) -> tuple[str, int | str | None]:
    return full_name, int(trunc_id) if str(trunc_id).isdigit() else trunc_id


def write_results(verified: list[dict[str, str]], unverified: list[dict[str, str]], output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    pref_fields = list(dict.fromkeys(
        k for row in (*verified, *unverified) for k in row if k.startswith(PREF_PREFIX)))
    for name, rows in (("verified.csv", verified), ("unverified.csv", unverified)):
        with open(output_dir / name, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS + pref_fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        logger.info(f"Wrote {len(rows)} rows to {output_dir / name}")


def verify_senators(csv_file: Path, cursor: sqlite3.Cursor, log_sample: bool = False,
                    output_dir: Path | str = "secrets/output"):
    """
    Verify senate applications against uoft_data. Only the newest application per student is kept.
    Writes verified.csv and unverified.csv to output_dir (relative paths resolve from the project root).
    """
    if isinstance(csv_file, str):
        csv_file = Path(csv_file)
    senators: csv.DictReader = setup_reader(csv_file, absfile("data/lookup_table_senate.csv"))

    applications = []
    for row in senators:
        app = {k: (row.get(k) or "").strip() for k in OUTPUT_FIELDS if k != "uuid"}
        app["delegated"] = "yes" if app["delegated"].lower().startswith("yes") else "no"
        app.update(read_preferences(row))
        if not app["id"] and not app["full_name"]:
            continue
        app["uuid"] = application_uuid(app)
        applications.append(app)

    current = keep_newest(applications)
    logger.info(f"{len(applications)} applications read; {len(applications) - len(current)} older "
                f"duplicate submissions dropped; {len(current)} to verify")

    non_matched: set = set()
    sample_pending = log_sample
    for start in range(0, len(current), 50):
        batch = current[start:start + 50]
        names = [normalize_case(a["full_name"]) for a in batch]
        trunc_ids = [get_trunc_id(a["id"]) if a["id"] else None for a in batch]
        results = bulk_check_for_students(names, trunc_ids, cursor, log_sample=sample_pending)
        sample_pending = False
        non_matched.update(_match_key(n, t) for n, t in results["non_matches"])

    verified, unverified = [], []
    for app in current:
        trunc = get_trunc_id(app["id"]) if app["id"] else None
        key = _match_key(normalize_case(app["full_name"]), trunc)
        if key in non_matched:
            unverified.append(app)
            logger.warning(f"UNVERIFIED application {app['uuid']}")
        else:
            verified.append(app)
            logger.info(f"VERIFIED application {app['uuid']}")

    write_results(verified, unverified, Path(absfile(output_dir)))
    return {"verified": verified, "unverified": unverified}


