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
      "task_id": "e7824d307be04070b85ff0b455d73871",
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
      "task_id": "44c6b3e9b3be4100af52cf898ea653cf",
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
      "task_id": "389836f85bca4f8798294fe4f82dc357",
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

