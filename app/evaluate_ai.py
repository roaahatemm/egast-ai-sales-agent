
import json
from pathlib import Path

from app.local_ai_qualifier import qualify_lead


ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "data" / "ai_evaluation.jsonl"


def main():
    cases = []

    with DATASET.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                cases.append(json.loads(line))

    if not cases:
        print("The evaluation dataset is empty.")
        return

    correct = 0
    total = len(cases)

    for case in cases:
        case_id = case["case_id"]
        expected = case["expected_status"]

        print(f"\nTesting: {case_id}")

        try:
            result = qualify_lead(case["lead"])
            actual = result["buyer_status"]
            passed = actual == expected

            if passed:
                correct += 1

            print(f"Expected: {expected}")
            print(f"Actual:   {actual}")
            print(f"Result:   {'PASS' if passed else 'FAIL'}")
            print(f"Buyer type: {result['buyer_type']}")
            print(f"Confidence: {result['confidence']}")
            print(f"Reason: {result['qualification_reason']}")
            print(f"Evidence: {result['evidence']}")

        except Exception as exc:
            print(f"ERROR: {type(exc).__name__}: {exc}")
            print(f"Expected: {expected}")
            print("Result: FAIL")

    print("\n" + "=" * 45)
    print(f"Correct classifications: {correct}/{total}")
    print(f"Test-set accuracy: {correct / total:.0%}")
    print(
        "Note: this is a tiny development dataset, "
        "not a measure of real-world accuracy."
    )


if __name__ == "__main__":
    main()
