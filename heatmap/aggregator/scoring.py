import math


def weighted_score(mention: int, interactions: int) -> float:
    """Stage B 加权分。零互动时回退为 mention（不会清零）。"""
    if mention <= 0:
        return 0.0
    factor = 1.0 + math.log10(1.0 + max(0, interactions))
    return mention * factor
