from pathlib import Path

from traceability import Report, check, main, marker_ids, spec_ids

SPEC = "| AC-T3-01 | x |\n| AC-INV-02 | y |\nplaceholders AC-<area>-<nn> and AC-… are not ids\n"


def test_spec_ids_reads_real_ids_and_skips_placeholders() -> None:
    assert spec_ids(SPEC) == {"AC-T3-01", "AC-INV-02"}


def test_marker_ids_reads_decorators_and_module_marks_only() -> None:
    source = (
        "import pytest\n"
        "pytestmark = pytest.mark.ac('AC-INV-02')\n"
        "@pytest.mark.ac('AC-T3-01')\n"
        "@pytest.mark.integration\n"
        "def test_x() -> None: ...\n"
    )
    assert marker_ids(source) == {"AC-T3-01", "AC-INV-02"}


def test_report_splits_unknown_from_missing(tmp_path: Path) -> None:
    (tmp_path / "spec.md").write_text(SPEC)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("import pytest\n@pytest.mark.ac('AC-T9-99')\ndef test_a(): ...\n")
    report = check(tmp_path / "spec.md", tmp_path / "tests")
    assert report == Report(declared=frozenset({"AC-T3-01", "AC-INV-02"}), covered=frozenset({"AC-T9-99"}))
    assert report.unknown == {"AC-T9-99"}
    assert report.missing == {"AC-T3-01", "AC-INV-02"}


def test_strict_mode_fails_only_on_missing(tmp_path: Path) -> None:
    (tmp_path / "spec.md").write_text(SPEC)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("import pytest\n@pytest.mark.ac('AC-T3-01')\ndef test_a(): ...\n")
    argv = ["--spec", str(tmp_path / "spec.md"), "--tests", str(tmp_path / "tests")]
    assert main(argv) == 0
    assert main([*argv, "--strict"]) == 1


def test_repository_tests_cite_only_declared_acs() -> None:
    report = check(Path("PLAN_SPEC.md"), Path("tests"))
    # one sentinel per area: a broken id pattern would silently empty the gate
    assert {
        "AC-INV-01",
        "AC-T1-03",
        "AC-T2-04",
        "AC-T3-02",
        "AC-EV-01",
        "AC-AUD-02",
        "AC-MOD-01",
    } <= report.declared
    assert report.unknown == frozenset()
