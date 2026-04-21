import os
from research_team.search.base import SearchEngine

_DEFAULT_SEARCH_URL = "https://www.google.com/search?q="


def _get_human_engine(control_ui=None) -> SearchEngine:
    from research_team.search.human import HumanSearchEngine
    url = os.environ.get("SEARCH_ENGINE_URL", _DEFAULT_SEARCH_URL)
    return HumanSearchEngine(search_engine_url=url, control_ui=control_ui)


def _get_tavily_engine(control_ui=None) -> SearchEngine:
    from research_team.search.tavily import TavilySearchEngine
    return TavilySearchEngine()


def _get_serper_engine(control_ui=None) -> SearchEngine:
    from research_team.search.serper import SerperSearchEngine
    return SerperSearchEngine()


_FACTORIES = {
    "human": _get_human_engine,
    "tavily": _get_tavily_engine,
    "serper": _get_serper_engine,
}


class SearchEngineFactory:
    @staticmethod
    def create(mode: str | None = None, control_ui=None) -> SearchEngine:
        mode = mode or os.environ.get("SEARCH_MODE", "human")
        factory_fn = _FACTORIES.get(mode)
        if factory_fn is None:
            raise ValueError(f"Unknown SEARCH_MODE: {mode!r}. Valid: {list(_FACTORIES)}")
        return factory_fn(control_ui=control_ui)
