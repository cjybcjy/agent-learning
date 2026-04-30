from pathlib import Path
from heatmap.extractor.dictionary import load_aliases
from heatmap.extractor.ac import AhoCorasickExtractor

def test_load_aliases(tmp_path: Path):
    p = tmp_path / "a.csv"
    p.write_text("symbol,alias,is_ambiguous,source\nBTC,比特币,false,seed\nAPT,apt,true,seed\n",
                 encoding="utf-8")
    entries = load_aliases(p)
    assert len(entries) == 2
    assert entries[0].symbol == "BTC"
    assert entries[1].is_ambiguous is True

def test_ac_extracts_ticker():
    from heatmap.extractor.dictionary import AliasEntry
    ext = AhoCorasickExtractor([
        AliasEntry("BTC", "比特币", False, "seed"),
        AliasEntry("DOGE", "doge", False, "seed"),
    ])
    hits = ext.extract("今天比特币和 doge 都飞了")
    symbols = sorted({h.symbol for h in hits})
    assert symbols == ["BTC", "DOGE"]

def test_ac_case_insensitive_for_latin():
    from heatmap.extractor.dictionary import AliasEntry
    ext = AhoCorasickExtractor([AliasEntry("DOGE", "doge", False, "seed")])
    hits = ext.extract("DOGE pump")
    assert len(hits) == 1
