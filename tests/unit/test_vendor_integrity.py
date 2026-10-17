import hashlib
from pathlib import Path

# regenerate with tools/vendor_orgforge.py and update this pin together; a hand edit fails here
VENDORED = Path("src/constellation/_vendor/orgforge_causal.py")
PINNED_SHA256 = "fb30e0b497c3c78c1a11bfc0ea366f3a5e297991b20e9d131149710f66f9d43b"


def test_vendored_orgforge_code_is_byte_identical_to_its_generation() -> None:
    assert hashlib.sha256(VENDORED.read_bytes()).hexdigest() == PINNED_SHA256


def test_vendored_code_names_its_source_commit_and_licence() -> None:
    head = VENDORED.read_text().splitlines()[:3]
    assert "1da5e4b51e22f4a82db4b003becc9cb42cfec34b" in head[0]
    assert "third_party/orgforge/LICENSE" in head[1]
    assert Path("third_party/orgforge/LICENSE").read_text().startswith("MIT License")
