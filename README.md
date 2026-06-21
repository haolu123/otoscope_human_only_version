# Otoscope Exam

Windows desktop exam application for otoscope videos.

## Run

Double-click:

```text
otoscope_exam.exe
```

The expected directory structure is:

```text
otoscope_exam/
├─ otoscope_exam.exe
├─ videos/
│  ├─ AOM/
│  ├─ Effusion/
│  ├─ Normal/
│  ├─ Perforation/
│  ├─ Retraction/
│  ├─ Tubes/
│  └─ Tympanosclerosis/
└─ result/
```

Results are saved automatically to `result/` as CSV files.
Progress is also saved automatically in `result/` as session JSON files, so an
unfinished test can be resumed later by entering the same name.

## Build

The conda environment is named `otoscope_exam`.
It uses Python 3.11, PySide6 6.7.3, and OpenCV for video playback.

```powershell
.\build_exe.ps1
```

## Question Count

By default, the exam uses 100 videos with category-balanced sampling. The 100
questions are distributed as evenly as possible across the 7 categories.

```python
QUESTION_LIMIT = 100
BALANCE_CATEGORIES = True
```

To use every video instead:

```python
QUESTION_LIMIT = None
BALANCE_CATEGORIES = False
```
