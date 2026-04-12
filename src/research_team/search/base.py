from abc import ABC, abstractmethod
from pydantic import BaseModel


class SearchResult(BaseModel):
    url: str
    title: str
    content: str
    source: str


class SearchEngine(ABC):
    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        ...

    @abstractmethod
    async def fetch(self, url: str) -> SearchResult:
        ...
