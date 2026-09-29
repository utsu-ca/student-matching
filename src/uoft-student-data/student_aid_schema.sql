PRAGMA foreign_keys = ON;

CREATE TABLE  (
    student_id TEXT PRIMARY KEY,
    aid_type TEXT NOT NULL,
    amount REAL NOT NULL,
    FOREIGN KEY (student_id) REFERENCES students(student_id)
);

