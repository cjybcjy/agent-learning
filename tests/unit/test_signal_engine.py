def test_prompt_includes_top_posts():
    from heatmap.ai.prompts import build_prompt
    posts = [
        {"content": "BTC to the moon", "interactions": 100},
        {"content": "Institutional buying", "interactions": 50},
    ]
    prompt = build_prompt(symbol="BTC", instant_alpha=2.5, sources="twitter", top_posts=posts)
    assert "BTC to the moon" in prompt
    assert "Institutional buying" in prompt
    assert "2.50%" in prompt or "250.00%" in prompt


def test_prompt_includes_json_schema():
    from heatmap.ai.prompts import build_prompt
    prompt = build_prompt("BTC", 1.0, "twitter", [])
    assert "anomaly_score" in prompt
    assert "sentiment_shift" in prompt
    assert "driver_keywords" in prompt
