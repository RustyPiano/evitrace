# Case 03 Quantity Conflict

This case plants a quantity conflict. Text and image evidence say 3 vehicles; audio and video evidence say 5 vehicles. Time and location are stable.

Files:
- `brief.txt` and `report.pdf`: parsed by the real document parser.
- `image.png`, `audio.wav`, `video.mp4`: real uploadable media files.
- `image.ocr.json`, `audio.asr.json`, `video.video.json`, `*.caption.json`: MOCK media sidecars.
- `extraction.json`: deterministic MOCK extraction with `match` references.
- `expected.json`: evaluator labels.
