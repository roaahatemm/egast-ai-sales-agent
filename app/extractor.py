
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup


GENERIC_TITLES = {
    "home",
    "homepage",
    "welcome",
    "wholesale",
    "contact",
    "about us",
    "products",
    "index",
}

COUNTRY_KEYWORDS = {
    "Netherlands": ["netherlands", "the netherlands", "dutch"],
    "Germany": ["germany", "german"],
    "United Kingdom": ["united kingdom", "britain", "british"],
    "Saudi Arabia": ["saudi arabia"],
    "United Arab Emirates": ["united arab emirates", "uae"],
    "Egypt": ["egypt", "egyptian"],
}

PRODUCT_KEYWORDS = [
    "oranges",
    "orange",
    "valencia",
    "navel",
    "citrus",
    "grapes",
    "grape",
    "pomegranates",
    "pomegranate",
    "vegetables",
    "vegetable",
    "fruit",
    "fruits",
]

IMPORTER_KEYWORDS = [
    "importer",
    "importers",
    "import",
    "wholesaler",
    "wholesalers",
    "wholesale",
    "distributor",
    "distributors",
    "fresh produce",
    "fruit and vegetables",
    "fruits and vegetables",
    "food importer",
    "produce supplier",
]


def clean_text(value: str | None) -> str:
    """Normalize whitespace in extracted text."""
    if not value:
        return ""

    return re.sub(r"\s+", " ", value).strip()


def detect_country(text: str) -> str:
    """
    Detect the first recognized country mentioned in text.

    Note: this detects a mention, not necessarily the company's
    registered location.
    """
    normalized = text.lower()

    for country, keywords in COUNTRY_KEYWORDS.items():
        for keyword in keywords:
            pattern = r"\b" + re.escape(keyword) + r"\b"

            if re.search(pattern, normalized):
                return country

    return ""


def extract_emails(text: str) -> list[str]:
    """Extract email addresses and remove duplicates."""
    pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"

    found = re.findall(pattern, text)
    emails = []
    seen = set()

    for email in found:
        normalized = email.strip().lower()

        if normalized not in seen:
            seen.add(normalized)
            emails.append(normalized)

    return emails


def get_domain(url: str) -> str:
    """Return a normalized hostname from a URL."""
    if not url:
        return ""

    parsed = urlparse(url if "://" in url else "https://" + url)
    hostname = (parsed.hostname or "").lower()

    if hostname.startswith("www."):
        hostname = hostname[4:]

    return hostname


def extract_company_name(soup: BeautifulSoup, domain: str) -> str:
    """Find a likely company name from page metadata."""
    candidates = []

    for attribute in [
        {"property": "og:site_name"},
        {"name": "application-name"},
    ]:
        tag = soup.find("meta", attrs=attribute)

        if tag and tag.get("content"):
            candidates.append(clean_text(tag["content"]))

    if soup.title:
        title = clean_text(soup.title.get_text(" ", strip=True))

        # Prefer the first part of titles like "Company Name | Home".
        for separator in [" | ", " - ", " – ", " — ", " :: "]:
            if separator in title:
                parts = [part.strip() for part in title.split(separator)]
                candidates.extend(parts)
                break

        candidates.append(title)

    for candidate in candidates:
        if (
            candidate
            and candidate.lower() not in GENERIC_TITLES
            and len(candidate) <= 120
        ):
            return candidate

    # Fallback to the website's domain.
    return domain.split(".")[0].replace("-", " ").title() if domain else "Unknown"


def extract_description(soup: BeautifulSoup) -> str:
    """Extract a page description from metadata."""
    for attribute in [
        {"name": "description"},
        {"property": "og:description"},
        {"name": "twitter:description"},
    ]:
        tag = soup.find("meta", attrs=attribute)

        if tag and tag.get("content"):
            description = clean_text(tag["content"])

            if description:
                return description[:1000]

    return ""


def extract_lead(html: str, url: str) -> dict:
    """
    Extract potential company lead information from website HTML.

    This function extracts publicly visible page information. The
    results are candidates for review, not proof that a company buys
    EGAST products or is actively seeking suppliers.
    """
    soup = BeautifulSoup(html or "", "html.parser")

    # Remove elements that usually contain navigation, scripts, or styles.
    for element in soup(
        ["script", "style", "noscript", "svg", "iframe"]
    ):
        element.decompose()

    domain = get_domain(url)
    website = f"https://{domain}" if domain else url

    company_name = extract_company_name(soup, domain)
    description = extract_description(soup)

    # Collect visible text from the page.
    text = clean_text(soup.get_text(" ", strip=True))
    business_text = clean_text(
        f"{company_name} {description} {text}"
    ).lower()

    # Detect country mentions. This may identify a target market rather
    # than the company's own location, so treat it as a clue only.
    country = detect_country(f"{description} {text}")

    # Identify likely business type using evidence from the page.
    if any(keyword in business_text for keyword in IMPORTER_KEYWORDS):
        industry = "Fresh Produce Importer/Wholesaler"
    elif any(
        keyword in business_text
        for keyword in ["exporter", "export company", "export fresh"]
    ):
        industry = "Fresh Produce Exporter"
    elif any(
        keyword in business_text
        for keyword in ["fruit", "vegetable", "agriculture", "produce"]
    ):
        industry = "Fresh Produce Business"
    else:
        industry = ""

    # Find email addresses in visible text and mailto links.
    email_source = text

    mailto_emails = []
    for link in soup.find_all("a", href=True):
        href = link["href"].strip()

        if href.lower().startswith("mailto:"):
            address = href[7:].split("?")[0].strip()
            mailto_emails.append(address)

    all_emails = extract_emails(email_source + " " + " ".join(mailto_emails))

    # Prefer an email whose domain matches the website.
    primary_email = ""

    for email in all_emails:
        email_domain = email.rsplit("@", 1)[-1].lower()

        if domain and (
            email_domain == domain
            or email_domain.endswith("." + domain)
        ):
            primary_email = email
            break

    # If no matching domain was found, keep the first discovered email.
    if not primary_email and all_emails:
        primary_email = all_emails[0]

    # Identify produce-related keywords found on the page.
    products = []

    for product in PRODUCT_KEYWORDS:
        pattern = r"\b" + re.escape(product) + r"\b"

        if re.search(pattern, business_text, flags=re.IGNORECASE):
            # Normalize singular/plural and variety names.
            if product in ["orange", "oranges", "valencia", "navel"]:
                normalized_product = "oranges"
            elif product in ["grape", "grapes"]:
                normalized_product = "grapes"
            elif product in ["pomegranate", "pomegranates"]:
                normalized_product = "pomegranates"
            elif product in ["vegetable", "vegetables"]:
                normalized_product = "vegetables"
            elif product in ["fruit", "fruits"]:
                normalized_product = "fruit"
            else:
                normalized_product = product

            if normalized_product not in products:
                products.append(normalized_product)

    # Keep short snippets to help a reviewer understand the extraction.
    # These are page-level clues, not proof of buyer intent.
    extraction_evidence = {
        "industry_text": description or text[:500],
        "product_text": description or text[:500],
        "country_text": description or text[:500],
    }

    return {
        "company_name": company_name or domain or "Unknown",
        "website": website,
        "email": primary_email,
        "emails": all_emails,
        "source_url": url,
        "description": description,
        "country": country,
        "industry": industry,
        "products": products,
        "extraction_evidence": extraction_evidence,
    }
