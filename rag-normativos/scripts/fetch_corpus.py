"""Download the compiled text of LC 108/2001 and LC 109/2001 from planalto.gov.br and save clean text in data/."""
import html
import re
import sys
from pathlib import Path

import httpx

NORMAS = {
    "lc108_2001": "https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp108.htm",
    "lc109_2001": "https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp109.htm",
}
DATA = Path(__file__).resolve().parent.parent / "data"
NEW_PARAGRAPH = re.compile(r"^(Art\.|§|Parágrafo|[IVXL]+(\s*[–-]|$)|[a-z]\)|CAPÍTULO|TÍTULO|SEÇÃO|Seção|Subseção)")
HEADING = re.compile(r"^(CAPÍTULO|TÍTULO|SEÇÃO|Seção|Subseção)\b")


def clean(raw: bytes) -> list[str]:
    text = raw.decode("cp1252")
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", text)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</tr>|</div>|</table>", "\n", text)
    text = html.unescape(re.sub(r"(?s)<[^>]+>", "", text)).replace("\xa0", " ")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]
    lines = [line for line in lines if line]
    start = next(i for i, line in enumerate(lines) if line.startswith("Art. 1"))
    end = next(i for i, line in enumerate(lines) if line.startswith("Brasília,"))
    paragraphs: list[str] = []
    skipping_heading = False
    for line in lines[start:end]:
        if HEADING.match(line):
            skipping_heading = True
            continue
        if skipping_heading:
            if not line.startswith("Art."):
                continue
            skipping_heading = False
        if NEW_PARAGRAPH.match(line) or not paragraphs:
            paragraphs.append(line)
        else:
            paragraphs[-1] += " " + line
    joined = [re.sub(r"(?<=\d)o\b", "º", p) for p in paragraphs]
    joined = [re.sub(r"\bno (?=\d)", "nº ", p) for p in joined]
    return [re.sub(r"§\s+(?=\d)", "§ ", p) for p in joined]


def main() -> None:
    DATA.mkdir(exist_ok=True)
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/120 Safari/537.36"}
    with httpx.Client(timeout=60, follow_redirects=True, headers=headers) as client:
        for name, url in NORMAS.items():
            response = client.get(url)
            if response.status_code != 200:
                sys.exit(f"Falha ao baixar {url}: HTTP {response.status_code}")
            paragraphs = clean(response.content)
            (DATA / f"{name}.txt").write_text(f"Fonte: {url}\n" + "\n".join(paragraphs) + "\n", encoding="utf-8")
            print(f"{name}: {len(paragraphs)} parágrafos")


if __name__ == "__main__":
    main()
