import html


PROMPT_TEMPLATE = """你是一名量化市场异动分析专家。请根据以下标的在最近30分钟内的统计异动和【真实讨论抽样】，分析其异动背后的核心驱动力。

[统计异动]
标的: {symbol} | 即时α涨幅: {instant_alpha:.2%} | 来源: {sources}

[真实讨论抽样 (Top {post_count} 高赞/高频提及帖子)]
{posts_text}

重要约束：
1. 你必须完全基于上面提供的【真实讨论抽样】进行分析，禁止编造不存在的帖子内容或作者观点。
2. 如果讨论抽样信息不足，请明确说明"样本不足以得出结论"。
3. 所有推理必须引用具体帖子编号作为证据。

请基于上述真实讨论，返回严格符合以下 JSON Schema 的结果：
{{
  "anomaly_score": float,        // 0.0-1.0，异常强度
  "sentiment_shift": string,     // "positive" | "negative" | "neutral" | "mixed"
  "sentiment_confidence": float, // 0.0-1.0
  "key_driver": string,          // 一句话概括核心驱动力，不超过200字
  "key_driver_confidence": float,// 0.0-1.0
  "driver_keywords": [string],   // 最多10个关键词
  "reasoning": string            // 简要推理过程，基于提供的帖子，不超过2000字
}}
"""


def _sanitize_post_content(content: str, max_len: int = 500) -> str:
    """Sanitize raw post content for prompt injection safety.

    1. Strip HTML tags (if any).
    2. Escape curly braces so they don't interfere with JSON Schema template.
    3. Truncate to max_len characters.
    4. Replace newlines with spaces to keep prompt flat.
    """
    # Basic HTML tag removal (defense in depth)
    text = html.escape(content)
    # Flatten newlines
    text = text.replace("\n", " ").replace("\r", " ")
    # Escape braces so they don't break the JSON schema example in the prompt
    text = text.replace("{", "{{").replace("}", "}}")
    # Truncate
    if len(text) > max_len:
        text = text[: max_len - 3] + "..."
    return text


def build_prompt(symbol: str, instant_alpha: float, sources: str, top_posts: list[dict]) -> str:
    """Build the analysis prompt with sanitized post content."""
    sanitized_posts = []
    for i, post in enumerate(top_posts):
        raw_content = post.get("content", "")
        safe_content = _sanitize_post_content(raw_content)
        interactions = post.get("interactions", 0)
        sanitized_posts.append(f"{i + 1}. {safe_content} (互动: {interactions})")

    posts_text = "\n".join(sanitized_posts) if sanitized_posts else "(该窗口内无讨论样本)"

    return PROMPT_TEMPLATE.format(
        symbol=symbol,
        instant_alpha=instant_alpha,
        sources=sources,
        post_count=len(top_posts),
        posts_text=posts_text,
    )
