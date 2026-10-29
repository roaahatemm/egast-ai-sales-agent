
from app.database import (
    DATABASE_PATH,
    save_lead,
    save_ai_qualification,
    get_all_leads,
)
from app.local_ai_qualifier import qualify_lead


def main():
    test_lead = {
        "company_name": "EGAST Temporary AI Integration Test",
        "website": "https://ai-integration-test.invalid",
        "source_url": "https://ai-integration-test.invalid",
        "description": (
            "Test data only. This fictional company description says "
            "it imports fresh oranges and distributes them to wholesalers."
        ),
        "country": "Germany",
        "industry": "Fresh Produce Importer",
        "products": ["oranges"],
        "score": 50,
        "discovered_links": [],
    }

    # Create one temporary record in the existing database.
    lead_id = save_lead(test_lead)

    try:
        # Ask the local AI model to qualify the lead.
        qualification = qualify_lead(test_lead)

        print("\nAI qualification:")
        print(qualification)

        # Save the AI result to the existing database.
        save_ai_qualification(
            lead_id,
            qualification=qualification,
        )

        # Retrieve the same lead to verify database persistence.
        saved_lead = next(
            (
                lead
                for lead in get_all_leads()
                if lead["id"] == lead_id
            ),
            None,
        )

        assert saved_lead is not None, (
            "The temporary test lead could not be retrieved."
        )

        print("\nSaved database values:")

        fields_to_check = (
            "company_name",
            "buyer_status",
            "buyer_type",
            "products_of_interest",
            "target_country",
            "ai_confidence",
            "recommended_next_action",
            "ai_qualification_error",
        )

        for field in fields_to_check:
            print(f"{field}: {saved_lead.get(field)}")

        # Check that the AI result was saved correctly.
        assert (
            saved_lead["buyer_status"]
            == qualification["buyer_status"]
        ), "Buyer status was not saved correctly."

        assert (
            saved_lead["buyer_type"]
            == qualification["buyer_type"]
        ), "Buyer type was not saved correctly."

        assert (
            saved_lead["ai_confidence"]
            == qualification["confidence"]
        ), "AI confidence was not saved correctly."

        # This test record explicitly describes a fictional company.
        # It must not be treated as a confirmed real-world buyer.
        assert qualification["buyer_status"] == "uncertain", (
            "A fictional test lead must remain uncertain."
        )

        assert qualification["is_company"] is False, (
            "The fictional test lead must not be classified "
            "as a real company."
        )

        assert qualification["buyer_type"] == "unknown", (
            "The fictional test lead must have an unknown buyer type."
        )

        assert (
            qualification["recommended_next_action"]
            in ("investigate_website", "review_lead")
        ), "The fictional test lead must not be sent directly to outreach."

        print(
            "\nPASS: Database persistence and "
            "fictional-lead safeguards passed."
        )

    finally:
        # Delete only this temporary test record.
        # Do not reset or delete the database.
        import sqlite3

        with sqlite3.connect(DATABASE_PATH) as connection:
            connection.execute(
                "DELETE FROM leads WHERE id = ?",
                (lead_id,),
            )

        print("Temporary test lead removed.")


if __name__ == "__main__":
    main()
