
def score_lead(lead: dict) -> int:
    """Score a potential fresh-produce buyer from 0 to 100."""
    score = 0

    company_name = (lead.get("company_name") or "").lower()
    website = lead.get("website") or ""
    email = lead.get("email") or ""
    description = (lead.get("description") or "").lower()
    industry = (lead.get("industry") or "").lower()
    products = lead.get("products") or []

    if company_name and company_name != "unknown":
        score += 15

    if lead.get("country"):
        score += 10

    if website:
        score += 10

    if email:
        score += 10

    business_text = f"{description} {industry}"

    if any(term in business_text for term in [
        "importer", "import", "wholesaler", "distributor"
    ]):
        score += 25
    elif any(term in business_text for term in [
        "fresh produce", "fruit", "vegetable", "agricultural"
    ]):
        score += 15

    if isinstance(products, list) and products:
        score += 20

    return min(score, 100)
