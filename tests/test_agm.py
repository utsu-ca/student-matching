import csv
import sqlite3
from pathlib import Path

from utsu_core import agm, agm_verify
from utsu_core.verification import construct_lookup_tables
from utsu_std.utils import absfile

HEADERS = ["Timestamp", "Username", "Preferred Name", "Preferred Pronouns", "ACORN-registered First Name",
           "ACORN-registered Last Name ", "UofT Email Address", "Meeting Preference",
           "Do you have any dietary restrictions or food allergies?", "Accessibility Requirements",
           "Data Processing Confirmation", "Contact Consent"]


def form_csv(path, rows, extra_header=None):
    header = HEADERS + ([extra_header] if extra_header else [])
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def rsvp(ts, first, last, email="", dietary="", confirm="Yes", extra=None, meeting="Online"):
    row = [ts, "p@gmail.com", "", "she/her", first, last, email, meeting, dietary, "", confirm, "Yes"]
    return row + ([extra] if extra is not None else [])


def students_db(*people):
    conn = sqlite3.connect(":memory:")
    conn.executescript(Path(absfile("src/schema/uoft_data.sql")).read_text(encoding="utf-8"))
    for i, (first, last, trunc) in enumerate(people):
        conn.execute("INSERT INTO uoft_data (uuid, trunc_id, first_name, last_name, full_name, division, faculty) "
                     "VALUES (?, ?, ?, ?, ?, 'UC', 'ARTSC')", (f"u{i}", trunc, first, last, f"{first} {last}"))
    conn.commit()
    return conn


def test_lookup_table_matches_the_real_form_headers():
    names = construct_lookup_tables(Path(absfile("data/conversion_table_agm.csv")))[0]
    assert set(names) == {h.strip() for h in HEADERS}


def test_process_agm_verifies_by_name_and_dedupes(tmp_path):
    form = form_csv(tmp_path / "rsvp.csv", [
        rsvp("2026/10/01 9:00:00 a.m. AST", "Ann", "Lee", "ann@mail.utoronto.ca", dietary="Vegan"),
        rsvp("2026/10/02 9:00:00 a.m. AST", "Ann", "Lee", "ann@mail.utoronto.ca", dietary="Halal"),  # newer wins
        rsvp("2026/10/01 10:00:00 a.m. AST", "Bo", "Chan", "bo@mail.utoronto.ca", confirm=""),
        rsvp("2026/10/01 11:00:00 a.m. AST", "Cy", "Doe", "cy@mail.utoronto.ca"),  # not a student
        rsvp("2026/10/01 12:00:00 p.m. AST", "Di", "Park", "di@mail.utoronto.ca"),  # name shared by two students
    ])
    conn = students_db(("Ann", "Lee", 3161), ("Bo", "Chan", 9111), ("Di", "Park", 1111), ("Di", "Park", 2222))
    out = tmp_path / "out"

    result = agm.process_agm(form, conn, output_dir=out)
    assert [r["full_name"] for r in result["verified"]] == ["Ann Lee", "Bo Chan"]
    reasons = {r["full_name"]: r["reason"] for r in result["unverified"]}
    assert reasons == {"Cy Doe": "name not found", "Di Park": "name shared by 2 students; a student number is needed"}
    ann = next(r for r in result["verified"] if r["full_name"] == "Ann Lee")
    assert ann["dietary"] == "Halal" and ann["match_method"] == "name only" and "name_only_match" in ann["flags"]
    bo = next(r for r in result["verified"] if r["full_name"] == "Bo Chan")
    assert "no_data_confirmation" in bo["flags"]

    accommodations = (out / "agm_accommodations.csv").read_text(encoding="utf-8")
    assert "Halal" in accommodations and "Ann" not in accommodations and "ann@" not in accommodations
    assert conn.execute("SELECT status, COUNT(*) FROM agm_rsvp GROUP BY status ORDER BY status").fetchall() \
        == [("unverified", 2), ("verified", 2)]
    # the stored rows carry no names or emails
    assert "Ann" not in str(conn.execute("SELECT * FROM agm_rsvp").fetchall())


def test_everyone_and_in_person_lists(tmp_path):
    form = form_csv(tmp_path / "rsvp.csv", [
        rsvp("2026/10/01 9:00:00 a.m. AST", "Ann", "Lee", "ann@mail.utoronto.ca", meeting="In-person"),
        rsvp("2026/10/01 10:00:00 a.m. AST", "Bo", "Chan", "bo@mail.utoronto.ca", meeting="Online"),
        rsvp("2026/10/01 11:00:00 a.m. AST", "Cy", "Doe", "cy@mail.utoronto.ca", meeting="In-person"),  # unverified
        rsvp("2026/10/01 12:00:00 p.m. AST", "Ed", "Abe", "ed@mail.utoronto.ca", meeting="In person"),
    ])
    conn = students_db(("Ann", "Lee", 3161), ("Bo", "Chan", 9111), ("Ed", "Abe", 1234))
    out = tmp_path / "out"
    result = agm.process_agm(form, conn, output_dir=out)

    def names(file):
        with open(out / file, newline="", encoding="utf-8") as f:
            return [f"{r['first_name']} {r['last_name']}" for r in csv.DictReader(f)]

    assert names("agm_list_all.csv") == ["Ed Abe", "Bo Chan", "Ann Lee"]  # by last name
    assert names("agm_list_in_person.csv") == ["Ed Abe", "Ann Lee"]
    assert result["summary"]["in_person"] == 2 and result["summary"]["unverified"] == 1
    assert [r["full_name"] for r in result["in_person"]] == ["Ed Abe", "Ann Lee"]


def test_in_person_detection():
    assert [agm.is_in_person(v) for v in ("In-person", "in person", "Online", "Virtual", "Hybrid", "")] \
        == [True, True, False, False, False, False]


def test_standalone_verification_only_reports(tmp_path):
    form = form_csv(tmp_path / "rsvp.csv", [
        rsvp("2026/10/01 9:00:00 a.m. AST", "Ann", "Lee", "ann@mail.utoronto.ca"),
        rsvp("2026/10/01 11:00:00 a.m. AST", "Cy", "Doe", "cy@mail.utoronto.ca"),
    ])
    conn = students_db(("Ann", "Lee", 3161))
    rows = agm_verify.verify_file(form, conn.cursor(), tmp_path / "out")
    assert [(r["full_name"], r["status"]) for r in rows] == [("Ann Lee", "verified"), ("Cy Doe", "unverified")]
    with open(tmp_path / "out" / "agm_verification.csv", newline="", encoding="utf-8") as f:
        assert [r["status"] for r in csv.DictReader(f)] == ["verified", "unverified"]
    assert not (tmp_path / "out" / "agm_list_all.csv").exists()
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'agm_rsvp'").fetchone() == (0,)


def test_student_number_column_breaks_name_ties(tmp_path):
    form = form_csv(tmp_path / "rsvp.csv", [
        rsvp("2026/10/01 9:00:00 a.m. AST", "Di", "Park", "di@mail.utoronto.ca", extra="1001232222"),
        rsvp("2026/10/01 9:05:00 a.m. AST", "Di", "Park", "other@mail.utoronto.ca", extra="1001239999"),
    ], extra_header="Student Number")
    # "1001232222" -> truncated 3222; "1001239999" -> 3999
    conn = students_db(("Di", "Park", 1111), ("Di", "Park", 3222))
    result = agm.process_agm(form, conn, output_dir=tmp_path / "out")
    assert [(r["email"], r["match_method"]) for r in result["verified"]] == [("di@mail.utoronto.ca",
                                                                              "name + student number")]
    assert result["unverified"][0]["reason"] == "student number does not match"
