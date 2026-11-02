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

# Faster searches with less waiting.
SEARCH_DELAY_SECONDS = 0.5
SEARCH_TIMEOUT = (3, 8)
SEARCH_MAX_ATTEMPTS = 2

SEARCH_CACHE_FILE = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "search_cache.json"
)


# ---------------------------------------------------------
# WORLDWIDE, MULTILINGUAL SEARCH TERMS
# ---------------------------------------------------------

GLOBAL_BUYER_TERMS = [
    "fresh fruit importer",
    "fresh orange importer",
    "citrus fruit importer",
    "fruit import company",
    "fruit wholesaler",
    "fresh produce wholesaler",
    "fruit distributor",
    "fruit and vegetable importer",
    "fresh produce distributor",
    "fruit trading company",
    "fruit purchasing company",
    "fruit procurement",
    "fruit buyer",
    "fresh produce buyer",
    "fruit supermarket supplier",
    "fruit retail supplier",
    "fresh fruit sourcing company",
    "fruit market distributor",
]

# Broad fruit coverage, in addition to the company's configured products.
GLOBAL_FRUITS = [
    "orange", "oranges", "citrus", "grape", "grapes",
    "pomegranate", "pomegranates", "apple", "apples",
    "banana", "bananas", "mango", "mangoes", "lemon", "lemons",
    "lime", "limes", "mandarin", "mandarins", "tangerine",
    "tangerines", "grapefruit", "peach", "peaches", "pear", "pears",
    "plum", "plums", "strawberry", "strawberries", "blueberry",
    "blueberries", "raspberry", "raspberries", "watermelon",
    "melon", "kiwi", "pineapple", "avocado", "date", "dates",
    "fig", "figs", "apricot", "apricots", "cherry", "cherries",
    "papaya", "guava", "persimmon", "fresh fruit",
]

MULTILINGUAL_BUYER_TERMS = [
    # Dutch
    "fruitimporteur",
    "groente en fruit groothandel",
    "verse fruit importeur",
    "citrus importeur",
    # German
    "Obstimporteur",
    "Obst und Gemüse Großhandel",
    "Frischobst Großhändler",
    "Zitrusfrüchte Importeur",
    # French
    "importateur de fruits frais",
    "grossiste en fruits",
    "distributeur de fruits",
    "importateur d'oranges",
    # Spanish
    "importador de frutas frescas",
    "mayorista de frutas",
    "distribuidor de frutas",
    "importador de naranjas",
    # Italian
    "importatore di frutta fresca",
    "grossista di frutta",
    "distributore di frutta",
    # Portuguese
    "importador de frutas frescas",
    "atacadista de frutas",
    "distribuidor de frutas",
    # Arabic
    "مستورد فواكه",
    "مستورد برتقال",
    "تجارة الفواكه والخضروات",
    "موزع فواكه طازجة",
    # Turkish
    "taze meyve ithalatçısı",
    "meyve toptancısı",
    "portakal ithalatçısı",
    # Russian
    "импортер свежих фруктов",
    "оптовая торговля фруктами",
    "импортер апельсинов",
    # Chinese
    "新鲜水果进口商",
    "水果批发商",
    "橙子进口商",
]

LOCALIZED_COUNTRY_TERMS = {
    "netherlands": [
        "fruitimporteur", "groente en fruit groothandel",
        "verse fruit importeur", "citrus importeur",
    ],
    "germany": [
        "Obstimporteur", "Obst und Gemüse Großhandel",
        "Frischobst Großhändler", "Zitrusfrüchte Importeur",
    ],
    "belgium": [
        "fruitimporteur", "importateur de fruits frais",
        "grossiste en fruits",
    ],
    "austria": ["Obstimporteur", "Obst und Gemüse Großhandel"],
    "switzerland": [
        "Obstimporteur", "importateur de fruits frais",
        "grossiste en fruits",
    ],
}


def get_world_countries() -> list[str]:
    """Return ISO country names using pycountry when installed."""
    try:
        import pycountry

        return sorted({
            country.name for country in pycountry.countries
            if getattr(country, "name", None)
        })
    except ImportError:
        # Keep global searches working without the optional dependency.
        return []


def build_search_queries(profile: dict) -> list[str]:
    """Build global, product-specific, and worldwide buyer queries."""
    products = profile.get("products", [])
    profile_countries = profile.get("target_countries", [])

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

    product_names = list(dict.fromkeys(
        GLOBAL_FRUITS
        + [name for name, _ in active_products]
    ))

    countries = list(dict.fromkeys(
        [str(c).strip() for c in profile_countries
         if str(c).strip()]
        + get_world_countries()
    ))

    queries = []

    # Broad searches without a country restriction.
    queries.extend(GLOBAL_BUYER_TERMS)
    queries.extend(MULTILINGUAL_BUYER_TERMS)

    # Product-specific global searches, prioritizing the full fruit list.
    for fruit in product_names:
        for term in GLOBAL_BUYER_TERMS[:12]:
            queries.append(f'"{fruit}" {term}')

    # Worldwide country-specific searches.
    for country in countries:
        for term in GLOBAL_BUYER_TERMS:
            queries.append(f'{term} "{country}"')

        for fruit in product_names:
            # Use fewer combinations per fruit to keep the query set useful.
            for term in GLOBAL_BUYER_TERMS[:6]:
                queries.append(f'"{fruit}" {term} "{country}"')

        for term in LOCALIZED_COUNTRY_TERMS.get(country.lower(), []):
            queries.append(f'{term} "{country}"')

    # Variety-specific searches from the company profile.
    for country in countries:
        for name, varieties in active_products:
            for variety in varieties:
                variety = str(variety).strip()
                if variety:
                    queries.append(
                        f'"{variety}" "{name}" importer "{country}"'
                    )

    return list(dict.fromkeys(
        query.strip() for query in queries if query.strip()
    ))


# ---------------------------------------------------------
# SEARCH CACHE
# ---------------------------------------------------------

def load_search_cache() -> dict:
    """Load cached search results."""
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
    """Save successful search results locally."""
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
        print(f"Could not save search cache: {exc}")


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
    Search OpenSERP, cache successful results, and use short
    timeouts with a limited number of retries.
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

    if cache_key in cache:
        cached_results = cache[cache_key]
        if isinstance(cached_results, list):
            print(f"Using cached results: {query}")
            return cached_results

    last_error = None

    for attempt in range(SEARCH_MAX_ATTEMPTS):
        try:
            if SEARCH_DELAY_SECONDS > 0:
                time.sleep(SEARCH_DELAY_SECONDS)

            response = requests.get(
                SEARCH_URL,
                params={
                    "text": query,
                    "limit": limit,
                },
                timeout=SEARCH_TIMEOUT,
            )

            if response.status_code in (429, 503):
                raise requests.HTTPError(
                    f"Search service returned HTTP "
                    f"{response.status_code}.",
                    response=response,
                )

            response.raise_for_status()
            data = response.json()

            if not isinstance(data, dict):
                raise requests.RequestException(
                    "Unexpected search response format."
                )

            results = data.get("results", [])

            if not isinstance(results, list):
                raise requests.RequestException(
                    "Search response has no valid results list."
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

            # Do not retry rate limits, service outages,
            # or ordinary client errors.
            if status in (429, 503):
                break

            if status is not None and status < 500:
                break

        except (
            requests.Timeout,
            requests.ConnectionError,
            requests.RequestException,
            ValueError,
        ) as exc:
            last_error = exc

        if attempt < SEARCH_MAX_ATTEMPTS - 1:
            delay = 1
            print(
                f"Search attempt {attempt + 1} failed. "
                f"Retrying in {delay}s: {last_error}"
            )
            time.sleep(delay)

    raise requests.RequestException(
        f"Search via {SEARCH_ENGINE} failed: {last_error}"
    )


# ---------------------------------------------------------
# RESULT RELEVANCE FILTER
# ---------------------------------------------------------

def is_relevant_result(result: dict) -> bool:
    """Filter obviously unrelated search results."""
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
    max_queries: int = 3,
    results_per_query: int = 10,
    max_results: int = 10,
    exclude_domains: set[str] | None = None,
    query_offset: int = 0,
) -> list[dict]:
    """
    Discover up to max_results unique candidate websites.

    Only max_queries searches are run. Existing domains can be
    excluded before discovery results are returned.

    This function does not save leads to the database.
    """

    if max_queries < 0:
        raise ValueError(
            "max_queries must be non-negative."
        )

    if results_per_query < 1 or max_results < 1:
        raise ValueError(
            "Result limits must be positive."
        )

    profile = load_company_profile()
    countries = profile.get("target_countries", [])
    all_queries = build_search_queries(profile)
    if not all_queries:
        return []

    # Rotate through the full query list instead of repeating the first
    # few queries on every click.
    start = query_offset % len(all_queries)
    queries = [
        all_queries[(start + i) % len(all_queries)]
        for i in range(min(max_queries, len(all_queries)))
    ]

    excluded = set()
    for value in (exclude_domains or set()):
        raw = str(value or "").strip()
        if not raw:
            continue
        # normalize_domain expects a URL with http(s); accept bare domains too.
        candidate = raw if "://" in raw else f"https://{raw}"
        domain = normalize_domain(candidate)
        if domain:
            excluded.add(domain)

    discovered = []
    seen_domains = set()

    print(f"Target countries: {', '.join(countries)}")
    print(f"Queries in this batch: {len(queries)}")
    print(f"Maximum candidate websites: {max_results}")

    for index, query in enumerate(queries, start=1):
        if len(discovered) >= max_results:
            break

        print(f"Search {index}/{len(queries)}: {query}")

        try:
            results = search_web(
                query,
                limit=results_per_query,
            )
        except requests.RequestException as exc:
            print(f"Search failed; continuing to next query: {exc}")
            continue

        for result in results:
            if not is_relevant_result(result):
                continue

            url = str(result.get("url") or "").strip()
            domain = normalize_domain(url)

            if not domain:
                continue

            if domain in excluded or domain in seen_domains:
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

            if len(discovered) >= max_results:
                break

    print(
        f"Unique new candidate websites: {len(discovered)}"
    )

    return discovered


# ---------------------------------------------------------
# LINKEDIN COMPANY-PAGE DISCOVERY
# ---------------------------------------------------------

def discover_linkedin_company_pages(
    max_queries: int = 3,
    results_per_query: int = 10,
) -> list[dict]:
    """
    Discover public LinkedIn company-page URLs through search.

    Does not crawl LinkedIn or save records to the database.
    Personal profile URLs are excluded.
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
    countries = list(dict.fromkeys(
        [str(c).strip() for c in profile.get("target_countries", [])
         if str(c).strip()]
        + get_world_countries()
    ))
    products = profile.get("products", [])

    buyer_terms = GLOBAL_BUYER_TERMS[:8] + MULTILINGUAL_BUYER_TERMS[:8]

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

    # Add global LinkedIn company searches so discovery is not limited
    # to country names present in the profile.
    for term in GLOBAL_BUYER_TERMS[:8]:
        queries.append(f'site:linkedin.com/company/ "{term}"')

    for fruit in GLOBAL_FRUITS:
        queries.append(
            f'site:linkedin.com/company/ "{fruit}" "importer"'
        )

    queries = list(dict.fromkeys(queries))[:max_queries]

    pages = []
    seen_urls = set()

    print(f"LinkedIn discovery queries: {len(queries)}")

    for index, query in enumerate(queries, start=1):
        print(f"LinkedIn search {index}/{len(queries)}: {query}")

        try:
            results = search_web(
                query,
                limit=results_per_query,
            )
        except requests.RequestException as exc:
            print(f"LinkedIn search failed: {exc}")
            continue

        for result in results:
            url = str(result.get("url") or "").strip()

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
                    item
                    for item in countries
                    if item.lower() in query.lower()
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
        f"Unique LinkedIn company-page candidates: {len(pages)}"
    )

    return pages
