"""
Lightweight HTTP-based web search without API keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
import re
from urllib.parse import parse_qs, quote_plus, urlparse

import requests

from runtime_logging import debug_log


USER_AGENT = "Mozilla/5.0"


@dataclass
class SearchItem:
    title: str
    url: str
    snippet: str = ""


@dataclass
class SearchResponse:
    query: str
    items: list[SearchItem]
    success: bool = True
    error: str = ""

    def format_text(self) -> str:
        if not self.success:
            return f"웹 검색에 실패했습니다. {self.error}".strip()
        if not self.items:
            return f"'{self.query}'에 대한 웹 검색 결과를 찾지 못했습니다."

        lines = [f"웹 검색 결과: {self.query}"]
        for index, item in enumerate(self.items, start=1):
            lines.append(f"{index}. {item.title}")
            lines.append(f"   {item.url}")
            if item.snippet:
                lines.append(f"   {item.snippet}")
        return "\n".join(lines)


class InternetSearchEngine:
    SEARCH_URL = "https://lite.duckduckgo.com/lite/"

    def __init__(self, verbose: bool = True, timeout_sec: int = 10):
        self.verbose = verbose
        self.timeout_sec = timeout_sec

    def search(self, query: str, max_results: int = 5) -> SearchResponse:
        normalized = " ".join(query.split())
        if not normalized:
            return SearchResponse(query=query, items=[], success=False, error="검색어가 비어 있습니다.")

        try:
            response = requests.get(
                f"{self.SEARCH_URL}?q={quote_plus(normalized)}&kl=kr-ko",
                headers={"User-Agent": USER_AGENT},
                timeout=self.timeout_sec,
            )
            response.raise_for_status()

            items = self._parse_items(response.text, max_results=max_results)
            debug_log(self.verbose, f"[InternetSearch] '{normalized}' → {len(items)}개 결과")
            return SearchResponse(query=normalized, items=items)
        except Exception as error:
            debug_log(self.verbose, f"[InternetSearch] 오류: {error}")
            return SearchResponse(query=normalized, items=[], success=False, error=str(error))

    def _parse_items(self, html: str, max_results: int) -> list[SearchItem]:
        parser = _LiteDuckDuckGoParser(self)
        parser.feed(html)
        return parser.items[:max_results]

    def _decode_result_url(self, href: str) -> str:
        parsed = urlparse(href)
        query = parse_qs(parsed.query)
        uddg = query.get("uddg")
        if uddg:
            return unescape(uddg[0])
        return unescape(href)

    def _clean_html(self, raw: str) -> str:
        text = re.sub(r"<.*?>", " ", raw)
        return " ".join(unescape(text).split())


class _LiteDuckDuckGoParser(HTMLParser):
    def __init__(self, engine: InternetSearchEngine):
        super().__init__()
        self.engine = engine
        self.items: list[SearchItem] = []
        self._capture_title = False
        self._capture_snippet = False
        self._title_parts: list[str] = []
        self._snippet_parts: list[str] = []
        self._current_url = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        attr_map = dict(attrs)
        css_class = attr_map.get("class", "") or ""

        if tag == "a" and "result-link" in css_class:
            self._capture_title = True
            self._title_parts = []
            self._current_url = self.engine._decode_result_url(attr_map.get("href", "") or "")
            return

        if tag == "td" and "result-snippet" in css_class and self.items:
            self._capture_snippet = True
            self._snippet_parts = []

    def handle_data(self, data: str):
        if self._capture_title:
            self._title_parts.append(data)
        elif self._capture_snippet:
            self._snippet_parts.append(data)

    def handle_endtag(self, tag: str):
        if tag == "a" and self._capture_title:
            title = self.engine._clean_html("".join(self._title_parts))
            if title and self._current_url:
                self.items.append(SearchItem(title=title, url=self._current_url, snippet=""))
            self._capture_title = False
            self._title_parts = []
            self._current_url = ""
            return

        if tag == "td" and self._capture_snippet:
            snippet = self.engine._clean_html("".join(self._snippet_parts))
            if snippet and self.items:
                self.items[-1].snippet = snippet
            self._capture_snippet = False
            self._snippet_parts = []