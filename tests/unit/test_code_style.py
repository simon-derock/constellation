import ast
from pathlib import Path

import pytest

# PLAN_SPEC §22: notes are inline comments; a docstring anywhere in shipped code is a defect
# verbatim third-party code (src/constellation/_vendor) keeps its upstream form; the rule binds our code
SHIPPED = [p for root in ("src", "tools") for p in Path(root).rglob("*.py") if "_vendor" not in p.parts]
DEFINITIONS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def docstring_sites(source: str) -> list[int]:
    tree = ast.parse(source)
    return [
        getattr(node, "lineno", 1)
        for node in ast.walk(tree)
        if isinstance(node, DEFINITIONS) and ast.get_docstring(node, clean=False) is not None
    ]


def test_detector_catches_module_class_and_function_docstrings() -> None:
    sample = '"""m"""\nclass A:\n    """c"""\n    def f(self) -> None:\n        """f"""\n'
    assert docstring_sites(sample) == [1, 2, 4]


def test_detector_ignores_plain_strings_and_comments() -> None:
    sample = "# note\nx = 'not a docstring'\ndef f() -> str:\n    return 'value'\n"
    assert docstring_sites(sample) == []


@pytest.mark.parametrize("path", SHIPPED, ids=str)
def test_shipped_code_has_no_docstrings(path: Path) -> None:
    assert docstring_sites(path.read_text()) == []
