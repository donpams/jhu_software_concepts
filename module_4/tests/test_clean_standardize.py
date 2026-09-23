"""clean.py and standardize.py: field cleaning, name normalization, the parallel
LLM driver (with subprocess faked) and the CLI (marker: analysis)."""

import json
import subprocess

import pytest

import clean
import standardize
from conftest import make_record

pytestmark = pytest.mark.analysis


# --------------------------------------------------------------------------- #
# clean_data                                                                  #
# --------------------------------------------------------------------------- #
def test_clean_data_normalizes_fields():
    raw = make_record(1, comments="<b>Great &amp; fun</b>  news", GPA="GPA 3.85", GRE="", **{"GRE AW": "GRE AW 4.5"},
                      status="Wait listed on Sep 07", decision_date="", Degree="phd")
    cleaned = clean.clean_data([raw, "not a dict"])
    assert len(cleaned) == 1
    row = cleaned[0]
    assert list(row) == clean.OUTPUT_KEYS
    assert row["comments"] == "Great & fun news"
    assert row["GPA"] == "3.85" and row["GRE"] is None and row["GRE AW"] == "4.5"
    assert row["status"] == "Wait listed" and row["decision_date"] == "Sep 07"
    assert row["Degree"] == "PhD"
    assert row["program"] == raw["program"]  # preserved verbatim


@pytest.mark.parametrize("status,expected", [
    ("accepted", ("Accepted", None)), ("REJECTED on 1 Mar", ("Rejected", "1 Mar")),
    ("Waitlisted", ("Wait listed", None)), ("Interview", ("Interview", None)),
    ("Other", ("Other", None)), ("Deferred", ("Deferred", None)), (None, (None, None)), ("", (None, None)),
])
def test_normalize_status(status, expected):
    assert clean._normalize_status(status, None) == expected


@pytest.mark.parametrize("value,expected", [
    ("masters", "Masters"), ("Master's", "Masters"), ("MS", "Masters"), ("Ph.D.", "PhD"),
    ("MFA", "MFA"), (None, None), ("", None),
])
def test_normalize_degree(value, expected):
    assert clean._normalize_degree(value) == expected


def test_strip_html_and_extract_number():
    assert clean._strip_html(None) is None
    assert clean._strip_html("  ") is None
    assert clean._strip_html("<p>a</p>&nbsp;b") == "a b"
    assert clean._extract_number("GPA 3.5") == "3.5"
    assert clean._extract_number("none") is None
    assert clean._extract_number("") is None


# --------------------------------------------------------------------------- #
# standardize.py                                                              #
# --------------------------------------------------------------------------- #
def test_fix_title_case_keeps_connectors():
    assert standardize.fix_title_case("master of arts in teaching") == "Master of Arts in Teaching"
    assert standardize.fix_title_case("of things") == "Of Things"


def test_normalize_university_paths():
    assert standardize.normalize_university("University of Michigan") == "University of Michigan"
    assert standardize.normalize_university("University Of Michgian") == "University of Michigan"      # fuzzy
    assert standardize.normalize_university("Penn State") == "Pennsylvania State University"          # fix table
    assert standardize.normalize_university("UBC") == "University of British Columbia"                 # abbreviation
    assert standardize.normalize_university("Washington University in St. Louis (WashU)") == \
        "Washington University in St. Louis"                                                           # parenthetical
    assert standardize.normalize_university("Kent Stat University") == "Kent State University"
    assert standardize.normalize_university("Xyzzy Institute of Nowhere") == "Xyzzy Institute of Nowhere"
    assert standardize.normalize_university("") == "Unknown"


def test_plausible_match_guard():
    assert standardize.plausible_match("Penn State University", "Kent State University") is False
    assert standardize.plausible_match("University of Michgian", "University of Michigan") is True
    # a near-miss that difflib accepts but the guard rejects -> falls through to the raw text
    assert standardize.normalize_university("Kent State University") == "Kent State University"
    assert standardize.normalize_university("Pent State University") == "Pent State University"


def test_normalize_program_and_split():
    assert standardize.normalize_program("computer science") == "Computer Science"
    assert standardize.normalize_program("Mathematic") == "Mathematics"
    assert standardize.normalize_program("Compuer Science") == "Computer Science"    # fuzzy
    assert standardize.normalize_program("Underwater Basket Weaving") == "Underwater Basket Weaving"
    assert standardize.split_program_string("physics, MIT") == ("Physics", "Massachusetts Institute of Technology")
    assert standardize.split_program_string("") == ("", "Unknown")


def test_best_match_and_read_canon(tmp_path):
    assert standardize.best_match("", ["a"]) is None
    assert standardize.best_match("a", []) is None
    assert standardize.read_canon(tmp_path / "missing.txt") == []
    (tmp_path / "c.txt").write_text("A\n\n B \n")
    assert standardize.read_canon(tmp_path / "c.txt") == ["A", "B"]


def test_refine_and_rules_only():
    rows = clean.clean_data([make_record(1, university="Stanford Universty", program_name="physics"),
                             make_record(2, university="", program_name="", program="History, Nowhere U")])
    out = clean.standardize_rules_only(rows)
    assert out[0]["llm-generated-university"] == "Stanford University"
    assert out[0]["llm-generated-program"] == "Physics"
    assert out[1]["llm-generated-program"] == "History" and out[1]["llm-generated-university"] == "Nowhere U"
    # an LLM answer that already matches is left alone; title-case artefacts are fixed
    row = {"university": "Yale University", "llm-generated-university": "Yale University",
           "llm-generated-program": "Master Of Arts"}
    assert clean._refine_standardized(row)["llm-generated-program"] == "Master of Arts"


# --------------------------------------------------------------------------- #
# Parallel LLM driver with subprocess faked                                   #
# --------------------------------------------------------------------------- #
def fake_app_py(monkeypatch):
    """Replace subprocess.run with a function that behaves like llm_hosting/app.py."""
    calls = []

    def run(command, cwd=None, check=None):
        calls.append(command)
        in_path, out_path = command[command.index("--file") + 1], command[command.index("--out") + 1]
        mode = "a" if "--append" in command else "w"
        with open(out_path, mode, encoding="utf-8") as fh:
            for row in json.loads(open(in_path, encoding="utf-8").read()):
                program, university = standardize.split_program_string(row["program"])
                fh.write(json.dumps({**row, "llm-generated-program": program,
                                     "llm-generated-university": university}) + "\n")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(clean.subprocess, "run", run)
    return calls


def test_standardize_with_llm_chunks_and_resumes(tmp_path, monkeypatch):
    calls = fake_app_py(monkeypatch)
    rows = clean.clean_data([make_record(i, program=f"Physics, University {i % 3}") for i in range(6)])
    out = clean.standardize_with_llm(rows, output=tmp_path / "ext.json", workers=2, work_dir=tmp_path / "work")
    assert len(out) == 6 and all(r["llm-generated-program"] == "Physics" for r in out)
    assert len(calls) == 2                       # 3 unique strings / 2 workers -> 2 chunks

    # resume: one chunk complete (skipped), one chunk partially done (remaining rows appended)
    partial = tmp_path / "work" / "chunk_00.jsonl"
    lines = partial.read_text().splitlines()
    partial.write_text(lines[0] + "\n")
    (tmp_path / "work" / "chunk_01.jsonl").unlink()
    calls.clear()
    clean.standardize_with_llm(rows, output=tmp_path / "ext.json", workers=2, work_dir=tmp_path / "work")
    assert any("--append" in c for c in calls)
    assert len(partial.read_text().splitlines()) == len(lines)


def test_standardize_with_llm_more_workers_than_strings(tmp_path, monkeypatch):
    calls = fake_app_py(monkeypatch)
    rows = clean.clean_data([make_record(1, program="Physics, Yale University", university="Yale University")])
    out = clean.standardize_with_llm(rows, output=tmp_path / "e.json", workers=3, work_dir=tmp_path / "w")
    assert len(calls) == 1 and out[0]["llm-generated-university"] == "Yale University"


def test_run_worker_skips_finished_chunk(tmp_path, monkeypatch):
    calls = fake_app_py(monkeypatch)
    chunk, out = tmp_path / "chunk_00.json", tmp_path / "chunk_00.jsonl"
    chunk.write_text(json.dumps([{"program": "A, B"}]))
    out.write_text('{"program": "A, B"}\n')
    clean._run_worker(chunk, out, "python")
    assert calls == []


def test_clean_cli(tmp_path, monkeypatch, capsys):
    fake_app_py(monkeypatch)
    source = tmp_path / "in.json"
    source.write_text(json.dumps([make_record(1), make_record(2)]))
    monkeypatch.chdir(tmp_path)
    assert clean.main(["--input", str(source), "--output", str(tmp_path / "c.json")]) == 0
    assert "cleaned 2 records" in capsys.readouterr().out
    assert clean.main(["--input", str(source), "--output", str(tmp_path / "c.json"), "--llm",
                       "--llm-output", str(tmp_path / "l.json"), "--workers", "1"]) == 0
    assert len(json.loads((tmp_path / "l.json").read_text())) == 2
