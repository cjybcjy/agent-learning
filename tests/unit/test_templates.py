from heatmap.reporter.templates import render_today_table, render_archive_collapsible
from heatmap.aggregator.gates import Candidate


def _cands():
    return [Candidate("DOGE", 2.2, 3.4, 1.18, 1234, 1234.0)]


def test_today_table_contains_symbol_and_alpha():
    xml = render_today_table(_cands(), date="2026-04-30")
    assert "DOGE" in xml
    assert "+220" in xml  # alpha%
    assert "<table" in xml


def test_archive_wraps_in_collapsible_with_date_title():
    xml = render_archive_collapsible(_cands(), date="2026-04-30")
    assert "<collapsible" in xml
    assert "2026-04-30" in xml
