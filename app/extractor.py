import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

def get_domain(url: str) -> str:
    """Return the domain name from a URL."""
    return (urlparse(url).hostname or "").lower().removeprefix("www.")

GENERIC_EMAIL_PREFIXES = {
    "info",
    "contact",
    "hello",
    "admin",
    "office",
    "support",
    "enquiries",
    "inquiries",
    "customerservice",
    "webmaster",
    "marketing",
}

SALES_EMAIL_PREFIXES = {
    "sales",
    "export",
    "exports",
    "trade",
    "commercial",
    "business",
    "b2b",
    "procurement",
    "purchasing",
}


def extract_emails(text: str) -> list[str]:
    """Extract unique email addresses from public page content."""
    pattern = (
        r"\b[A-Za-z0-9._%+-]+@"
        r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
    )

    emails = []
    seen = set()

    for email in re.findall(pattern, text or ""):
        email = email.strip(".,;:!?").lower()

        if email not in seen:
            seen.add(email)
            emails.append(email)

    return emails


def find_sales_emails(html: str, page_url: str) -> dict:
    """
    Extract publicly listed sales/export emails and other contacts.

    This does not guess email addresses or verify that an address
    belongs to a specific employee.
    """
    soup = BeautifulSoup(html or "", "html.parser")

    # Extract visible text and mailto links.
    visible_text = soup.get_text(" ", strip=True)
    mailto_emails = []

    for link in soup.find_all("a", href=True):
        href = link["href"].strip()

        if href.lower().startswith("mailto:"):
            address = href[7:].split("?")[0].strip()
            mailto_emails.extend(extract_emails(address))

    all_emails = extract_emails(
        visible_text + " " + " ".join(mailto_emails)
    )

    domain = (urlparse(page_url).hostname or "").lower()

    if domain.startswith("www."):
        domain = domain[4:]

    # Prefer emails belonging to the company's own website domain.
    company_emails = []
    external_emails = []

    for email in all_emails:
        email_domain = email.rsplit("@", 1)[-1]

        if (
            email_domain == domain
            or email_domain.endswith("." + domain)
        ):
            company_emails.append(email)
        else:
            external_emails.append(email)

    # Prioritize sales/export-related addresses.
    sales_emails = []
    other_emails = []

    for email in company_emails:
        prefix = email.split("@", 1)[0].lower()
        parts = re.split(r"[._+-]+", prefix)

        if any(
            part in SALES_EMAIL_PREFIXES
            for part in parts
        ):
            sales_emails.append(email)
        else:
            other_emails.append(email)

    return {
        "sales_email": sales_emails[0] if sales_emails else "",
        "sales_emails": sales_emails,
        "company_emails": company_emails,
        "other_emails": other_emails,
        "external_emails": external_emails,
        "all_emails": all_emails,
        "source_url": page_url,
    }


def find_contact_page_urls(html: str, website: str) -> list[str]:
    """Find likely public contact, sales, and export pages."""
    soup = BeautifulSoup(html or "", "html.parser")

    keywords = (
        "contact",
        "sales",
        "export",
        "team",
        "about",
        "commercial",
    )

    urls = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = link["href"].strip()
        label = link.get_text(" ", strip=True).lower()
        combined = f"{href.lower()} {label}"

        if not any(keyword in combined for keyword in keywords):
            continue

        full_url = urljoin(website.rstrip("/") + "/", href)
        parsed = urlparse(full_url)

        if parsed.scheme not in {"http", "https"}:
            continue

        # Avoid following unrelated external websites.
        website_domain = (urlparse(website).hostname or "").lower()
        target_domain = (parsed.hostname or "").lower()

        if (
            website_domain.startswith("www.")
        ):
            website_domain = website_domain[4:]

        if target_domain.startswith("www."):
            target_domain = target_domain[4:]

        if target_domain != website_domain:
            continue

        normalized_url = full_url.split("#", 1)[0]

        if normalized_url not in seen:
            seen.add(normalized_url)
            urls.append(normalized_url)

    return urls
def extract_lead(html: str, url: str) -> dict:
    """
    Preserve compatibility with the existing pipeline
    while extracting sales and export email addresses.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    text = soup.get_text(" ", strip=True)

    # Reuse the email extraction functions above.
    email_data = find_sales_emails(html, url)

    domain = get_domain(url)
    company_name = extract_company_name(soup, domain)
    description = extract_description(soup)
    country = detect_country(text)

    business_text = f"{company_name} {description} {text}".lower()

    if any(keyword in business_text for keyword in IMPORTER_KEYWORDS):
        industry = "Fresh Produce Importer/Wholesaler"
    elif any(keyword in business_text for keyword in [
        "exporter", "export company", "export fresh"
    ]):
        industry = "Fresh Produce Exporter"
    else:
        industry = "Fresh Produce Business"

    return {
        "company_name": company_name,
        "website": f"https://{domain}" if domain else url,
        "email": (
            email_data["sales_email"]
            or (email_data["all_emails"][0]
                if email_data["all_emails"] else "")
        ),
        "sales_email": email_data["sales_email"],
        "sales_emails": email_data["sales_emails"],
        "company_emails": email_data["company_emails"],
        "all_emails": email_data["all_emails"],
        "emails": email_data["all_emails"],
        "sales_email_source": (
            url if email_data["sales_email"] else ""
        ),
        "source_url": url,
        "description": description,
        "country": country,
        "industry": industry,
        "products": [],
        "extraction_evidence": {
            "industry_text": description or text[:500],
            "product_text": description or text[:500],
            "country_text": description or text[:500],
        },
    }


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
