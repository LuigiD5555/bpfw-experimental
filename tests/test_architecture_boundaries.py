import pathlib

def test_public_does_not_import_infrastructure():
    repo = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for path in repo.rglob("*.py"):
        lowered = str(path).lower()
        if "/public/" in lowered and "infrastructure" in path.read_text(encoding="utf-8", errors="ignore"):
            offenders.append(str(path))
    assert not offenders, f"Public layer imports infrastructure directly: {offenders}"
