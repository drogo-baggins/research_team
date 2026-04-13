import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from research_team.search.google_parser import GoogleSearchParser


class TestGoogleSearchParser:
    """GoogleSearchParser のユニットテスト。"""

    def test_parse_returns_list_of_results(self):
        """パーサーが複数の SearchResult を返すこと。"""
        html = """
        <div data-hveid="CABQAA">
          <div>
            <a href="/url?q=https://example.com/article1&amp;sa=U">
              <h3>Article 1 Title</h3>
            </a>
            <span>Snippet for article 1 that describes the content.</span>
          </div>
        </div>
        <div data-hveid="CABQAB">
          <div>
            <a href="/url?q=https://example.com/article2&amp;sa=U">
              <h3>Article 2 Title</h3>
            </a>
            <span>Snippet for article 2 with different content.</span>
          </div>
        </div>
        """
        parser = GoogleSearchParser()
        results = parser.parse(html, max_results=5)
        assert len(results) >= 1
        assert all(r.url.startswith("http") for r in results)
        assert all(r.title for r in results)
        assert all(r.source == "human" for r in results)

    def test_parse_excludes_google_own_urls(self):
        """google.com ドメインの URL を除外すること。"""
        html = """
        <div data-hveid="CABQAA">
          <a href="/url?q=https://www.google.com/maps&sa=U"><h3>Google Maps</h3></a>
          <span>Internal google page</span>
        </div>
        <div data-hveid="CABQAB">
          <a href="/url?q=https://example.com/article&sa=U"><h3>External Article</h3></a>
          <span>Real article snippet</span>
        </div>
        """
        parser = GoogleSearchParser()
        results = parser.parse(html, max_results=5)
        urls = [r.url for r in results]
        assert not any("google.com" in u for u in urls)
        assert any("example.com" in u for u in urls)

    def test_parse_respects_max_results(self):
        """max_results を超えた結果を返さないこと。"""
        divs = "\n".join(
            f'<div data-hveid="CABQA{i}"><a href="/url?q=https://example.com/{i}&sa=U">'
            f'<h3>Title {i}</h3></a><span>Snippet {i}</span></div>'
            for i in range(5)
        )
        parser = GoogleSearchParser()
        results = parser.parse(divs, max_results=3)
        assert len(results) <= 3

    def test_parse_empty_html_returns_empty_list(self):
        """空の HTML に対して空のリストを返すこと。"""
        parser = GoogleSearchParser()
        results = parser.parse("", max_results=5)
        assert results == []

    def test_parse_decodes_google_redirect_url(self):
        """/url?q= 形式の Google リダイレクト URL を実際の URL にデコードすること。"""
        html = """
        <div data-hveid="CABQAA">
          <a href="/url?q=https://example.com/target%3Fid%3D1&sa=U">
            <h3>Target Article</h3>
          </a>
          <span>Snippet text</span>
        </div>
        """
        parser = GoogleSearchParser()
        results = parser.parse(html, max_results=5)
        if results:
            assert "google.com" not in results[0].url
            assert "example.com" in results[0].url
