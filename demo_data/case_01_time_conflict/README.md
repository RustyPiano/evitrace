# Case 01 Time Conflict

This case plants a time conflict. Text and image evidence say 14:00; audio and video evidence say 16:30. Other fields are held constant.

Files:
- `brief.txt` and `report.pdf`: parsed by the real document parser.
- `image.png`, `audio.wav`, `video.mp4`: real uploadable media files.
- `image.ocr.json`, `audio.asr.json`, `video.video.json`: MOCK media sidecars.
- `extraction.json`: deterministic MOCK extraction with `match` references.
- `expected.json`: evaluator labels.
