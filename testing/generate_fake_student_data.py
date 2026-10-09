"""
Fake UofT student data (testing/fake_uoft_data.csv), the roster every other form's applicants are verified against.
Run through generate_fake_data.py.

It is deterministic and built from data/seats_senate.csv: every division gets a few students, and always more than it
has Faculty/College seats, and the rest of the requested size is filled with students spread over the divisions like
the real applicants are. The generators for the forms (senate, sabp, agm) only read this file, so the size of the
roster (how many students there are to draw applicants from) is set here, with generate(size).
"""
from itertools import count

from generate_fake_data import DEFAULT_SEED, DEFAULT_STUDENTS, DIVISION_WEIGHTS, ORIGINAL_STUDENTS, TESTING, Gen, \
    division_of, generate_student, load_seats, write_students

OUT = TESTING / "fake_uoft_data.csv"
PER_DIVISION = 3


def generate(size: int = DEFAULT_STUDENTS) -> None:
    seats = load_seats()
    seats_in = {r["division"]: int(r["seats"]) for r in seats if r["constituency"] == "Faculty/College"}
    assert {d for d, _ in DIVISION_WEIGHTS} == set(seats_in), "DIVISION_WEIGHTS must cover every division"

    students = list(ORIGINAL_STUDENTS)
    nth = count()  # generate_student(n, ...) is unique for every n, so no clash checking is needed
    for d in seats_in:
        in_division = sum(1 for s in students if division_of(s) == d)
        needed = max(PER_DIVISION, seats_in[d] + 1)
        students += [generate_student(next(nth), d) for _ in range(max(0, needed - in_division))]
    if size < len(students):
        raise SystemExit(f"The student data needs at least {len(students)} students to cover every division")

    g = Gen(DEFAULT_SEED)
    while len(students) < size:
        students.append(generate_student(next(nth), g.pick(DIVISION_WEIGHTS)))

    write_students(OUT, students)
    print(f"Wrote {len(students)} students to {OUT}")
