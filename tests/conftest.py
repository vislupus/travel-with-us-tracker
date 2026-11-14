from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_html():
    def _load(name: str) -> str:
        return (FIXTURES / f"{name}.html").read_text(encoding="utf-8")
    return _load


class FakeFetcher:
    """Връща HTML от речник {url: html}; липсващ url -> FetchError (404); стойност-изключение се хвърля."""

    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.calls: list[str] = []

    def get(self, url: str) -> str:
        from tracker.fetch import FetchError
        self.calls.append(url)
        if url not in self.pages:
            raise FetchError("Страницата не съществува (404) – линкът вероятно е сменен.")
        page = self.pages[url]
        if isinstance(page, Exception):
            raise page
        return page


@pytest.fixture
def fake_fetcher():
    return FakeFetcher
