import os
from research_team.search.base import SearchEngine


def _get_human_engine() -> SearchEngine:
    from research_team.search.human import HumanSearchEngine
    return HumanSearchEngine()


def _get_tavily_engine() -> SearchEngine:
    from research_team.search.tavily import TavilySearchEngine
    return TavilySearchEngine()


_FACTORIES = {
    "human": _get_human_engine,
    "tavily": _get_tavily_engine,
}


class SearchEngineFactory:
    @staticmethod
    def create(mode: str | None = None) -> SearchEngine:
        mode = mode or os.environ.get("SEARCH_MODE", "human")
        factory_fn = _FACTORIES.get(mode)
        if factory_fn is None:
            raise ValueError(f"Unknown SEARCH_MODE: {mode!r}. Valid: {list(_FACTORIES)}")
        return factory_fn()
