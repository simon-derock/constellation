import argparse
import ast
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

# an AC id is AC-<AREA>-<two digits>; placeholders like AC-<area>-<nn> or AC-… never match
AC_ID = re.compile(r"\bAC-[A-Z0-9]+-\d{2}\b")


@dataclass(frozen=True)
class Report:
    declared: frozenset[str]
    covered: frozenset[str]

    @property
    def unknown(self) -> frozenset[str]:
        # a test citing an AC the spec never declared is always a defect
        return self.covered - self.declared

    @property
    def missing(self) -> frozenset[str]:
        # allowed while building; the release gate (--strict) forbids it
        return self.declared - self.covered


def spec_ids(spec_text: str) -> frozenset[str]:
    return frozenset(AC_ID.findall(spec_text))


def _is_ac_mark(func: ast.expr) -> bool:
    # matches pytest.mark.ac(...) and mark.ac(...) without importing the test module
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "ac"
        and (
            (isinstance(func.value, ast.Attribute) and func.value.attr == "mark")
            or (isinstance(func.value, ast.Name) and func.value.id == "mark")
        )
    )


def marker_ids(source: str) -> frozenset[str]:
    return frozenset(
        arg.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and _is_ac_mark(node.func)
        for arg in node.args
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
    )


def check(spec: Path, tests_root: Path) -> Report:
    covered = frozenset().union(*(marker_ids(p.read_text()) for p in sorted(tests_root.rglob("test_*.py"))))
    return Report(declared=spec_ids(spec.read_text()), covered=covered)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PLAN_SPEC acceptance-criteria traceability")
    parser.add_argument("--spec", type=Path, default=Path("PLAN_SPEC.md"))
    parser.add_argument("--tests", type=Path, default=Path("tests"))
    parser.add_argument("--strict", action="store_true", help="release gate: every AC needs a test")
    args = parser.parse_args(argv)
    report = check(args.spec, args.tests)
    print(f"traceability: {len(report.declared & report.covered)}/{len(report.declared)} ACs have tests")
    for ac in sorted(report.unknown):
        print(f"  unknown AC cited by tests: {ac}")
    if args.strict:
        for ac in sorted(report.missing):
            print(f"  no test for: {ac}")
    return 1 if report.unknown or (args.strict and report.missing) else 0


if __name__ == "__main__":
    sys.exit(main())
