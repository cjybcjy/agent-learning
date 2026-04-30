from heatmap.aggregator.gates import Candidate


def _row(idx: int, c: Candidate) -> str:
    new_flag = "🆕" if c.alpha == float("inf") else ""
    alpha_str = "NEW" if c.alpha == float("inf") else f"+{c.alpha*100:.0f}%"
    return (
        f"<tr><td>{idx}</td><td>{c.symbol}</td>"
        f"<td>{c.mention}</td><td>{alpha_str}</td>"
        f"<td>{c.beta:.2f}</td><td>{c.composite:.3f}</td>"
        f"<td>{new_flag}</td></tr>"
    )


def _table(cands: list[Candidate]) -> str:
    head = "<tr><th>排名</th><th>标的</th><th>提及</th><th>α</th><th>β</th><th>复合分</th><th>标记</th></tr>"
    body = "".join(_row(i + 1, c) for i, c in enumerate(cands))
    return f"<table>{head}{body}</table>"


def render_today_table(cands: list[Candidate], date: str) -> str:
    return f"<p>📅 数据日期：{date}</p>" + _table(cands)


def render_archive_collapsible(cands: list[Candidate], date: str) -> str:
    return f"<collapsible><heading2>{date}</heading2>{_table(cands)}</collapsible>"
