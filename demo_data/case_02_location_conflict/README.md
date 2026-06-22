# Case 02 Location Conflict

This case plants a location conflict. Text and audio evidence say North Pier; image and video evidence say East Warehouse. Time and quantity are stable.

Files:
- `brief.txt` and `report.pdf`: parsed by the real document parser.
- `image.png`, `audio.wav`, `video.mp4`: real uploadable media files.
- `image.ocr.json`, `audio.asr.json`, `video.video.json`: MOCK media sidecars.
- `extraction.json`: deterministic MOCK extraction with `match` references.
- `expected.json`: evaluator labels.
