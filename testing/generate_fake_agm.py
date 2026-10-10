"""
Fake AGM voter RSVPs. Run through generate_fake_data.py.

Most RSVPs are drawn from testing/output/fake_uoft_data.csv so they verify; a few have a misspelled or unknown name, about 2%
of people RSVP twice, and pronouns can be several sets ("they/them;it/its") or "Any". The meeting-preference, dietary
and accessibility options are placeholders (the real form's wording is not known).
"""
from datetime import datetime, timedelta

from generate_fake_data import DEFAULT_SEED, OUTPUT_DIR, Gen, email_for, fmt_ts, load_students, slug, student_name, \
    write_csv

OUT = OUTPUT_DIR / "fake_agm.csv"

HEADERS = ["Timestamp", "Username", "Preferred Name", "Preferred Pronouns", "ACORN-registered First Name",
           "ACORN-registered Last Name ", "UofT Email Address", "Meeting Preference",
           "Do you have any dietary restrictions or food allergies?", "Accessibility Requirements",
           "Data Processing Confirmation", "Contact Consent"]
# Counts read off the real RSVP export. Several sets are joined with ";" (e.g. "they/them;it/its"), and a few
# people just answer "Any".
PRONOUNS = [("she/her", 183), ("he/him", 121), ("they/them", 30), ("it/its", 4), ("ze/zir", 2)]
PRONOUN_COUNT = [(1, 92), (2, 7), (3, 1)]
PRONOUN_ANY_PERCENT = 0.6
DOUBLE_REGISTRATION_PERCENT = 2
MEETING = ["Yes, I'll be attending in-person.", "No, I will be attending virtually."]
DIETARY = ["Vegetarian", "Vegan", "Halal", "Gluten-free", "Peanut allergy", "Kosher"]
ACCESSIBILITY = ["Wheelchair-accessible seating", "Captioning", "Quiet space", "Large-print materials"]
DATA_PROCESSING_CONFIRMATION = "I confirm and understand how my data will be processed."
CONTACT_CONSENT = ["Yes, please send me reminder emails.", "No, do not send me a reminder."]


def generate(rows: int = 60, seed: int | str = DEFAULT_SEED) -> None:
    g = Gen(seed)
    rng = g.rng
    students = load_students()
    pool = [(s["first"], s["last"]) for s in students]
    rng.shuffle(pool)
    people = pool[:rows]
    # not in the student data (numbered after everyone who is): stays unverified
    people += [student_name(len(students) + i) for i in range(rows - len(people))]

    people = [(f, l + "x") if g.chance(4 / 100) else (f, l) for f, l in people]  # misspelled
    # about 2% register twice (at least one, so small runs still exercise it); the later form replaces the earlier
    people += rng.sample(people, k=max(1, round(len(people) * DOUBLE_REGISTRATION_PERCENT / 100)))

    start = datetime(2026, 10, 1, 8, 0, 0)
    stamps = sorted(start + timedelta(seconds=rng.randrange(14 * 86400)) for _ in people)
    out_rows = []
    for (first, last), ts in zip(people, stamps):
        out_rows.append([
            fmt_ts(ts), 
            f"{slug(first)}{rng.randint(1, 99)}@gmail.com",
            first.split()[0] if g.chance(15 / 100) else "", 
            ";".join(["Any"] if g.chance(PRONOUN_ANY_PERCENT / 100) else g.multi(PRONOUNS, g.pick(PRONOUN_COUNT))),
            first, 
            last,
            email_for(first, last),
            rng.choice(MEETING), 
            rng.choice(DIETARY) if g.chance(15 / 100) else "",
            rng.choice(ACCESSIBILITY) if g.chance(6 / 100) else "",
            DATA_PROCESSING_CONFIRMATION, 
            rng.choice(CONTACT_CONSENT)
        ])

    write_csv(OUT, HEADERS, out_rows)
    print(f"Wrote {len(out_rows)} RSVPs to {OUT}")
