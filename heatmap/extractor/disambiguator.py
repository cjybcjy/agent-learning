from typing import Protocol

from heatmap.extractor.ac import Hit


class Disambiguator(Protocol):
    def resolve(self, text: str, hits: list[Hit]) -> list[Hit]: ...


class NoopDisambiguator:
    def resolve(self, text: str, hits: list[Hit]) -> list[Hit]:
        return hits
