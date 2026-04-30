from dataclasses import dataclass
import ahocorasick
from heatmap.extractor.dictionary import AliasEntry

@dataclass(frozen=True)
class Hit:
    symbol: str
    matched_alias: str
    is_ambiguous: bool
    start: int
    end: int

class AhoCorasickExtractor:
    def __init__(self, entries: list[AliasEntry]):
        self._auto = ahocorasick.Automaton()
        for e in entries:
            key = e.alias.lower()
            self._auto.add_word(key, (e.symbol, e.alias, e.is_ambiguous))
        self._auto.make_automaton()

    def extract(self, text: str) -> list[Hit]:
        lower = text.lower()
        hits: list[Hit] = []
        for end_idx, (symbol, alias, is_amb) in self._auto.iter(lower):
            start_idx = end_idx - len(alias) + 1
            hits.append(Hit(symbol, alias, is_amb, start_idx, end_idx + 1))
        return hits
