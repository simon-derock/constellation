import hashlib
from pathlib import Path

import pytest

# regenerate with tools/vendor_orgforge.py and update these pins together; a hand edit fails here
PINS = {
    "src/constellation/_vendor/orgforge_causal.py": "2b5c66f7184fe716f808e94b20a66247001f3b082eff173db252c5311527ce9d",
    "src/constellation/_vendor/orgforge_scoring.py": "15c79465e156cde41b43171ac8ff321b6a4f7597514b5dd91d32ad43d61e2dc5",
}


@pytest.mark.parametrize(("path", "digest"), PINS.items())
def test_vendored_orgforge_code_is_byte_identical_to_its_generation(path: str, digest: str) -> None:
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("path", PINS)
def test_vendored_code_names_its_source_commit_and_licence(path: str) -> None:
    head = Path(path).read_text().splitlines()[:3]
    assert "1da5e4b51e22f4a82db4b003becc9cb42cfec34b" in head[0]
    assert "third_party/orgforge/LICENSE" in head[1]
    assert Path("third_party/orgforge/LICENSE").read_text().startswith("MIT License")
