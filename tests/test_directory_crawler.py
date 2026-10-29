
from app.directory_crawler import (
    is_excluded_domain,
    is_linkedin_company_page,
)


def test_excludes_social_and_messaging_domains():
    assert is_excluded_domain("facebook.com")
    assert is_excluded_domain("www.facebook.com")
    assert is_excluded_domain("wa.me")
    assert is_excluded_domain("api.whatsapp.com")


def test_keeps_normal_company_domains():
    assert not is_excluded_domain("freshdiamond.nl")
    assert not is_excluded_domain("example.com")


def test_linkedin_company_pages_are_preserved():
    assert is_linkedin_company_page(
        "https://www.linkedin.com/company/example/"
    )
    assert is_linkedin_company_page(
        "https://linkedin.com/school/example/"
    )


def test_linkedin_personal_profiles_are_not_company_pages():
    assert not is_linkedin_company_page(
        "https://www.linkedin.com/in/example/"
    )
