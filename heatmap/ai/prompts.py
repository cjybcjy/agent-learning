PROMPT_TEMPLATE = """你是一名量化市场异动分析专家。请根据以下标的在最近30分钟内的统计异动和【真实讨论抽样】，分析其异动背后的核心驱动力。

[统计异动]
标的: {symbol} | 即时α涨幅: {instant_alpha:.2%} | 来源: {sources}

[真实讨论抽样 (Top {post_count} 高赞/高频提及帖子)]
{posts_text}

请基于上述真实讨论，返回严格符合以下 JSON Schema 的结果：
{{
  "anomaly_score": float,
  "sentiment_shift": string,
  "sentiment_confidence": float,
  "key_driver": string,
  "key_driver_confidence": float,
  "driver_keywords": [string],
  "reasoning": string
}}
"""


def build_prompt(symbol: str, instant_alpha: float, sources: str, top_posts: list[dict]) -> str:
    posts_text = "\n".join(
        f"{i+1}. {p['content']} (互动: {p.get('interactions', 0)})"
        for i, p in enumerate(top_posts)
    )
    return PROMPT_TEMPLATE.format(
        symbol=symbol,
        instant_alpha=instant_alpha,
        sources=sources,
        post_count=len(top_posts),
        posts_text=posts_text
    )
