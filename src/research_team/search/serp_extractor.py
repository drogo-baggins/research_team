"""SERP（検索エンジン結果ページ）からの構造化データ抽出インターフェース。

各検索エンジン固有の抽出ロジックはこのABCを継承して実装する。
将来 Bing/DuckDuckGo を追加する場合は BingSearchExtractor 等を新規作成するだけでよい。
"""

from abc import ABC, abstractmethod

from playwright.async_api import Page

from research_team.search.base import SearchResult


class SerpExtractor(ABC):
    """検索エンジン結果ページからの構造化データ抽出の抽象基底クラス。

    実装クラスは extract() を override し、
    Playwright Page オブジェクトから SearchResult のリストを返すこと。
    """

    @abstractmethod
    async def extract(self, page: Page, max_results: int = 5) -> list[SearchResult]:
        """検索結果ページから SearchResult のリストを抽出する。

        Args:
            page: 検索結果ページが開かれた Playwright Page オブジェクト。
            max_results: 返す結果の最大件数。

        Returns:
            SearchResult のリスト。抽出失敗時は空リストを返す（例外を投げない）。
        """
        ...
