import pytest
from abc import ABC
from research_team.search.serp_extractor import SerpExtractor
from research_team.search.base import SearchResult


def test_serp_extractor_is_abstract():
    """SerpExtractor は直接インスタンス化できないこと。"""
    assert issubclass(SerpExtractor, ABC)
    with pytest.raises(TypeError):
        SerpExtractor()  # type: ignore


def test_serp_extractor_concrete_subclass_works():
    """extract を実装したサブクラスはインスタンス化できること。"""

    class DummyExtractor(SerpExtractor):
        async def extract(self, page, max_results=5):
            return []

    extractor = DummyExtractor()
    assert isinstance(extractor, SerpExtractor)
