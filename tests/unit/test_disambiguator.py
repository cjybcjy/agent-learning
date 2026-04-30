from heatmap.extractor.disambiguator import NoopDisambiguator
from heatmap.extractor.ac import Hit


def test_noop_returns_input_unchanged():
    d = NoopDisambiguator()
    hits = [Hit("BTC", "btc", False, 0, 3)]
    assert d.resolve("any text", hits) is hits
