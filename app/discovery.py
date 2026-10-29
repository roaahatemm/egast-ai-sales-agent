

import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests

from app.config import load_company_profile


# ---------------------------------------------------------
# SEARCH CONFIGURATION
# ---------------------------------------------------------

SEARCH_ENGINE = os.getenv(
    "EGAST_SEARCH_ENGINE", "bing"
).strip().lower()

SEARCH_ENDPOINTS = {
    "bing": "http://127.0.0.1:7000/bing/search",
    "duckduckgo": "http://127.0.0.1:7000/duck/search",
}

if SEARCH_ENGINE not in SEARCH_ENDPOINTS:
    raise ValueError(
        "EGAST_SEARCH_ENGINE must be 'bing' or 'duckduckgo'"
    )

SEARCH_URL = SEARCH_ENDPOINTS[SEARCH_ENGINE]

# Wait between requests to reduce unnecessary search traffic.
SEARCH_DELAY_SECONDS = 4

# Cache successful results locally.
SEARCH_CACHE_FILE = Path("data/search_cache.json")


# ---------------------------------------------------------
# SEARCH TERMS
# ---------------------------------------------------------

BUYER_SEARCH_TERMS = [
    "fresh fruit importer",
    "fruit and vegetable importer",
    "fresh produce wholesaler",
    "fruit distributor",
    "fresh produce trading company",
    "supermarket fresh produce procurement",
    "supermarket fruit purchasing",
    "fruit and vegetable retailer",
    "fruit exporter",
    "fresh produce sourcing company",
]

COUNTRY_LANGUAGE_TERMS = {
    "Netherlands": [
        "fruit importeur",
        "groente fruit groothandel",
        "fruits and vegetables importer",
    ],
    "Germany": [
        "Obst Importeur",
        "Obst und Gemüse Großhandel",
        "Frischobst Händler",
    ],
    "United Kingdom": [
        "fresh fruit importer",
        "fruit wholesaler",
        "supermarket produce buyer",
    ],
    "Saudi Arabia": [
        "fruit importer",
        "fresh fruit wholesaler",
        "مستورد فواكه",
        "تجارة الفواكه",
    ],
    "United Arab Emirates": [
        "fruit importer",
        "fresh produce distributor",
        "مستورد فواكه",
        "تجارة الفواكه والخضروات",
    ],
}


# ---------------------------------------------------------
# SEARCH CACHE
# ---------------------------------------------------------

def load_search_cache() -> dict:
    """Load cached search results, if the cache exists."""
    try:
        if SEARCH_CACHE_FILE.exists():
            data = json.loads(
                SEARCH_CACHE_FILE.read_text(encoding="utf-8")
            )

            if isinstance(data, dict):
                return data

    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read search cache: {exc}")

    return {}


def save_search_cache(cache: dict) -> None:
    """Save cached results to a local JSON file."""
    try:
        SEARCH_CACHE_FILE.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        SEARCH_CACHE_FILE.write_text(
            json.dumps(
                cache,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    except OSError as exc:
        # Cache failure should not stop lead discovery.
        print(f"Could not save search cache: {exc}")


# ---------------------------------------------------------
# QUERY GENERATION
# ---------------------------------------------------------

def build_search_queries(profile: dict) -> list[str]:
    """Build searches for active products and target markets."""
    products = profile.get("products", [])
    countries = profile.get("target_countries", [])

    queries = []
    active_products = []

    for product in products:
        if isinstance(product, dict):
            if product.get("available") is False:
                continue

            name = str(product.get("name", "")).strip()
            varieties = product.get("varieties", [])

        else:
            name = str(product).strip()
            varieties = []

        if not name:
            continue

        if not isinstance(varieties, list):
            varieties = []

        active_products.append((name, varieties))

    if not active_products:
        return []

    for country in countries:
        buyer_terms = list(BUYER_SEARCH_TERMS)
        buyer_terms.extend(
            COUNTRY_LANGUAGE_TERMS.get(country, [])
        )

        # General buyer searches.
        for term in buyer_terms:
            queries.append(f"{term} {country}")

        # Product-specific searches.
        for name, varieties in active_products:
            for term in buyer_terms:
                queries.append(
                    f'"{name}" {term} {country}'
                )

            for variety in varieties:
                variety = str(variety).strip()

                if variety:
                    queries.append(
                        f'"{variety}" "{name}" importer {country}'
                    )

    # Preserve order while removing duplicate queries.
    return list(dict.fromkeys(queries))


# ---------------------------------------------------------
# DOMAIN NORMALIZATION
# ---------------------------------------------------------

def normalize_domain(url: str) -> str:
    """Normalize a URL to a domain for duplicate detection."""
    try:
        parsed = urlsplit(url.strip())

        if parsed.scheme.lower() not in ("http", "https"):
            return ""

        if not parsed.hostname:
            return ""

        host = parsed.hostname.lower().rstrip(".")

        if host.startswith("www."):
            host = host[4:]

        port = parsed.port

        if port and not (
            (parsed.scheme.lower() == "http" and port == 80)
            or (parsed.scheme.lower() == "https" and port == 443)
        ):
            host = f"{host}:{port}"

        return host

    except (ValueError, AttributeError):
        return ""


# ---------------------------------------------------------
# WEB SEARCH
# ---------------------------------------------------------

def search_web(query: str, limit: int = 10) -> list[dict]:
    """
    Search using the configured local OpenSERP service.

    Successful responses are cached. Temporary server and connection
    failures receive limited retries. HTTP 429 and 503 are not retried
    immediately, to avoid repeatedly hitting a failing service.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Search query must not be empty.")

    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or limit < 1
    ):
        raise ValueError(
            "Search limit must be a positive integer."
        )

    query = query.strip()
    cache = load_search_cache()
    cache_key = f"{SEARCH_ENGINE}:{query}:{limit}"

    # Reuse a previous successful search.
    if cache_key in cache:
        cached_results = cache[cache_key]

        if isinstance(cached_results, list):
            print(f"Using cached results for: {query}")
            return cached_results

    last_error = None

    for attempt in range(3):
        try:
            # Avoid unnecessary rapid requests to the search provider.
            time.sleep(SEARCH_DELAY_SECONDS)

            response = requests.get(
                SEARCH_URL,
                params={
                    "text": query,
                    "limit": limit,
                },
                timeout=25,
            )

            if response.status_code == 429:
                raise requests.HTTPError(
                    "Search service rate limited the request (HTTP 429).",
                    response=response,
                )

            if response.status_code == 503:
                raise requests.HTTPError(
                    "Search service is temporarily unavailable (HTTP 503).",
                    response=response,
                )

            response.raise_for_status()

            try:
                data = response.json()

            except ValueError as exc:
                raise requests.RequestException(
                    "Search service returned invalid JSON."
                ) from exc

            if not isinstance(data, dict):
                raise requests.RequestException(
                    "Search service returned an unexpected response format."
                )

            results = data.get("results", [])

            if not isinstance(results, list):
                raise requests.RequestException(
                    "Search service response does not contain a valid "
                    "results list."
                )

            cleaned_results = []

            for item in results:
                if not isinstance(item, dict):
                    continue

                url = item.get("url", "")

                if not isinstance(url, str) or not url.strip():
                    continue

                cleaned_results.append({
                    "title": str(item.get("title") or ""),
                    "url": url.strip(),
                    "snippet": str(item.get("snippet") or ""),
                    "engine": str(
                        item.get("engine") or SEARCH_ENGINE
                    ),
                })

            # Cache only successful responses.
            # An empty list is a valid successful result.
            cache[cache_key] = cleaned_results
            save_search_cache(cache)

            return cleaned_results

        except requests.HTTPError as exc:
            last_error = exc

            status = (
                exc.response.status_code
                if exc.response is not None
                else None
            )

            # Do not immediately retry rate limits or service outages.
            if status in (429, 503):
                break

            # Do not retry ordinary client errors.
            if status is not None and status < 500:
                break

            if attempt < 2:
                delay = 2 ** attempt

                print(
                    f"Search attempt {attempt + 1} failed. "
                    f"Retrying in {delay}s."
                )

                time.sleep(delay)

        except (
            requests.Timeout,
            requests.ConnectionError,
        ) as exc:
            last_error = exc

            if attempt < 2:
                delay = 2 ** attempt

                print(
                    f"Search attempt {attempt + 1} failed. "
                    f"Retrying in {delay}s."
                )

                time.sleep(delay)

        except requests.RequestException as exc:
            last_error = exc
            break

    raise requests.RequestException(
        f"Search via {SEARCH_ENGINE} failed: {last_error}"
    )


# ---------------------------------------------------------
# RESULT RELEVANCE FILTER
# ---------------------------------------------------------

def is_relevant_result(result: dict) -> bool:
    """
    Filter obviously unrelated results.

    A relevant keyword match does not prove that a company imports
    or buys EGAST products.
    """
    text = " ".join([
        str(result.get("title") or ""),
        str(result.get("snippet") or ""),
        str(result.get("url") or ""),
    ]).lower()

    irrelevant_terms = [
        "home appliances",
        "tourist attractions",
        "travel guide",
        "things to do",
    ]

    if any(term in text for term in irrelevant_terms):
        return False

    relevant_terms = [
        "importer",
        "importers",
        "importeur",
        "import",
        "wholesaler",
        "groothandel",
        "großhandel",
        "distributor",
        "distribution",
        "fruit",
        "fruits",
        "produce",
        "fresh produce",
        "vegetable",
        "vegetables",
        "obst",
        "supermarket",
        "supermarkets",
        "retailer",
        "retail",
        "trading",
        "sourcing",
        "فواكه",
        "الخضروات",
    ]

    return any(term in text for term in relevant_terms)


# ---------------------------------------------------------
# WEBSITE DISCOVERY
# ---------------------------------------------------------

def discover_leads(
    max_queries: int | None = None,
    results_per_query: int = 10,
) -> list[dict]:
    """
    Discover unique candidate websites.

    This function does not write results to the database.
    """
    if max_queries is not None and max_queries < 0:
        raise ValueError(
            "max_queries must be non-negative or None."
        )

    if results_per_query < 1:
        raise ValueError(
            "results_per_query must be positive."
        )

    profile = load_company_profile()
    queries = build_search_queries(profile)

    if max_queries is not None:
        queries = queries[:max_queries]

    discovered = []
    seen_domains = set()
    countries = profile.get("target_countries", [])

    print("Target countries: " + ", ".join(countries))
    print(f"Search queries to run: {len(queries)}")
    print(
        f"Results requested per query: {results_per_query}"
    )

    for index, query in enumerate(queries, start=1):
        print(f"\nSearch {index}/{len(queries)}: {query}")

        try:
            results = search_web(
                query,
                limit=results_per_query,
            )

        except requests.RequestException as exc:
            print(f"Search failed: {exc}")
            continue

        except (ValueError, TypeError) as exc:
            print(f"Invalid search response: {exc}")
            continue

        for result in results:
            if not is_relevant_result(result):
                continue

            url = result.get("url", "").strip()
            domain = normalize_domain(url)

            if not domain or domain in seen_domains:
                continue

            seen_domains.add(domain)

            candidate = dict(result)
            candidate["domain"] = domain
            candidate["search_query"] = query

            candidate["target_country"] = next(
                (
                    country
                    for country in countries
                    if country.lower() in query.lower()
                ),
                "",
            )

            discovered.append(candidate)

    print(
        f"\nUnique relevant websites: {len(discovered)}"
    )

    return discovered


# ---------------------------------------------------------
# LINKEDIN COMPANY-PAGE DISCOVERY
# ---------------------------------------------------------

def discover_linkedin_company_pages(
    max_queries: int = 20,
    results_per_query: int = 10,
) -> list[dict]:
    """
    Discover public LinkedIn company-page URLs via search results.

    This function does not crawl LinkedIn or write to the database.
    Personal profile URLs such as /in/ are excluded.
    """
    if max_queries < 0:
        raise ValueError(
            "max_queries must be non-negative."
        )

    if results_per_query < 1:
        raise ValueError(
            "results_per_query must be positive."
        )

    profile = load_company_profile()
    countries = profile.get("target_countries", [])
    products = profile.get("products", [])

    buyer_terms = [
        "fresh fruit importer",
        "fresh produce wholesaler",
        "fruit distributor",
        "fruit and vegetable importer",
        "supermarket produce procurement",
        "fresh produce trading company",
    ]

    queries = []

    for country in countries:
        for term in buyer_terms:
            queries.append(
                f'site:linkedin.com/company/ "{term}" "{country}"'
            )

        for product in products:
            if isinstance(product, dict):
                if product.get("available") is False:
                    continue

                product_name = str(
                    product.get("name") or ""
                ).strip()

            else:
                product_name = str(product).strip()

            if product_name:
                queries.append(
                    f'site:linkedin.com/company/ '
                    f'"{product_name}" importer "{country}"'
                )

    queries = list(dict.fromkeys(queries))[:max_queries]

    pages = []
    seen_urls = set()

    print(
        f"LinkedIn discovery queries: {len(queries)}"
    )

    for index, query in enumerate(queries, start=1):
        print(f"\nSearch {index}/{len(queries)}: {query}")

        try:
            results = search_web(
                query,
                limit=results_per_query,
            )

        except requests.RequestException as exc:
            print(f"Search failed: {exc}")
            continue

        for result in results:
            url = result.get("url", "").strip()

            try:
                parsed = urlsplit(url)
                hostname = (parsed.hostname or "").lower()

            except ValueError:
                continue

            if (
                parsed.scheme.lower() not in ("http", "https")
                or hostname not in {
                    "linkedin.com",
                    "www.linkedin.com",
                }
            ):
                continue

            path_parts = [
                part
                for part in parsed.path.split("/")
                if part
            ]

            # Only accept company pages, not personal profiles.
            if (
                len(path_parts) < 2
                or path_parts[0].lower() != "company"
            ):
                continue

            page_key = (
                "/" + "/".join(path_parts[:2]).lower()
            )

            if page_key in seen_urls:
                continue

            seen_urls.add(page_key)

            country = next(
                (
                    c
                    for c in countries
                    if c.lower() in query.lower()
                ),
                "",
            )

            pages.append({
                "company_page_url": url,
                "title": result.get("title", ""),
                "search_snippet": result.get("snippet", ""),
                "search_query": query,
                "target_country": country,
                "source": f"{SEARCH_ENGINE.title()} search",
                "status": "unverified_candidate",
            })

    print(
        "\nUnique LinkedIn company-page candidates: "
        f"{len(pages)}"
    )

    return pages
