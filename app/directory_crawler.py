
from collections import deque
from urllib.parse import urljoin, urlparse, urldefrag
from urllib.robotparser import RobotFileParser
import ipaddress
import socket

import requests
from bs4 import BeautifulSoup

from app.discovery import normalize_domain


USER_AGENT = "EGASTLeadResearch/1.0"
REQUEST_TIMEOUT = 15

ROBOTS_CACHE = {}

DIRECTORY_KEYWORDS = (
    "company",
    "companies",
    "supplier",
    "suppliers",
    "importer",
    "importers",
    "wholesaler",
    "distributor",
    "business",
    "member",
    "members",
    "directory",
    "page",
)

EXCLUDED_EXTENSIONS = (
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".zip",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
)

EXCLUDED_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "tiktok.com",
    "x.com",
    "twitter.com",
    "wa.me",
    "whatsapp.com",
    "t.me",
}


def is_public_http_url(url: str) -> bool:
    """Check that a URL uses HTTP/HTTPS and has no embedded credentials."""
    try:
        parsed = urlparse(url)

        return (
            parsed.scheme.lower() in ("http", "https")
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
            and parsed.port != 0
        )
    except ValueError:
        return False


def is_excluded_domain(domain: str) -> bool:
    """Exclude irrelevant social and messaging domains."""
    domain = domain.lower().rstrip(".")

    return any(
        domain == excluded or domain.endswith("." + excluded)
        for excluded in EXCLUDED_DOMAINS
    )


def is_linkedin_company_page(url: str) -> bool:
    """Identify LinkedIn company or school pages, not personal profiles."""
    try:
        parsed = urlparse(url)
        domain = (parsed.hostname or "").lower().rstrip(".")

        if domain != "linkedin.com" and not domain.endswith(".linkedin.com"):
            return False

        path_parts = [
            part for part in parsed.path.strip("/").split("/") if part
        ]

        return (
            len(path_parts) >= 2
            and path_parts[0].lower() in {"company", "school"}
        )
    except ValueError:
        return False
    


def is_safe_public_url(url: str) -> bool:
    """
    Reject URLs whose host resolves to a non-public IP address.

    This is an additional safeguard, not a complete defense against
    DNS rebinding or every possible network-level attack.
    """
    if not is_public_http_url(url):
        return False

    try:
        parsed = urlparse(url)
        hostname = parsed.hostname

        if not hostname:
            return False

        # Handle IP addresses supplied directly in the URL.
        try:
            addresses = [ipaddress.ip_address(hostname)]
        except ValueError:
            # Resolve hostnames and inspect every returned address.
            port = parsed.port or (443 if parsed.scheme == "https" else 80)

            results = socket.getaddrinfo(
                hostname,
                port,
                type=socket.SOCK_STREAM,
            )

            addresses = [
                ipaddress.ip_address(result[4][0])
                for result in results
            ]

        if not addresses:
            return False

        # Reject the host if ANY resolved address is not globally routable.
        return all(address.is_global for address in addresses)

    except (ValueError, OSError, socket.gaierror):
        return False



def can_fetch_url(url: str) -> bool:
    """
    Check robots.txt permission before fetching a page.

    If robots.txt cannot be retrieved, fail closed and skip the page.
    """
    if not is_safe_public_url(url):
      return False

    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    if robots_url not in ROBOTS_CACHE:
        parser = RobotFileParser()
        parser.set_url(robots_url)

        try:
            response = requests.get(
                robots_url,
                timeout=10,
                headers={"User-Agent": USER_AGENT},
                allow_redirects=False,
            )

            if response.is_redirect:
                # Do not follow robots.txt redirects in this version.
                ROBOTS_CACHE[robots_url] = None
            else:
                response.raise_for_status()
                parser.parse(response.text.splitlines())
                ROBOTS_CACHE[robots_url] = parser

        except requests.RequestException:
            ROBOTS_CACHE[robots_url] = None

    parser = ROBOTS_CACHE[robots_url]

    if parser is None:
        return False

    return parser.can_fetch(USER_AGENT, url)


def is_excluded_url(url: str) -> bool:
    """Filter excluded domains, while retaining LinkedIn company pages."""
    domain = normalize_domain(url)

    if not domain:
        return True

    return (
        is_excluded_domain(domain)
        and not is_linkedin_company_page(url)
    )


def extract_directory_links(page_url: str) -> list[dict]:
    """
    Extract link candidates from one permitted public HTML page.

    Results are unverified candidates and are not saved to the database.
    """
    if not is_public_http_url(page_url):
        raise ValueError("Page URL must use HTTP or HTTPS")

    if not can_fetch_url(page_url):
        print(f"Skipped: robots.txt permission unavailable or denied: {page_url}")
        return []

    try:
        response = requests.get(
            page_url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=False,
        )

        if response.is_redirect:
            print(f"Skipped redirect: {page_url}")
            return []

        response.raise_for_status()

    except requests.RequestException as exc:
        print(f"Page skipped: {exc}")
        return []

    content_type = response.headers.get("Content-Type", "").lower()

    if "text/html" not in content_type:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    seen = set()
    source_domain = normalize_domain(page_url)

    for link in soup.find_all("a", href=True):
        title = link.get_text(" ", strip=True)
        url = urljoin(page_url, link["href"].strip())
        url, _fragment = urldefrag(url)

        if not is_public_http_url(url):
            continue

        parsed = urlparse(url)

        if parsed.path.lower().endswith(EXCLUDED_EXTENSIONS):
            continue

        domain = normalize_domain(url)

        if not domain or url in seen:
            continue

        linkedin_company = is_linkedin_company_page(url)

        if is_excluded_url(url):
            continue

        seen.add(url)

        results.append({
            "title": title,
            "url": url,
            "domain": domain,
            "source_directory": page_url,
            "is_external": domain != source_domain,
            "is_listing_candidate": any(
                word in (title + " " + parsed.path).lower()
                for word in DIRECTORY_KEYWORDS
            ),
            "is_linkedin_company_page": linkedin_company,
            "status": "unverified_candidate",
        })

    return results


def crawl_directory(
    start_url: str,
    max_pages: int = 10,
    max_results: int = 200,
) -> list[dict]:
    """
    Crawl a limited number of permitted pages within one directory domain.

    Collects unverified candidates only. Does not modify the lead database.
    """
    if not is_public_http_url(start_url):
       raise ValueError("Start URL must use HTTP or HTTPS")

    if not is_safe_public_url(start_url):
       raise ValueError(
        "Start URL must resolve exclusively to public IP addresses"
    )
    if max_pages < 1 or max_results < 1:
        raise ValueError("max_pages and max_results must be at least 1")

    start_domain = normalize_domain(start_url)

    if not start_domain:
        raise ValueError("Could not determine the starting domain")

    queue = deque([start_url])
    visited_pages = set()
    seen_external_domains = set()
    seen_linkedin_urls = set()
    candidates = []

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    while queue and len(visited_pages) < max_pages:
        page_url = queue.popleft()
        page_domain = normalize_domain(page_url)

        if page_url in visited_pages or page_domain != start_domain:
            continue

        if not can_fetch_url(page_url):
            print(
                "Skipped: robots.txt permission unavailable or denied: "
                f"{page_url}"
            )
            continue

        visited_pages.add(page_url)
        print(f"Crawling {len(visited_pages)}/{max_pages}: {page_url}")

        try:
            response = session.get(
                page_url,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
            )

            if response.is_redirect:
                print(f"Skipped redirect: {page_url}")
                continue

            response.raise_for_status()

        except requests.RequestException as exc:
            print(f"Page skipped: {exc}")
            continue

        # Extra check in case the response URL differs from the requested URL.
        if normalize_domain(response.url) != start_domain:
            print(f"Page skipped after redirect: {response.url}")
            continue

        content_type = response.headers.get("Content-Type", "").lower()

        if "text/html" not in content_type:
            continue

        soup = BeautifulSoup(response.text, "html.parser")

        for link in soup.find_all("a", href=True):
            title = link.get_text(" ", strip=True)
            url = urljoin(page_url, link["href"].strip())
            url, _fragment = urldefrag(url)

            if not is_public_http_url(url):
                continue

            parsed = urlparse(url)

            if parsed.path.lower().endswith(EXCLUDED_EXTENSIONS):
                continue

            domain = normalize_domain(url)

            if not domain:
                continue

            linkedin_company = is_linkedin_company_page(url)

            # Preserve LinkedIn company pages as separate candidates.
            if linkedin_company:
                if url not in seen_linkedin_urls:
                    seen_linkedin_urls.add(url)

                    candidates.append({
                        "title": title,
                        "url": url,
                        "domain": domain,
                        "source_directory": page_url,
                        "is_external": True,
                        "is_linkedin_company_page": True,
                        "status": "unverified_candidate",
                    })

                    if len(candidates) >= max_results:
                        return candidates

                continue

            if domain != start_domain:
                if is_excluded_url(url):
                    continue

                # Keep one candidate per external domain.
                if domain not in seen_external_domains:
                    seen_external_domains.add(domain)

                    candidates.append({
                        "title": title,
                        "url": url,
                        "domain": domain,
                        "source_directory": page_url,
                        "is_external": True,
                        "is_linkedin_company_page": False,
                        "status": "unverified_candidate",
                    })

                    if len(candidates) >= max_results:
                        return candidates

                continue

            path_and_title = (
                parsed.path + " " + title
            ).lower()

            looks_like_listing = any(
                word in path_and_title
                for word in DIRECTORY_KEYWORDS
            )

            if looks_like_listing and url not in visited_pages:
                if url not in queue:
                    queue.append(url)

    return candidates
