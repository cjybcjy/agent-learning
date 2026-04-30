from dataclasses import dataclass
from pathlib import Path
import csv

@dataclass(frozen=True)
class AliasEntry:
    symbol: str
    alias: str
    is_ambiguous: bool
    source: str

def load_aliases(path: Path) -> list[AliasEntry]:
    out: list[AliasEntry] = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out.append(AliasEntry(
                symbol=row["symbol"].strip(),
                alias=row["alias"].strip(),
                is_ambiguous=row["is_ambiguous"].strip().lower() == "true",
                source=row.get("source", "").strip(),
            ))
    return out
