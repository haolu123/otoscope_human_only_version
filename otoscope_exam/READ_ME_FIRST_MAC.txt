Otoscope Exam for macOS

Run:
Double-click Otoscope Exam.app.

Expected folder structure:

otoscope_exam_mac/
- Otoscope Exam.app
- videos/
  - AOM/
  - Effusion/
  - Normal/
  - Perforation/
  - Retraction/
  - Tubes/
  - Tympanosclerosis/
- result/

If the videos folder only contains PUT_VIDEOS_HERE.txt, copy the real videos
folder into otoscope_exam_mac before running the app.

If macOS blocks the app because it is unsigned, open Terminal and run:

xattr -dr com.apple.quarantine "/path/to/otoscope_exam_mac"

Then double-click Otoscope Exam.app again.

