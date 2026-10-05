from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Built from code points on purpose: this file must not contain them itself.
INVISIBLE = {
    chr(0x200B): "zero width space",
    chr(0x200C): "zero width non-joiner",
    chr(0x200D): "zero width joiner",
    chr(0x2060): "word joiner",
    chr(0xFEFF): "byte order mark",
    chr(0x00A0): "no-break space",
}
SCANNED = [
    *REPO_ROOT.joinpath("src").rglob("*.py"),
    *REPO_ROOT.joinpath("tests").rglob("*.py"),
    *REPO_ROOT.joinpath("scripts").rglob("*.py"),
    *REPO_ROOT.joinpath("infra").rglob("*.tf"),
    *REPO_ROOT.joinpath("infra").rglob("*.tftpl"),
    *REPO_ROOT.joinpath("docker").rglob("*"),
    REPO_ROOT / "Makefile",
]


def test_sources_contain_no_invisible_characters() -> None:
    found = []
    for path in SCANNED:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            for char, name in INVISIBLE.items():
                if char in line:
                    found.append(f"{path.relative_to(REPO_ROOT)}:{number}: {name}")
    # Use an escape (or codecs.BOM_UTF8) instead of a literal invisible character.
    assert found == []
