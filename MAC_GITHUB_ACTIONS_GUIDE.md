# macOS Build Guide

This repository builds the human-only Otoscope Exam macOS app with GitHub
Actions. The video dataset is not uploaded to GitHub.

After a successful run, download the `otoscope_exam_mac` artifact from the
Actions page. It contains `otoscope_exam_mac.zip`.

For distribution, unzip the artifact, place the local `videos/` folder next to
the app inside `otoscope_exam_mac/`, and zip the final folder.

If macOS blocks the unsigned app, run:

```bash
xattr -dr com.apple.quarantine "/path/to/otoscope_exam_mac"
```

