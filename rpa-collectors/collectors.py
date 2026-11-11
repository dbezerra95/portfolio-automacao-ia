import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from pydantic import BaseModel


class Record(BaseModel):
    source: str
    natural_key: str
    title: str
    detail: str


def parse_books(html: str) -> list[Record]:
    soup = BeautifulSoup(html, "html.parser")
    return [Record(source="books", natural_key=book.select_one("h3 a")["href"],
                   title=book.select_one("h3 a")["title"],
                   detail=book.select_one(".price_color").get_text(strip=True))
            for book in soup.select("article.product_pod")]


def parse_quotes(html: str) -> list[Record]:
    soup = BeautifulSoup(html, "html.parser")
    records = []
    for quote in soup.select("div.quote"):
        text = quote.select_one(".text").get_text(strip=True)
        author = quote.select_one(".author").get_text(strip=True)
        records.append(Record(source="quotes", natural_key=f"{author}:{text}",
                              title=text, detail=author))
    return records


def collect_books(pages: int) -> list[Record]:
    records = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.goto("https://books.toscrape.com/", wait_until="domcontentloaded")
            for index in range(pages):
                records.extend(parse_books(page.content()))
                next_link = page.locator("li.next a")
                if index + 1 == pages or not next_link.count():
                    break
                next_link.click()
                page.wait_for_load_state("domcontentloaded")
        finally:
            browser.close()
    return records


def collect_quotes(pages: int) -> list[Record]:
    records = []
    with httpx.Client(follow_redirects=True, timeout=30) as client:
        for page in range(1, pages + 1):
            response = client.get(f"https://quotes.toscrape.com/page/{page}/")
            response.raise_for_status()
            items = parse_quotes(response.text)
            records.extend(items)
            if not items:
                break
    return records


def save_records(records: list[Record], db_path: str | Path) -> dict[str, int]:
    counts = {"created": 0, "updated": 0, "unchanged": 0}
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS records (source TEXT, natural_key TEXT, "
                   "title TEXT, detail TEXT, content_hash TEXT, PRIMARY KEY (source, natural_key))")
        for record in records:
            content = json.dumps(record.model_dump(), sort_keys=True, ensure_ascii=False)
            digest = hashlib.sha256(content.encode()).hexdigest()
            old = db.execute("SELECT content_hash FROM records WHERE source = ? AND natural_key = ?",
                             (record.source, record.natural_key)).fetchone()
            status = "created" if old is None else "unchanged" if old[0] == digest else "updated"
            counts[status] += 1
            if status != "unchanged":
                db.execute("INSERT INTO records VALUES (?, ?, ?, ?, ?) "
                           "ON CONFLICT(source, natural_key) DO UPDATE SET "
                           "title=excluded.title, detail=excluded.detail, "
                           "content_hash=excluded.content_hash",
                           (record.source, record.natural_key, record.title, record.detail, digest))
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", choices=["books", "quotes"])
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--db", default="records.db")
    args = parser.parse_args()
    if args.pages < 1:
        parser.error("--pages must be positive")
    records = collect_books(args.pages) if args.source == "books" else collect_quotes(args.pages)
    print(save_records(records, args.db))


if __name__ == "__main__":
    main()
