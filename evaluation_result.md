# EviTrace M5 Demo Evaluation

## Summary JSON

```json
{
  "summary": {
    "case_count": 3,
    "all_completed": true,
    "overall_conflict_recall": 1.0,
    "min_citation_coverage": 1.0,
    "invalid_reference_count": 0,
    "uncited_fact_count": 0,
    "all_required_modalities": true
  },
  "cases": [
    {
      "case": "case_01_time_conflict",
      "task_id": "12083c28d5fd4d70a1d59c114cb8ad36",
      "task_status": "awaiting_review",
      "run_status": "succeeded",
      "expected_conflict_count": 1,
      "found_conflict_count": 1,
      "total_detected_conflicts": 1,
      "conflict_recall": 1.0,
      "report_reference_count": 6,
      "valid_reference_count": 6,
      "citation_coverage": 1.0,
      "invalid_reference_count": 0,
      "invalid_citations": [],
      "uncited_fact_count": 0,
      "uncited_sections": [],
      "modalities": [
        "audio",
        "image",
        "text",
        "video"
      ],
      "all_required_modalities": true,
      "matched_expected_conflicts": [
        {
          "type": "time",
          "left": "14:00",
          "right": "16:30"
        }
      ]
    },
    {
      "case": "case_02_location_conflict",
      "task_id": "d7c72a6c1f974b43bbb253ee87e1351a",
      "task_status": "awaiting_review",
      "run_status": "succeeded",
      "expected_conflict_count": 1,
      "found_conflict_count": 1,
      "total_detected_conflicts": 1,
      "conflict_recall": 1.0,
      "report_reference_count": 6,
      "valid_reference_count": 6,
      "citation_coverage": 1.0,
      "invalid_reference_count": 0,
      "invalid_citations": [],
      "uncited_fact_count": 0,
      "uncited_sections": [],
      "modalities": [
        "audio",
        "image",
        "text",
        "video"
      ],
      "all_required_modalities": true,
      "matched_expected_conflicts": [
        {
          "type": "location",
          "left": "North Pier",
          "right": "East Warehouse"
        }
      ]
    },
    {
      "case": "case_03_quantity_conflict",
      "task_id": "cffbf9227a2146f58d5031b195364da5",
      "task_status": "awaiting_review",
      "run_status": "succeeded",
      "expected_conflict_count": 1,
      "found_conflict_count": 1,
      "total_detected_conflicts": 1,
      "conflict_recall": 1.0,
      "report_reference_count": 5,
      "valid_reference_count": 5,
      "citation_coverage": 1.0,
      "invalid_reference_count": 0,
      "invalid_citations": [],
      "uncited_fact_count": 0,
      "uncited_sections": [],
      "modalities": [
        "audio",
        "image",
        "text",
        "video"
      ],
      "all_required_modalities": true,
      "matched_expected_conflicts": [
        {
          "type": "quantity",
          "left": "3 vehicles",
          "right": "5 vehicles"
        }
      ]
    }
  ]
}
```

## Case Table

| Case | Expected | Found | Recall | Report refs | Valid refs | Citation coverage | Invalid refs | Uncited facts | Four modalities |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| case_01_time_conflict | 1 | 1 | 1.00 | 6 | 6 | 1.00 | 0 | 0 | yes |
| case_02_location_conflict | 1 | 1 | 1.00 | 6 | 6 | 1.00 | 0 | 0 | yes |
| case_03_quantity_conflict | 1 | 1 | 1.00 | 5 | 5 | 1.00 | 0 | 0 | yes |

