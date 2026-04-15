from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class SearchResult:
    video_id: str
    title: str
    author: str
    duration: str
    cover: str
    url: str
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
