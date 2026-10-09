"""
Fake Senate applications shaped like the real form export (testing/fake_senator.csv). Run through
generate_fake_data.py.

Applicants are drawn from testing/fake_uoft_data.csv (generate the student data first), with delegations sized per
division to exercise exact fit, overflow and none. A handful of applications are deliberately unverifiable (wrong
student number, misspelled name, not a student at all), resubmitted, or impossible to seat. The data is deterministic.
"""
import csv
from datetime import datetime, timedelta

from generate_fake_data import DIVISION_NAMES, TESTING, Gen, division_of, email_for, fmt_ts, load_seats, \
    load_students, not_in_roster, student_key, write_csv

OUT = TESTING / "fake_senator.csv"
SEED = "UTSU"

HEADERS_BEFORE_CHOICES = [
    "Timestamp", "Username", "Full ACORN-registered Name", "Student Number", "UofT Email Address", "Divisional Code",
    "Confirmation of Eligibility: I am a current University of Toronto student and a paying member of the UTSU",
    "Are you an delegated applicant?", "Conflict of Interest Disclosure", "Feedback/Comment Card",
]
HEADERS_AFTER_CHOICES = [
    "General Statement",
    "Affiliation Statement: I confirm that I am affiliated with the constituency selected above.",
]

DELEGATE = "Yes, I am one of the confirmed delegates of my constituency."
NOT_DELEGATE = "No, I am applying without an delegation."
CONFLICTS = ["", "N/A", "n/a", "None.", "No conflicts!", "I have nothing to declare.",
             "I sit on a residence council.", "I work part-time for a campus club."]
FEEDBACK = [""] * 12 + ["N/A", "NA", "Thank you for the opportunity to apply!", "Great form!",
                        "How do you get a delegation?"]
STATEMENTS = [
    "I want to help first-year students find their footing.", 
    "I commute a long way each day and know the pain points.",
    "Residence life shapes the student experience and deserves a voice.",
    "As an international student I want better supports on campus.",
    "I am the first in my family to attend university.", 
    "I am a mature student and a parent of two.",
    "Small programs often get overlooked in Senate discussions.",
    "I have experience on multiple student committees.", 
    "Happy to serve in any general capacity.",
    "I believe students should have a stronger say in academic governance.", 
    "",
]
TIERS = ["First-choice", "Second-choice", "Third-choice", "Interested"]
AFFIL = "I confirm my affiliations."


def generate(seed=SEED) -> None:
    g = Gen(seed)
    rng = g.rng
    students = load_students()
    if not students:
        raise SystemExit("No student data to draw applicants from; generate testing/fake_uoft_data.csv first")

    seats = load_seats()
    constituencies = [r["constituency"] for r in seats if r["constituency"] != "Faculty/College"]
    capacity = {r["division"]: int(r["seats"]) for r in seats if r["constituency"] == "Faculty/College"}
    divisions = list(capacity)

    def prefs_for():
        cols = constituencies + ["Faculty/College"]
        values = dict.fromkeys(cols, "None")
        shape = rng.random()
        # most people rank a few constituencies; General Member is a popular fallback
        picks = rng.sample(constituencies, rng.randint(2, 5))
        if shape < 50 / 100 and "General Member" not in picks:
            picks.append("General Member")
        if shape > 85 / 100 and "Faculty/College" not in picks:
            picks.append("Faculty/College")
        tiers = TIERS[:]
        rng.shuffle(picks)
        for i, c in enumerate(picks):
            values[c] = tiers[i] if i < len(tiers) else "Interested"
        if "Faculty/College" not in picks:
            values["Faculty/College"] = rng.choice(["", "None"])
        return [values[c] for c in cols]

    # ---- which students apply, as delegates, etc. -------------------------------------------------
    delegate_plan = {}  # division -> number of delegates; chosen to exercise exact fit, overflow and none
    for d in divisions:
        cap = capacity[d]
        if d in ("DENT", "LAW", "TYP"):
            delegate_plan[d] = 0
        elif d in ("WDW", "TRIN", "APSC"):
            delegate_plan[d] = cap + 1  # more delegates than seats
        elif d in ("MED", "NURS", "PHM"):
            delegate_plan[d] = cap  # exactly full
        else:
            delegate_plan[d] = rng.randint(1, max(1, cap - 1))

    applicants = []  # (student, delegated)
    for d, n in delegate_plan.items():
        pool = [s for s in students if division_of(s) == d]
        if len(pool) < n:
            raise SystemExit(f"{d} has {len(pool)} students but needs {n} delegates; regenerate the student data")
        rng.shuffle(pool)
        applicants += [(s, True) for s in pool[:n]]

    delegate_ids = {student_key(s) for s, _ in applicants}
    non_delegates = [s for s in students if student_key(s) not in delegate_ids]
    rng.shuffle(non_delegates)
    applicants += [(s, False) for s in non_delegates[:72]]

    # ---- rows -------------------------------------------------------------------------------------
    def personal(first, last):
        return f"{first.split()[0].lower()}.{last.lower().replace(' ', '').replace('ó', 'o').replace('č', 'c')}" \
               f"{rng.choice(['', '', str(rng.randint(1, 99))])}@gmail.com"

    headers = [*HEADERS_BEFORE_CHOICES, *(f"Constituency Choice [{c}]" for c in [*constituencies, "Faculty/College"]),
               *HEADERS_AFTER_CHOICES]

    rows = []
    t = datetime(2026, 8, 14, 13, 30, 47) + timedelta(minutes=17)
    numbers = {}

    def build_row(st, delegated, ts, *, name=None, number=None, comment=None):
        division = division_of(st)
        number = number or numbers.setdefault(
            student_key(st), f"10{rng.randint(0, 999):03d}{st['trunc']}{rng.randint(0, 9)}")
        prefs = [""] * 9 if delegated else prefs_for()
        return [fmt_ts(ts), personal(st["first"], st["last"]), name or f"{st['first']} {st['last']}", number,
                email_for(st["first"], st["last"]), f"{division} - {DIVISION_NAMES[division]}",
                "Yes, I confirm my eligibility.", DELEGATE if delegated else NOT_DELEGATE,
                "" if delegated else rng.choice(CONFLICTS),
                comment if comment is not None else ("" if delegated else rng.choice(FEEDBACK)), *prefs,
                "" if delegated else rng.choice(STATEMENTS), "" if delegated else AFFIL]

    order = applicants[:]
    rng.shuffle(order)
    for st, delegated in order:
        t += timedelta(minutes=rng.randint(20, 900), seconds=rng.randint(0, 59))
        rows.append(build_row(st, delegated, t))

    non_delegate_applicants = [a for a in order if not a[1]]

    # unverified: wrong truncated number / misspelled name / not in the student data at all
    for st, _ in rng.sample(non_delegate_applicants, 3):
        t += timedelta(hours=rng.randint(1, 20), seconds=rng.randint(0, 59))
        wrong = f"10{rng.randint(0, 999):03d}{(int(st['trunc']) + 1) % 10000:04d}{rng.randint(0, 9)}"
        rows.append(build_row(st, False, t, number=wrong))
    for st, _ in rng.sample(non_delegate_applicants, 2):
        t += timedelta(hours=rng.randint(1, 20), seconds=rng.randint(0, 59))
        rows.append(build_row(st, False, t, name=f"{st['first'].split()[0]}x {st['last']}"))
    for ghost in not_in_roster(g, len(order), len(students)):
        t += timedelta(hours=rng.randint(1, 20), seconds=rng.randint(0, 59))
        rows.append(build_row(ghost, False, t))

    # resubmissions: a later form from the same student must replace the earlier one
    for st, _ in rng.sample(non_delegate_applicants, 5):
        t += timedelta(hours=rng.randint(2, 40), seconds=rng.randint(0, 59))
        rows.append(build_row(st, False, t, comment="Please ignore my first application form. "
                                                      "This is the final version for my application."))

    # one applicant who rejects every constituency in their final form (can never be seated)
    st, _ = rng.choice(non_delegate_applicants)
    t += timedelta(hours=3)
    row = build_row(st, False, t)
    row[10:19] = ["None"] * 9
    rows.append(row)

    rows.sort(key=lambda r: datetime.strptime(
        r[0].replace("p.m.", "PM").replace("a.m.", "AM").replace(" AST", ""), "%Y/%m/%d %I:%M:%S %p"))
    write_csv(OUT, headers, rows, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    print(f"Wrote {len(rows)} applications to {OUT}")
