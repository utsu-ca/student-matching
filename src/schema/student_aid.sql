PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS student_aid (
    guid TEXT PRIMARY KEY,
    aid_type TEXT NOT NULL,
    amount REAL NOT NULL,
    FOREIGN KEY (guid) REFERENCES uoft_data(guid)
);

