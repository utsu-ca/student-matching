"""
Student Aid Bursary Program (SABP) application processor.

Stage 1-3 of the SOP: read the form export, keep each student's newest application, verify them against
uoft_data, score the Weighted Financial Need Index (WFNI), record every application in the student_aid table, and
cut the verified ones into anonymized batches of general statements for the committee to review.
"""
import csv
import json
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from utsu_core.senate import keep_newest, parse_submission_ts
from utsu_core.verification import bulk_check_for_students, setup_reader
from utsu_std.utils import absfile, generate_uuid, get_trunc_id, normalize_case

logger = logging.getLogger(__name__)

LC, AP = "LC", "AP"
STREAM_NAMES = {LC: "Living-costs Bursary", AP: "Academic Pursuits Bursary"}
# Largest request per term: LABs are $1,500 plus up to $1,000 of Emergency Bursary; APRs are $1,500.
MAX_REQUEST = {LC: 2500, AP: 1500}
INSTANT_APPROVAL_BELOW = 150

MASTER_FIELDS = ["uuid", "status", "student_uuid", "submission_ts", "terms", "id", "full_name", "email", "faculty",
                 "stream", "subsidies", "requested_amount", "wfni", "emergency", "flags", "batch", "record"]
REVIEW_FIELDS = ["record_id", "uuid", "stream", "subsidies", "requested_amount", "wfni", "emergency",
                 "general_statement", "need_level", "notes"]

# ---- WFNI weights (SAS-002 "Financial Need Index Weights") ---------------------------------------------------
# Option text is normalized by _norm() before lookup, so spacing, case and "to" vs "-" do not matter.
DISABILITY = {"yes": 2, "no": 0}
HOUSING = {"stablyhoused": 0, "precariouslyhoused": 1, "imminentriskoflosinghousing": 4,
           "emergencysheltered": 4, "unsheltered": 6}
DISPOSABLE_INCOME = {"anegativeamount": 5, "lessthan$100": 4, "$100-200": 3, "$200-500": 2, "$500-1000": 0,
                     "$1000+": -3}
LIQUIDITY = {"$0-$500": 3, "$500-$1000": 1, "$1000-$2500": 0, "$2500-$5000": -1, "$5000-$7500": -2,
             "$7500-$10,000": -3, "$10,000+": -5}
DEPENDENTS = {"0": 0, "1": 1, "2": 2, "3": 3, "4+": 4}
EXTERNAL_SUPPORTS = {"yes": 0, "no": 1}
CIRCUMSTANCE_POINTS, CIRCUMSTANCE_CAP = 3, 10
MAX_WFNI = 2 + 2 + 6 + 5 + 3 + CIRCUMSTANCE_CAP + 4 + 1
# Policy: "trust but verify when point totals represent a majority of the point scale".
HIGH_WFNI = MAX_WFNI // 2 + 1


def _norm(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").lower().replace(" to ", "-"))


def _points(table: dict[str, int], value: str) -> int | None:
    """Points for an answer, or None when it is not a known option (the long 'negative amount' option matches by prefix)."""
    key = _norm(value)
    if key in table:
        return table[key]
    return next((p for k, p in table.items() if key.startswith(k)), None)


def split_multi(value: str) -> list[str]:
    """
    Split a ';' separated multi-select answer.

    >>> split_multi("A; B;;C ")
    ['A', 'B', 'C']
    """
    return [part.strip() for part in (value or "").split(";") if part.strip()]


def parse_amount(value: str) -> float | None:
    """
    >>> parse_amount("$1,500")
    1500.0
    >>> parse_amount("706.77")
    706.77
    >>> parse_amount("abc") is None
    True
    """
    try:
        return float(re.sub(r"[$,\s]", "", value or ""))
    except ValueError:
        return None


def compute_wfni(app: dict[str, str]) -> tuple[int | None, list[str]]:
    """
    Weighted Financial Need Index from the questionnaire. Only the living-costs stream answers it, so other
    applications get None. Returns (score, names of answers that were blank or not a known option).

    >>> compute_wfni({"disability_mobility": "Yes", "disability_invisible": "No", "living_situation": "Stably Housed",
    ...               "disposable_income": "Less than $100", "liquidity": "$0 to $500", "dependents": "1",
    ...               "external_supports": "No", "circumstances": "Racial Violence;Recent estrangement"})
    (17, [])
    """
    if not any(app.get(k) for k in ("living_situation", "disposable_income", "liquidity")):
        return None, []
    total, unknown = 0, []
    for field, table in (("disability_mobility", DISABILITY), ("disability_invisible", DISABILITY),
                         ("living_situation", HOUSING), ("disposable_income", DISPOSABLE_INCOME),
                         ("liquidity", LIQUIDITY), ("dependents", DEPENDENTS),
                         ("external_supports", EXTERNAL_SUPPORTS)):
        points = _points(table, app.get(field, ""))
        if points is None:
            unknown.append(field)
        else:
            total += points
    circumstances = [c for c in split_multi(app.get("circumstances", "")) if c.lower() not in ("n/a", "na", "none")]
    total += min(CIRCUMSTANCE_CAP, CIRCUMSTANCE_POINTS * len(circumstances))
    return total, unknown


def redact(text: str, names: list[str] = ()) -> str:
    """
    Remove contact details, student numbers, postal codes, links and the applicant's own name from free text.

    >>> redact("Hi, I'm Ann Lee (ann@mail.utoronto.ca, 416-555-0100, 1001231617). See https://x.co/a", ["Ann", "Lee"])
    "Hi, I'm [name] [name] ([email], [phone], [student number]). See [link]"
    """
    text = re.sub(r"https?://\S+", "[link]", text or "")
    text = re.sub(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "[email]", text)
    text = re.sub(r"(?<!\d)\d{9,10}(?!\d)", "[student number]", text)
    text = re.sub(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)", "[phone]", text)
    text = re.sub(r"\b[A-Za-z]\d[A-Za-z][\s-]?\d[A-Za-z]\d\b", "[postal code]", text)
    for name in {n for part in names for n in re.split(r"\s+", part) if len(n) >= 3}:
        text = re.sub(rf"\b{re.escape(name)}\b", "[name]", text, flags=re.I)
    return text


def sap_uuid(app: dict[str, str]) -> str:
    """Deterministic id for an application, so reprocessing the same form yields the same uuid."""
    return generate_uuid("sap|" + "|".join(app.get(k, "").strip() for k in ("submission_ts", "id", "email")))


def build_application(row: dict[str, str]) -> dict:
    """Turn one mapped form row into an application: cleaned fields, stream, amount, WFNI and review flags."""
    app = {k: (v or "").strip() for k, v in row.items() if isinstance(k, str)}
    app["full_name"] = normalize_case(f"{app.get('first_name', '')} {app.get('last_name', '')}")
    bursary = app.get("bursary_type", "").lower()
    app["stream"] = LC if bursary.startswith("living") else AP if bursary.startswith("academic") else ""
    prefix = app["stream"].lower()
    app["subsidies"] = "; ".join(split_multi(app.get(f"{prefix}_subsidies", "")))
    app["statement"] = app.get(f"{prefix}_statement", "")
    amount = parse_amount(app.get(f"{prefix}_amount", ""))
    app["requested_amount"] = "" if amount is None else f"{amount:g}"
    app["emergency"] = int(any("emergency bursary" in s.lower() for s in split_multi(app.get("lc_subsidies", ""))))
    app["faculty"] = app.get("faculty", "").split(" - ")[0].strip()
    app["uuid"] = sap_uuid(app)

    wfni, unknown = compute_wfni(app)
    app["wfni"] = "" if wfni is None else wfni
    flags = []
    if app.get("member_confirmed", "").lower() != "yes":
        flags.append("membership_not_confirmed")
    if not app["stream"]:
        flags.append("unknown_bursary_type")
    if amount is None:
        flags.append("no_amount")
    elif app["stream"] in MAX_REQUEST and amount > MAX_REQUEST[app["stream"]]:
        flags.append("amount_over_max")
    elif amount < INSTANT_APPROVAL_BELOW:
        flags.append("instant_approval_eligible")
    if not app["statement"]:
        flags.append("no_statement")
    if unknown:
        flags.append("wfni_incomplete")
    if wfni is not None and wfni >= HIGH_WFNI:
        flags.append("high_wfni")
    app["flags"] = ";".join(flags)
    return app


def read_applications(csv_file: Path) -> list[dict]:
    reader = setup_reader(csv_file, absfile("data/conversion_table_sap.csv"))
    applications = [build_application(row) for row in reader]
    return [a for a in applications if a.get("id") or a["full_name"]]


def verify_applications(applications: list[dict], cursor: sqlite3.Cursor) -> dict[tuple, str]:
    """Match applications to uoft_data by (name, truncated number). Returns {(name, trunc): uoft_data.uuid}."""
    matched: dict[tuple, str] = {}
    for start in range(0, len(applications), 50):
        batch = applications[start:start + 50]
        names = [a["full_name"] for a in batch]
        trunc_ids = [get_trunc_id(a["id"]) if a.get("id") else None for a in batch]
        result = bulk_check_for_students(names, trunc_ids, cursor)
        # matches are uoft_data rows: (uuid, trunc_id, first_name, last_name, full_name, ...)
        matched.update({(row[4], row[1]): row[0] for row in result["matches"]})
    return matched


def _match_key(app: dict) -> tuple[str, int | str | None]:
    trunc = get_trunc_id(app["id"]) if app.get("id") else None
    return app["full_name"], int(trunc) if str(trunc).isdigit() else trunc


def assign_batches(verified: list[dict], batch_size: int = 50) -> list[list[dict]]:
    """
    Cut verified applications into batches of at most `batch_size`, oldest submission first so that batches
    already handed out keep their contents as new applications arrive. Sets each application's batch and record.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    ordered = sorted(verified, key=lambda a: (parse_submission_ts(a.get("submission_ts", "")) or datetime.min,
                                              a["uuid"]))
    batches = [ordered[i:i + batch_size] for i in range(0, len(ordered), batch_size)]
    for number, batch in enumerate(batches, start=1):
        for record, app in enumerate(batch, start=1):
            app["batch"], app["record"] = number, record
    return batches


def review_row(app: dict) -> dict:
    """The anonymized view the committee sees: no name, student number, contact details or faculty."""
    names = [app.get("first_name", ""), app.get("last_name", "")]
    return {
        "record_id": f"B{app['batch']:03d}-{app['record']:02d}",
        "uuid": app["uuid"],
        "stream": STREAM_NAMES.get(app["stream"], ""),
        "subsidies": redact(app["subsidies"], names),
        "requested_amount": app["requested_amount"],
        "wfni": app["wfni"],
        "emergency": "yes" if app["emergency"] else "",
        "general_statement": redact(app["statement"], names) or "(no statement provided)",
        "need_level": "",
        "notes": "",
    }


REVIEWERS_PER_BATCH = 2
RATING_LEVELS = range(6)
# General Statement Rubric: recommended maximum per need level (SAS-002).
RUBRIC_AMOUNT = {0: 0, 1: 125, 2: 300, 3: 650, 4: 900, 5: 1500}
# Two reviewers whose levels are this far apart (or more) must discuss the application.
DISCUSS_SPREAD = 2
MERGED_FIELDS = ["uuid", "record_id", "stream", "requested_amount", "wfni", "emergency", "reviewers", "ratings",
                 "n_ratings", "mean_level", "spread", "suggested_amount", "status", "notes"]


def reviewer_id(name: str) -> str:
    """
    A reviewer's name as used in folder names and the database.

    >>> reviewer_id(" Ann  Lee ")
    'Ann_Lee'
    """
    return re.sub(r"[^\w.-]+", "_", name.strip()).strip("_")


def parse_reviewers(value) -> list[str]:
    """
    Reviewer names from a comma separated string or a list, without blanks or duplicates.

    >>> parse_reviewers("Ann, Bo,,Ann")
    ['Ann', 'Bo']
    """
    parts = value.split(",") if isinstance(value, str) else (value or [])
    return list(dict.fromkeys(r for r in (reviewer_id(str(p)) for p in parts) if r))


def ensure_schema(conn: sqlite3.Connection):
    conn.executescript(Path(absfile("src/schema/student_aid.sql")).read_text(encoding="utf-8"))


def assign_reviewers(conn: sqlite3.Connection, n_batches: int, reviewers: list[str]) -> dict[int, list[str]]:
    """
    Two reviewers per batch, saved in sap_batch_reviewer. Batches that already have reviewers keep them; new
    batches go to the two reviewers with the fewest batches so far (ties in the order given), so the workload
    stays even.
    """
    if len(reviewers) < REVIEWERS_PER_BATCH:
        raise ValueError(f"Need at least {REVIEWERS_PER_BATCH} reviewers, got {len(reviewers)}: {reviewers}")
    ensure_schema(conn)
    assigned: dict[int, list[str]] = {}
    for batch, reviewer in conn.execute("SELECT batch, reviewer FROM sap_batch_reviewer ORDER BY batch, reviewer"):
        assigned.setdefault(batch, []).append(reviewer)
    load = {r: sum(r in rs for rs in assigned.values()) for r in reviewers}
    for batch in range(1, n_batches + 1):
        if batch in assigned:
            continue
        picked = sorted(reviewers, key=lambda r: (load[r], reviewers.index(r)))[:REVIEWERS_PER_BATCH]
        for r in picked:
            load[r] += 1
            conn.execute("INSERT INTO sap_batch_reviewer (batch, reviewer) VALUES (?, ?)", (batch, r))
        assigned[batch] = sorted(picked)
    conn.commit()
    return {b: rs for b, rs in assigned.items() if b <= n_batches}


def _write_sheet(rows: list[dict], number: int, directory: Path, reviewer: str | None = None):
    """batch_NNN.csv (to fill in) and batch_NNN.txt (to read) for one batch."""
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / f"batch_{number:03d}.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    title = f"BATCH {number:03d}" + (f"  |  reviewer: {reviewer}" if reviewer else "")
    lines = [f"{title}  |  {len(rows)} applications  |  score each 0-5 against the General Statement Rubric", ""]
    for r in rows:
        lines += [f"[{r['record_id']}]  {r['stream']}  |  requested ${r['requested_amount']}  |  WFNI "
                  f"{r['wfni'] if r['wfni'] != '' else 'n/a'}" + ("  |  EMERGENCY" if r["emergency"] else ""),
                  f"Subsidies: {r['subsidies'] or 'n/a'}", "Statement:", r["general_statement"], "",
                  "Need level (0-5): ____    Notes:", "-" * 78, ""]
    (directory / f"batch_{number:03d}.txt").write_text("\n".join(lines), encoding="utf-8")


def _sheet_uuids(path: Path) -> set[str]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {row.get("uuid", "") for row in csv.DictReader(f)}


def write_batches(batches: list[list[dict]], batch_dir: Path, assignments: dict[int, list[str]] | None = None):
    """
    Write blank batch_NNN.{csv,txt} per batch (replacing older ones) and, for assigned reviewers, a copy in
    by_reviewer/<reviewer>/. A reviewer's existing sheet is never overwritten, since it may hold their ratings.
    """
    batch_dir.mkdir(parents=True, exist_ok=True)
    for old in (*batch_dir.glob("batch_*.csv"), *batch_dir.glob("batch_*.txt")):
        old.unlink()
    for number, batch in enumerate(batches, start=1):
        rows = [review_row(a) for a in batch]
        _write_sheet(rows, number, batch_dir)
        for reviewer in (assignments or {}).get(number, []):
            folder = batch_dir / "by_reviewer" / reviewer
            existing = folder / f"batch_{number:03d}.csv"
            if not existing.exists():
                _write_sheet(rows, number, folder, reviewer)
            elif _sheet_uuids(existing) != {r["uuid"] for r in rows}:
                logger.warning(f"{existing} no longer matches batch {number} (applications were added or "
                               f"changed); left untouched")
    logger.info(f"Wrote {len(batches)} review batch(es) to {batch_dir}")


def merge_reviews(conn: sqlite3.Connection, output_dir: Path | str = "secrets/output") -> dict:
    """
    Merge the completed reviewer sheets in <output_dir>/sap_batches/by_reviewer/*/ into sap_merged_ratings.csv and
    the sap_review table. Per application: who rated it, each level, the mean, the spread, a suggested amount
    (the mean of the rubric maximums, capped at the requested amount) and a status:
    agreed | discuss (levels differ by 2 or more) | incomplete (one rating) | unrated.
    """
    out = Path(absfile(output_dir))
    batch_dir = out / "sap_batches"
    with open(out / "sap_verified.csv", newline="", encoding="utf-8") as f:
        applications = {row["uuid"]: row for row in csv.DictReader(f)}
    ensure_schema(conn)

    ratings: dict[str, dict[str, tuple[int, str]]] = {}
    problems: list[str] = []
    for sheet in sorted(batch_dir.glob("by_reviewer/*/batch_*.csv")):
        reviewer = sheet.parent.name
        with open(sheet, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                uuid, raw = row.get("uuid", ""), (row.get("need_level") or "").strip()
                if uuid not in applications:
                    problems.append(f"{reviewer}: {sheet.name} has an unknown application {uuid!r}")
                elif raw:
                    try:
                        level = int(float(raw))
                        if level not in RATING_LEVELS or level != float(raw):
                            raise ValueError
                    except ValueError:
                        problems.append(f"{reviewer}: {row.get('record_id')} has an invalid need level {raw!r}")
                        continue
                    ratings.setdefault(uuid, {})[reviewer] = (level, (row.get("notes") or "").strip())

    assigned: dict[int, list[str]] = {}
    for batch, reviewer in conn.execute("SELECT batch, reviewer FROM sap_batch_reviewer"):
        assigned.setdefault(batch, []).append(reviewer)

    rows = []
    for uuid, app in sorted(applications.items(), key=lambda kv: (int(kv[1]["batch"]), int(kv[1]["record"]))):
        given = ratings.get(uuid, {})
        levels = [level for level, _ in given.values()]
        spread = max(levels) - min(levels) if levels else ""
        mean = sum(levels) / len(levels) if levels else ""
        suggested = ""
        if levels:
            suggested = sum(RUBRIC_AMOUNT[v] for v in levels) / len(levels)
            if app["requested_amount"]:
                suggested = min(suggested, float(app["requested_amount"]))
        status = ("unrated" if not levels else "incomplete" if len(levels) < REVIEWERS_PER_BATCH
                  else "discuss" if spread >= DISCUSS_SPREAD else "agreed")
        rows.append({
            "uuid": uuid, "record_id": f"B{int(app['batch']):03d}-{int(app['record']):02d}", "stream": app["stream"],
            "requested_amount": app["requested_amount"], "wfni": app["wfni"], "emergency": app["emergency"],
            "reviewers": "; ".join(sorted(assigned.get(int(app["batch"]), given))),
            "ratings": "; ".join(f"{r}={level}" for r, (level, _) in sorted(given.items())),
            "n_ratings": len(levels), "mean_level": "" if mean == "" else f"{mean:g}", "spread": spread,
            "suggested_amount": "" if suggested == "" else f"{suggested:g}", "status": status,
            "notes": " | ".join(f"{r}: {note}" for r, (_, note) in sorted(given.items()) if note)})
    with open(out / "sap_merged_ratings.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=MERGED_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    conn.executemany("INSERT OR REPLACE INTO sap_review (uuid, reviewer, need_level, notes) VALUES (?, ?, ?, ?)",
                     [(u, r, level, note) for u, given in ratings.items() for r, (level, note) in given.items()])
    conn.commit()

    counts = {s: sum(r["status"] == s for r in rows) for s in ("agreed", "discuss", "incomplete", "unrated")}
    for problem in problems:
        logger.warning(problem)
    logger.info(f"Merged ratings for {len(rows)} applications: {counts}")
    return {"rows": rows, "counts": counts, "problems": problems}


_UPSERT = """
INSERT INTO student_aid (uuid, student_uuid, student_number, submission_ts, terms, status, aid_type,
                         requested_amount, wfni, emergency, flags, batch, record)
VALUES (:uuid, :student_uuid, :id, :submission_ts, :terms, :status, :stream, :requested_amount, :wfni,
        :emergency, :flags, :batch, :record)
ON CONFLICT(uuid) DO UPDATE SET student_uuid = excluded.student_uuid, status = excluded.status,
    aid_type = excluded.aid_type, requested_amount = excluded.requested_amount, wfni = excluded.wfni,
    emergency = excluded.emergency, flags = excluded.flags, batch = excluded.batch, record = excluded.record
"""


def save_to_db(conn: sqlite3.Connection, applications: list[dict]):
    """Add (or refresh) one student_aid row per application. Committee decisions already stored are kept."""
    ensure_schema(conn)
    rows = [{**a, "requested_amount": float(a["requested_amount"]) if a["requested_amount"] != "" else None,
             "wfni": a["wfni"] if a["wfni"] != "" else None, "batch": a.get("batch"), "record": a.get("record"),
             "student_uuid": a.get("student_uuid")} for a in applications]
    conn.executemany(_UPSERT, rows)
    conn.commit()
    logger.info(f"Saved {len(rows)} application row(s) to student_aid")


def write_master(applications: list[dict], path: Path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MASTER_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(applications)
    logger.info(f"Wrote {len(applications)} rows to {path}")


def process_sap(csv_file: Path | str, conn: sqlite3.Connection, output_dir: Path | str = "secrets/output",
                batch_size: int = 50, reviewers=()) -> dict:
    """
    Process a SABP form export. Writes sap_verified.csv and sap_unverified.csv (private, with names and contact
    details) and sap_batches/batch_NNN.{csv,txt} (anonymized, for the committee) under output_dir, and records
    every application in the student_aid table. With `reviewers` (two or more names), each batch is also assigned
    to two of them and copied to sap_batches/by_reviewer/<name>/ for them to fill in; see merge_reviews.
    """
    reviewers = parse_reviewers(reviewers)
    csv_file = Path(csv_file)
    out = Path(absfile(output_dir))
    out.mkdir(parents=True, exist_ok=True)

    applications = read_applications(csv_file)
    current = keep_newest(applications)
    logger.info(f"{len(applications)} SABP applications read; {len(applications) - len(current)} older duplicate "
                f"submissions dropped; {len(current)} to verify")

    matched = verify_applications(current, conn.cursor())
    verified, unverified = [], []
    for app in current:
        student_uuid = matched.get(_match_key(app))
        app["student_uuid"], app["status"] = student_uuid, "verified" if student_uuid else "unverified"
        (verified if student_uuid else unverified).append(app)
        if not student_uuid:
            logger.warning(f"UNVERIFIED SABP application {app['uuid']}")

    batches = assign_batches(verified, batch_size)
    save_to_db(conn, current)
    assignments = assign_reviewers(conn, len(batches), reviewers) if reviewers else {}
    write_master(verified, out / "sap_verified.csv")
    write_master(unverified, out / "sap_unverified.csv")
    write_batches(batches, out / "sap_batches", assignments)

    summary = {"applications": len(current), "verified": len(verified), "unverified": len(unverified),
               "batches": len(batches), "batch_size": batch_size,
               "reviewers": {str(b): rs for b, rs in assignments.items()},
               "emergency": sum(a["emergency"] for a in verified),
               "flags": {flag: sum(flag in a["flags"].split(";") for a in current)
                         for flag in sorted({f for a in current for f in a["flags"].split(";") if f})}}
    (out / "sap_run.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info(f"SABP: {len(verified)} verified, {len(unverified)} unverified, {len(batches)} batch(es) "
                f"of up to {batch_size}")
    return {"verified": verified, "unverified": unverified, "batches": batches, "assignments": assignments,
            "summary": summary}


if __name__ == "__main__":
    import doctest
    doctest.testmod()
