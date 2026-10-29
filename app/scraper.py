

from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


def scrape_page_with_html(url: str) -> tuple[str, list[dict]]:
    """Download a webpage once and return its HTML and extracted links."""

    parsed_url = urlparse(url)

    if parsed_url.scheme not in ("http", "https"):
        raise ValueError("URL must use HTTP or HTTPS")

    if not parsed_url.netloc:
        raise ValueError("A valid URL is required")

    response = requests.get(
        url,
        timeout=15,
        headers={"User-Agent": "EGASTLeadResearch/1.0"},
    )
    response.raise_for_status()

    html = response.text
    soup = BeautifulSoup(html, "html.parser")

    results = []
    seen_urls = set()

    for link in soup.find_all("a", href=True):
        href = link["href"].strip()
        full_url = urljoin(url, href)
        parsed_link = urlparse(full_url)

        if parsed_link.scheme not in ("http", "https"):
            continue

        if full_url in seen_urls:
            continue

        seen_urls.add(full_url)

        results.append({
            "title": link.get_text(" ", strip=True),
            "url": full_url,
            "domain": parsed_link.netloc,
        })

    return html, results


def scrape_page(url: str) -> list[dict]:
    """Extract links from a public webpage."""

    _, links = scrape_page_with_html(url)
    return links
