"""
Fake Student Aid Bursary Program (SABP) applications shaped like the real form export (testing/fake_sabp.csv).
Run through generate_fake_data.py.

Applicants are drawn from testing/fake_uoft_data.csv (so name + truncated student number verify against it), which is
sized when it is generated: SABP only reads it and needs about as many students as applications. About 2% of
applicants are not in it at all, so they never verify.
"""
from datetime import datetime, timedelta

from generate_fake_data import DEFAULT_SEED, TESTING, Gen, email_for, fmt_ts, load_students, not_in_roster, write_csv

OUT = TESTING / "fake_sabp.csv"

HEADERS = [
    "Timestamp", "Application Semester", "Confirmation of UTSU Membership", "ACORN-registered First Name",
    "ACORN-registered Last Name", "Student Number", "UofT Email Address", "Phone Number", "Faculty ",
    "PEY Co-op Status", "Bursary Type", "AP General Statement", "AP Subsidies", "AP Request Amount",
    "AP Additional Information", "LC General Statement", "LC Subsidies", "LC Requested Amount",
    "Postal Code - TMS", "Disability Status - Mobility", "Disability Status - Invisible", "Living Situation",
    "Access to Disposable Income", "Liquidity", "Number of Dependents and/or Remittance members",
    "Access to External Supports", "Extenuating Circumstances", "LC - Additional Information", "Attestation",
    "Name of Institution", "Institution Number (3 digits)", "Transit Number (5 digits)", "Account Number",
    "Tuition Status", "Government Student-Aid Status", "Gender", "Age", "Race", "Commute Time", "Job Hours",
    "Urban", "Referral Avenue", "Contact Consent", "Research Invitation",
    "Do you have any feedback you would like to provide?",
]

# (option, weight).
FACULTIES = {
    "ARTSC": ("ARTSC - Faculty of Arts & Science", 353),
    "APSC": ("APSC - Faculty of Applied Science & Engineering", 67),
    "PHM": ("PHM - Leslie Dan Faculty of Pharmacy", 46),
    "NURS": ("NURS - Lawrence Bloomberg Faculty of Nursing", 30),
    "MED": ("MED - Temerty Faculty of Medicine", 29),
    "DENT": ("DENT - Faculty of Dentistry", 20),
    "FPEH": ("FPEH - Faculty of Kinesiology & Physical Education", 19),
    "TST": ("TST - Toronto School of Theology", 17),
    "ARCLA": ("ARCLA - John H. Daniels Faculty of Architecture, Landscape, and Design", 6),
    "FIS": ("FIS - Faculty of Information", 6),
    "TYP": ("TYP - Transitional Year Programme", 5),
    "MUSIC": ("MUSIC - Faculty of Music", 3),
    "LAW": ("LAW - Henry N.R. Jackman Faculty of Law", 2),
}
SEMESTERS = [("Fall 2026;Winter 2027", 532), ("Fall 2026", 66), ("Winter 2027", 4), ("", 1)]
BURSARY_LC = "Living-costs Bursary (long-form)"
BURSARY_AP = "Academic Pursuits Bursary (short-form)"
AP_SUBSIDIES = [("Mandatory Placement Stipend (~$500/term)", 51), ("Conference Reimbursement (~$350/term)", 42),
                ("Exam Deferral Subsidy (~$150/term)", 25),
                ("Professional Faculties Summer Gym Access Subsidy (TBD)", 19)]
AP_AMOUNTS = [("1500", 19), ("500", 15), ("350", 9), ("1000", 9), ("850", 6), ("150", 5), ("1200", 3), ("700", 2),
              ("600", 2), ("706.77", 1), ("215", 1), ("76.5", 1), ("735", 1), ("750", 1), ("420", 1), ("200", 1)]
LC_SUBSIDIES = [("Transit Mobility Subsidy (up-to $500/term)", 456), ("Healthy Living Subsidy (up-to $150/term)", 400),
                ("Emergency Bursary (expedited processing)", 257)]
LC_AMOUNTS = [("1500", 255), ("500", 55), ("1000", 44), ("2500", 33), ("650", 26), ("800", 25), ("1300", 15),
              ("300", 13), ("600", 7), ("1200", 5)]
LIVING = [("Stably Housed", 396), ("Precariously Housed", 67), ("Imminent risk of losing housing", 63)]
DISPOSABLE = [("A negative amount (taking on short-term debt to satisfy necessities)", 156), ("Less than $100", 116),
              ("$100-200", 106), ("$200-500", 61), ("$500-1000", 44), ("$1000+", 43)]
LIQUIDITY = [("$0 to $500", 268), ("$500 to $1000", 96), ("$1000 to $2500", 72), ("$2500 to $5000", 45),
             ("$5000 to $7500", 20), ("$7500 to $10,000", 13), ("$10,000+", 12)]
DEPENDENTS = [("0", 463), ("1", 33), ("2", 14), ("3", 11), ("4+", 5)]
EXTENUATING = [("Reduction in available hours at job", 147), ("Lost your job and/or main source of income", 136),
               ("Gone hungry due to a lack of funds", 116), ("Recent new disability", 54), ("Racial Violence", 38),
               ("Recent estrangement", 32), ("Survivor of Interpersonal Violence", 23),
               ("Identity Theft and or Fraud", 20), ("Immigration and/or Status Issues", 20)]
EXTENUATING_FREE = ["Unexpected dental expenses", "Unable to find a job", "High out-of-pocket medical expenses",
                    "Parent lost main source of income", "Recent relocation and high living expenses", "n/a"]
EXTENUATING_COUNT = [(0, 160), (1, 177), (2, 117), (3, 49), (4, 14), (5, 8), (6, 1)]
TUITION = [("Domestic (Ontario-resident)", 458), ("International", 65), ("Domestic (non-Ontario resident)", 59)]
GOV_AID = [("Yes, but the amount I received is too low to sustain myself.", 368),
           ("No, I am ineligible for aid due to status reasons.", 71),
           ("Yes, the amount I received covers my costs, but an unexpected situation has arisen, "
            "and it no longer meets my needs.", 50),
           ("No, I have yet to apply.", 38), ("Yes, the amount I received covers all my costs.", 27),
           ("No, my parents' income excludes me from receiving aid.", 18)]
GENDER = [("Woman", 335), ("Man", 185), ("Prefer not to answer", 31), ("Queer", 27), ("Non-binary", 12),
          ("Genderfluid", 8), ("Transgender", 2)]
AGE = [("18 to 24", 451), ("25 to 34", 93), ("35 to 44", 15), ("45 to 54", 8), ("Prefer not to answer", 7),
       ("55 to 64", 1)]
RACE = [("East Asian (e.g., Chinese, Korean, Japanese, Taiwanese)", 148),
        ("South Asian (e.g., Indian, Pakistani, Sri Lankan)", 136),
        ("Middle Eastern (e.g. Arab, Persian, West Asian descent)", 83), ("White (e.g., European descent)", 81),
        ("Black (e.g., African, African Canadian, Afro-Caribbean descent)", 62),
        ("Southeast Asian (e.g., Vietnamese, Cambodian, Laotian, Thai)", 45),
        ("Latin American (e.g., Bangladeshi, Indian, Indo-Caribbean, Pakistani, Sri Lankan)", 28),
        ("Prefer not to answer", 27), ("Indigenous (e.g. First Nations, Inuk/Inuit, Métis)", 7)]
URBAN = [("Suburban (northern scarborough)", 177), ("General Urban (midtown / transitional region)", 161),
         ("Urban (kensington market)", 97), ("Core Urban (financial core)", 52),
         ("Exurban (markham 14th street)", 29), ("Rural (barrie)", 20)]
REFERRAL = [("UTSU Newsletter", 164), ("UTSU Website", 128), ("Social Media", 110), ("Online/Research", 86),
            ("Financial/Academic/Accessibility Advisor", 69), ("Word of Mouth", 63), ("Previous Applicant", 54),
            ("Quercus/ACORN", 48), ("UofT Event/Website/Communication", 45), ("Faculty", 41),
            ("UTSU Event (Club's Fair/Orientation)", 33), ("Family", 10)]
RESEARCH = [("No.", 264), ("Yes, I would like to hear of any UTSU-led studies.", 263)]
ATTESTATION = "Yes, I certify, declare, and attest to the following declaration above."
FEEDBACK = ["N/A", "n/a", "Thank you!", "Thank you for this resource.", "The form was clear and easy to follow.",
            "I appreciate this program.", "Please consider raising the maximum amounts.", "No", "None"]
AP_STATEMENTS = ["I need support covering the costs of my placement.", "This subsidy would let me attend a conference "
                 "in my field.", "My program requires unpaid work that I cannot otherwise afford."]
LC_STATEMENTS = ["Rent and food costs have risen faster than my income.", "I lost hours at work this term and am "
                 "struggling to cover essentials.", "My OSAP does not cover my living costs.",
                 "I am supporting family members while studying full time."]


def postal_code(g: Gen) -> str:
    letters = "ABCEGHJKLMNPRSTVWXYZ"
    code = ["M",
            g.rng.randint(1, 9),
            g.rng.choice(letters),
            g.rng.randint(1, 9),
            g.rng.choice(letters),
            g.rng.randint(1, 9)]
    return "".join(str(c) for c in code)


def maybe(g: Gen, p_blank: float, value):
    return "" if g.chance(p_blank) else value


def make_row(g: Gen, student: dict, ts: datetime, number: str, email: str, last_name: str) -> dict:
    row = dict.fromkeys(HEADERS, "")
    faculty = FACULTIES.get(student["faculty"]) or FACULTIES[g.pick([(c, w) for c, (_, w) in FACULTIES.items()])]
    is_lc = g.chance(87 / 100)

    row["Timestamp"] = fmt_ts(ts)
    row["Application Semester"] = g.pick(SEMESTERS)
    row["Confirmation of UTSU Membership"] = "Yes" if g.chance(95 / 100) else "No"
    row["ACORN-registered First Name"] = student["first"]
    row["ACORN-registered Last Name"] = last_name
    row["Student Number"] = number
    row["UofT Email Address"] = email
    row["Faculty "] = faculty[0]
    row["PEY Co-op Status"] = maybe(g, 37 / 100, "Yes" if g.chance(15 / 100) else "No")
    row["Bursary Type"] = BURSARY_LC if is_lc else BURSARY_AP
    row["Postal Code - TMS"] = maybe(g, 0.30 / 100, postal_code(g))

    if is_lc:
        row["LC General Statement"] = g.rng.choice(LC_STATEMENTS)
        row["LC Subsidies"] = ";".join(g.multi(LC_SUBSIDIES, g.pick([(1, 130), (2, 205), (3, 191)])))
        row["LC Requested Amount"] = g.pick(LC_AMOUNTS)
        row["Disability Status - Mobility"] = "Yes" if g.chance(7.6 / 100) else "No"
        row["Disability Status - Invisible"] = "Yes" if g.chance(35 / 100) else "No"
        row["Living Situation"] = g.pick(LIVING)
        row["Access to Disposable Income"] = g.pick(DISPOSABLE)
        row["Liquidity"] = g.pick(LIQUIDITY)
        row["Number of Dependents and/or Remittance members"] = g.pick(DEPENDENTS)
        row["Access to External Supports"] = "Yes" if g.chance(63 / 100) else "No"
        circumstances = g.multi(EXTENUATING, g.pick(EXTENUATING_COUNT))
        if g.chance(4 / 100):
            circumstances.append(g.rng.choice(EXTENUATING_FREE))
        row["Extenuating Circumstances"] = ";".join(circumstances)
        row["Attestation"] = ATTESTATION
    else:
        row["AP General Statement"] = g.rng.choice(AP_STATEMENTS)
        row["AP Subsidies"] = ";".join(g.multi(AP_SUBSIDIES, g.pick([(1, 46), (2, 14), (3, 5), (4, 12)])))
        row["AP Request Amount"] = g.pick(AP_AMOUNTS)
        if g.chance(42 / 100):
            row["AP Additional Information"] = "http://google.com"

    row["Tuition Status"] = maybe(g, 3.5 / 100, g.pick(TUITION))
    row["Government Student-Aid Status"] = maybe(g, 5.1 / 100, g.pick(GOV_AID))
    row["Gender"] = maybe(g, 5.8 / 100, ";".join(g.multi(GENDER, g.pick([(1, 542), (2, 20), (3, 4), (4, 2)]))))
    row["Age"] = maybe(g, 4.6 / 100, g.pick(AGE))
    row["Race"] = maybe(g, 7.8 / 100, ";".join(g.multi(RACE, g.pick([(1, 487), (2, 61), (3, 7)]))))
    commute = min(300, max(5, round(g.rng.lognormvariate(3.9, 0.7) / 5) * 5))
    row["Commute Time"] = maybe(g, 8.3 / 100, str(commute))
    hours = 0 if g.chance(55 / 100) else g.rng.choice([4, 5, 8, 10, 12, 15, 16, 20, 24, 25, 30, 35, 40])
    row["Job Hours"] = maybe(g, 12 / 100, str(hours))
    row["Urban"] = maybe(g, 11 / 100, g.pick(URBAN))
    row["Referral Avenue"] = maybe(g, 6.8 / 100, ";".join(
        g.multi(REFERRAL, g.pick([(1, 382), (2, 113), (3, 41), (4, 14)]))))
    row["Contact Consent"] = "Yes" if g.chance(82 / 100) else "No"
    row["Research Invitation"] = maybe(g, 13 / 100, g.pick(RESEARCH))
    row["Do you have any feedback you would like to provide?"] = "" if g.chance(76 / 100) else g.rng.choice(FEEDBACK)
    return row


def generate(rows: int = 100, seed: int | str = DEFAULT_SEED, unmatched: float = 3,
             start: str = "2026-09-16", end: str = "2026-10-09") -> None:
    g = Gen(seed)
    pool = load_students()
    ghosts = not_in_roster(g, rows, len(pool))
    if len(pool) < rows - len(ghosts):
        raise SystemExit(f"SABP needs {rows - len(ghosts)} students to draw applicants from but fake_uoft_data.csv has "
                         f"{len(pool)}; generate the student data with at least {rows} students")
    g.rng.shuffle(pool)
    applicants = pool[:rows - len(ghosts)] + ghosts
    g.rng.shuffle(applicants)  # so the students outside the roster are spread over the application window

    first_day = datetime.fromisoformat(start)
    window = max(1, int((datetime.fromisoformat(end) + timedelta(days=1) - first_day).total_seconds()))
    stamps = sorted((first_day + timedelta(seconds=g.rng.randrange(window)) for _ in applicants), reverse=True)

    used_numbers, used_emails, out_rows = set(), set(), []
    for student, ts in zip(applicants, stamps):
        while True:
            number = f"10{g.rng.randint(0, 999):03d}{student['trunc']}{g.rng.randint(0, 9)}"
            if number not in used_numbers:
                used_numbers.add(number)
                break
        email = email_for(student["first"], student["last"])
        while email in used_emails:
            email = email.replace("@", f"{g.rng.randint(1, 99)}@", 1)
        used_emails.add(email)
        last = student["last"] + "x" if g.chance(unmatched / 100) else student["last"]
        out_rows.append(make_row(g, student, ts, number, email, last))

    write_csv(OUT, HEADERS, [[r[h] for h in HEADERS] for r in out_rows])
    print(f"Wrote {len(out_rows)} applications to {OUT}")
