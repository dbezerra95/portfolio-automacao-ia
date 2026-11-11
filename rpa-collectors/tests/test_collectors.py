from pathlib import Path

import httpx

from collectors import collect_books, collect_quotes, parse_books, parse_quotes, save_records

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_books():
    records = parse_books((FIXTURES / "books.html").read_text())
    assert records[0].title == "A Book" and records[0].detail == "£12.50"
    assert parse_books("<html></html>") == []


def test_parse_quotes():
    records = parse_quotes((FIXTURES / "quotes.html").read_text())
    assert records[0].detail == "An Author"
    assert parse_quotes("<html></html>") == []


def test_storage_idempotency_and_update(tmp_path):
    records = parse_books((FIXTURES / "books.html").read_text())
    path = tmp_path / "records.db"
    assert save_records(records, path) == {"created": 1, "updated": 0, "unchanged": 0}
    assert save_records(records, path) == {"created": 0, "updated": 0, "unchanged": 1}
    records[0].detail = "£15.00"
    assert save_records(records, path) == {"created": 0, "updated": 1, "unchanged": 0}


def test_collect_quotes_offline(monkeypatch):
    html = (FIXTURES / "quotes.html").read_text()

    def get(self, url):
        return httpx.Response(200, text=html if "/1/" in url else "<html></html>",
                              request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", get)
    assert len(collect_quotes(2)) == 1


def test_collect_books_offline(monkeypatch):
    from unittest.mock import MagicMock

    html = (FIXTURES / "books.html").read_text()
    playwright_context = MagicMock()
    browser = playwright_context.__enter__.return_value.chromium.launch.return_value
    page = browser.new_page.return_value
    page.content.return_value = html
    page.locator.return_value.count.return_value = 0
    monkeypatch.setattr("collectors.sync_playwright", lambda: playwright_context)

    records = collect_books(2)

    assert len(records) == 1
    assert records[0].title == "A Book"
    assert records[0].detail == "£12.50"
    browser.close.assert_called_once()
