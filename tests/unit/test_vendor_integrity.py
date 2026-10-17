import hashlib
from pathlib import Path

# regenerate with tools/vendor_orgforge.py and update this pin together; a hand edit fails here
VENDORED = Path("src/constellation/_vendor/orgforge_causal.py")
PINNED_SHA256 = "bec879244c4ee773e159423d68eaf142b9f58d3e0bb876ccd4c4219499926d04"


def test_vendored_orgforge_code_is_byte_identical_to_its_generation() -> None:
    assert hashlib.sha256(VENDORED.read_bytes()).hexdigest() == PINNED_SHA256


def test_vendored_code_names_its_source_commit_and_licence() -> None:
    head = VENDORED.read_text().splitlines()[:3]
    assert "1da5e4b51e22f4a82db4b003becc9cb42cfec34b" in head[0]
    assert "third_party/orgforge/LICENSE" in head[1]
    assert Path("third_party/orgforge/LICENSE").read_text().startswith("MIT License")
