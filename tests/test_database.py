
import app.database as database


def test_save_and_retrieve_lead(tmp_path, monkeypatch):
    monkeypatch.setattr(
        database,
        "DATABASE_PATH",
        tmp_path / "test_leads.db",
    )

    lead = {
        "company_name": "Example Importer",
        "country": "Germany",
        "industry": "Fresh Produce Import",
        "website": "https://example.com",
        "email": "contact@example.com",
        "score": 85,
        "products": ["Fresh fruit", "Vegetables"],
    }

    lead_id = database.save_lead(lead)
    saved_leads = database.get_all_leads()

    assert lead_id > 0
    assert len(saved_leads) == 1
    assert saved_leads[0]["company_name"] == "Example Importer"
    assert saved_leads[0]["score"] == 85


def test_saving_same_lead_does_not_duplicate_it(tmp_path, monkeypatch):
    monkeypatch.setattr(
        database,
        "DATABASE_PATH",
        tmp_path / "test_leads.db",
    )

    lead = {
        "company_name": "Example Importer",
        "website": "https://example.com",
        "score": 70,
    }

    database.save_lead(lead)
    lead["score"] = 90
    database.save_lead(lead)

    saved_leads = database.get_all_leads()

    assert len(saved_leads) == 1
    assert saved_leads[0]["score"] == 90
