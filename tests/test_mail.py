import csv
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utsu_mail import campaign, transport
from utsu_mail.__main__ import main
from utsu_mail.recipients import read_sql, split_by_validity
from utsu_mail.schema import schema_fields
from utsu_mail.templates import Template, TemplateError, load_template, parse_template

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = transport.SmtpSettings(host="localhost", from_addr="elections@utsu.ca", from_name="UTSU", security="none", delay=0)


def test_render_and_missing():
    t = Template("t", "Hi {{ full_name }}", "Dear {{full_name}} of {{ division }}", "<p>{{ full_name }}</p>")
    out = t.render({"full_name": "A <b>", "division": "UC"})
    assert out.subject == "Hi A <b>" and out.html == "<p>A &lt;b&gt;</p>"
    assert t.missing_fields({"full_name": "x"}) == ["division"]
    with pytest.raises(TemplateError):
        t.render({"full_name": "x"})


def test_subject_cannot_inject_headers():
    t = Template("t", "Hi {{ n }}", "body")
    assert "\n" not in t.render({"n": "a\r\nBcc: x@y.ca"}).subject


def test_parse_requires_subject():
    with pytest.raises(TemplateError):
        parse_template("x", "no header here")
    with pytest.raises(TemplateError):
        parse_template("x", "From: a\n\nbody")


def test_bundled_templates_only_use_schema_or_form_fields():
    allowed = {"full_name", "division", "id"}
    for name in ("senate_verified", "senate_unverified"):
        assert load_template(name, ROOT / "templates" / "email").fields <= allowed


def test_schema_fields_reads_sql_files():
    fields = schema_fields(ROOT / "src" / "schema")
    assert "first_name" in fields["uoft_data"]


def test_split_by_validity():
    rows = [{"email": "a@b.ca"}, {"email": "A@b.ca"}, {"email": "bad"}, {"email": ""}]
    kept, skipped = split_by_validity(rows, "email")
    assert kept == [rows[0]] and [n for n, _ in skipped] == [2, 3, 4]


def test_read_sql_is_readonly(tmp_path):
    import sqlite3
    db = tmp_path / "d.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("create table t (a text)")
    conn.execute("insert into t values ('x')")
    conn.commit()
    conn.close()
    assert read_sql(db, "select a as email from t") == [{"email": "x"}]
    with pytest.raises(ValueError):
        read_sql(db, "delete from t")


def test_review_requires_exact_confirmation():
    ready = [campaign.Prepared("a@b.ca", Template("t", "s", "b").render({}))]
    answers = iter(["yes", "r", "send"])
    out = []
    assert campaign.review(SETTINGS, ready, [], lambda i: None, lambda _: next(answers), out.append, random.Random(1))
    assert not campaign.review(SETTINGS, ready, [], lambda i: None, lambda _: "n", out.append)
    assert not campaign.review(SETTINGS, ready, [], lambda i: None, lambda _: (_ for _ in ()).throw(EOFError), out.append)


class FakeSMTP:
    sent = []

    def __init__(self, *a, **k): pass
    def ehlo(self): pass
    def quit(self): pass
    def close(self): pass
    def send_message(self, msg): FakeSMTP.sent.append(msg)


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def test_send_all_logs_and_resumes(monkeypatch, tmp_path):
    monkeypatch.setattr(transport.smtplib, "SMTP", FakeSMTP)
    FakeSMTP.sent = []
    t = Template("t", "Hi {{ n }}", "body {{ n }}")
    ready, skipped = campaign.prepare(t, [{"email": "a@b.ca", "n": "A"}, {"email": "c@d.ca", "n": ""}], "email")
    assert len(ready) == 1 and len(skipped) == 1
    log = tmp_path / "log.csv"
    assert campaign.send_all(SETTINGS, ready, log)["sent"] == 1
    assert FakeSMTP.sent[0]["To"] == "a@b.ca" and FakeSMTP.sent[0]["Subject"] == "Hi A"
    assert campaign.already_sent(log) == {"a@b.ca"}


def test_cli_dry_run_and_cancel(monkeypatch, tmp_path, capsys):
    tdir = tmp_path / "tpl"
    tdir.mkdir()
    (tdir / "hello.txt").write_text("Subject: Hi {{ full_name }}\n\nBody for {{ division }}\n", encoding="utf-8")
    recipients = tmp_path / "r.csv"
    write_csv(recipients, [{"email": "a@b.ca", "full_name": "Ada L", "division": "UC"}])
    base = ["hello", "--template_dir", str(tdir), "--recipients", str(recipients), "--log_dir", str(tmp_path),
            "--config", str(tmp_path / "none.json")]

    assert main(base + ["--dry_run"]) == 0
    assert "Subject: Hi Ada L" in capsys.readouterr().out

    # a missing field is reported against the schema, before any SMTP use
    (tdir / "bad.txt").write_text("Subject: x\n\n{{ faculty }}\n", encoding="utf-8")
    assert main(["bad"] + base[1:]) == 2

    # real send path with no smtp config refuses
    assert main(base) == 2
