import csv
import json
import logging
import os
import random
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import imageio.v2 as imageio
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


CATEGORIES = [
    "AOM",
    "Effusion",
    "Normal",
    "Perforation",
    "Retraction",
    "Tubes",
    "Tympanosclerosis",
]
VIDEO_EXTENSIONS = {".mov", ".avi", ".mp4", ".mkv", ".wmv", ".m4v"}
MAX_FRAME_READ_ATTEMPTS = 30
FIXED_QUESTIONS_MANIFEST = "fixed_questions_100.json"
LOGGER_NAME = "otoscope_exam"

# Keep this as the internal question-count interface. None means use every video.
QUESTION_LIMIT = 100
BALANCE_CATEGORIES = True


@dataclass(frozen=True)
class VideoQuestion:
    video_id: str
    correct_answer: str
    path: Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        executable_path = Path(sys.executable).resolve()
        if (
            sys.platform == "darwin"
            and executable_path.parent.name == "MacOS"
            and executable_path.parent.parent.name == "Contents"
        ):
            return executable_path.parents[3]
        return executable_path.parent
    return Path(__file__).resolve().parent


def setup_diagnostics(root: Path) -> logging.Logger:
    result_path = root / "result"
    result_path.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = RotatingFileHandler(
            result_path / "application.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(threadName)s | %(message)s")
        )
        logger.addHandler(handler)

    def handle_exception(exc_type, exc_value, exc_traceback):
        logger.critical(
            "Uncaught exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    sys.excepthook = handle_exception
    logger.info("Application diagnostics initialized")
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def configure_bundled_ffmpeg(root: Path) -> None:
    if os.environ.get("IMAGEIO_FFMPEG_EXE"):
        return
    candidates = [
        root / "ffmpeg" / "ffmpeg",
        root / "ffmpeg" / "ffmpeg.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            os.environ["IMAGEIO_FFMPEG_EXE"] = str(candidate)
            get_logger().info("Using bundled ffmpeg: %s", candidate)
            return
    get_logger().warning("Bundled ffmpeg was not found under %s", root)


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned.strip("_") or "Subject"


def result_dir(root: Path) -> Path:
    path = root / "result"
    path.mkdir(exist_ok=True)
    return path


def relative_to_root(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def load_questions(root: Path) -> list[VideoQuestion]:
    manifest_path = root / FIXED_QUESTIONS_MANIFEST
    if manifest_path.exists():
        questions = load_fixed_questions(root, manifest_path)
        random.shuffle(questions)
        return questions

    videos_dir = root / "videos"
    if not videos_dir.exists():
        raise FileNotFoundError(f"Videos folder not found: {videos_dir}")

    questions_by_category: dict[str, list[VideoQuestion]] = {}
    missing_categories: list[str] = []
    for category in CATEGORIES:
        category_dir = videos_dir / category
        if not category_dir.exists():
            missing_categories.append(category)
            continue

        questions_by_category[category] = []
        for file_path in sorted(category_dir.rglob("*")):
            if file_path.is_file() and file_path.suffix.lower() in VIDEO_EXTENSIONS:
                questions_by_category[category].append(
                    VideoQuestion(
                        video_id=file_path.name,
                        correct_answer=category,
                        path=file_path,
                    )
                )

    if missing_categories:
        missing = ", ".join(missing_categories)
        raise FileNotFoundError(f"Missing category folders: {missing}")
    questions = [
        question
        for category_questions in questions_by_category.values()
        for question in category_questions
    ]
    if not questions:
        raise FileNotFoundError("No video files were found in the videos folder.")

    if QUESTION_LIMIT is not None and BALANCE_CATEGORIES:
        return select_balanced_questions(questions_by_category, QUESTION_LIMIT)

    random.shuffle(questions)
    if QUESTION_LIMIT is not None:
        questions = questions[: max(0, min(QUESTION_LIMIT, len(questions)))]
    return questions


def select_balanced_questions(
    questions_by_category: dict[str, list[VideoQuestion]],
    question_limit: int,
) -> list[VideoQuestion]:
    if question_limit <= 0:
        raise ValueError("Question limit must be greater than 0.")

    total_available = sum(len(items) for items in questions_by_category.values())
    if question_limit > total_available:
        raise ValueError(
            f"Question limit is larger than the available video count. "
            f"Requested: {question_limit}, Available: {total_available}."
        )

    category_count = len(CATEGORIES)
    base_count = question_limit // category_count
    remainder = question_limit % category_count
    extra_categories = set(random.sample(CATEGORIES, remainder))

    selected: list[VideoQuestion] = []
    for category in CATEGORIES:
        target_count = base_count + (1 if category in extra_categories else 0)
        category_questions = questions_by_category.get(category, [])
        if len(category_questions) < target_count:
            raise ValueError(
                f"Not enough videos in category {category}. "
                f"Required: {target_count}, Found: {len(category_questions)}."
            )
        selected.extend(random.sample(category_questions, target_count))

    random.shuffle(selected)
    return selected


def load_fixed_questions(root: Path, manifest_path: Path) -> list[VideoQuestion]:
    with manifest_path.open("r", encoding="utf-8") as file:
        items = json.load(file)
    if not isinstance(items, list) or len(items) != 100:
        raise ValueError(
            f"{FIXED_QUESTIONS_MANIFEST} must contain exactly 100 questions."
        )

    questions: list[VideoQuestion] = []
    seen_paths: set[str] = set()
    for index, item in enumerate(items, start=1):
        try:
            relative_path = item["relative_path"]
            video_id = item["video_id"]
            correct_answer = item["correct_answer"]
        except KeyError as exc:
            raise ValueError(
                f"Question {index} in {FIXED_QUESTIONS_MANIFEST} is missing {exc}."
            ) from exc
        if correct_answer not in CATEGORIES:
            raise ValueError(
                f"Question {index} has unknown category: {correct_answer}."
            )
        if relative_path in seen_paths:
            raise ValueError(f"Duplicate question path in manifest: {relative_path}")
        seen_paths.add(relative_path)
        path = root / relative_path
        if not path.exists():
            raise FileNotFoundError(f"Manifest video not found: {relative_path}")
        questions.append(
            VideoQuestion(
                video_id=video_id,
                correct_answer=correct_answer,
                path=path,
            )
        )
    return questions


def find_subject_sessions(root: Path, subject_name: str) -> list[Path]:
    prefix = f"session_{safe_filename(subject_name)}_S*.json"
    sessions = sorted(
        result_dir(root).glob(prefix),
        key=lambda path: path.stat().st_mtime,
    )
    return sessions


def read_session_summary(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    total = len(data.get("questions", []))
    answered = sum(1 for answer in data.get("answers", []) if answer)
    return {
        "path": path,
        "subject_id": data.get("subject_id", "Unknown"),
        "exam_date": data.get("exam_date", "Unknown"),
        "completed": bool(data.get("completed", False)),
        "answered": answered,
        "total": total,
    }


class StartPage(QWidget):
    def __init__(self, start_callback):
        super().__init__()
        self.start_callback = start_callback

        title = QLabel("Otoscope Exam")
        title.setObjectName("Title")
        subtitle = QLabel("Please enter your name before starting the exam.")
        subtitle.setObjectName("Subtitle")

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Name")
        self.name_input.setMinimumHeight(38)
        self.name_input.returnPressed.connect(self.start_exam)

        start_button = QPushButton("Start Exam")
        start_button.setMinimumHeight(40)
        start_button.clicked.connect(self.start_exam)

        form = QFrame()
        form.setObjectName("Panel")
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(28, 28, 28, 28)
        form_layout.setSpacing(16)
        form_layout.addWidget(title)
        form_layout.addWidget(subtitle)
        form_layout.addSpacing(10)
        form_layout.addWidget(QLabel("Name"))
        form_layout.addWidget(self.name_input)
        form_layout.addWidget(start_button)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.addWidget(form)

    def start_exam(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Name Required", "Please enter your name.")
            return
        self.start_callback(name)


class ResumeDialog(QMessageBox):
    def __init__(self, subject_name: str, sessions: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Previous Tests Found")
        self.setIcon(QMessageBox.Icon.Question)
        self.setText(f"Previous tests were found for {subject_name}.")
        self.setInformativeText(
            "Select a previous test to continue, or start a new test."
        )
        self.sessions = sessions
        self.selected_session: Path | None = None

        self.list_widget = QListWidget()
        for index, session in enumerate(sessions, start=1):
            status = "Completed" if session["completed"] else "In progress"
            label = (
                f"Test {index} - {session['exam_date']} - {status} - "
                f"{session['answered']} / {session['total']} answered"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, str(session["path"]))
            self.list_widget.addItem(item)
        if sessions:
            self.list_widget.setCurrentRow(len(sessions) - 1)
        self.layout().addWidget(self.list_widget, 1, 1)

        self.continue_button = self.addButton(
            "Continue Selected Test", QMessageBox.ButtonRole.AcceptRole
        )
        self.new_button = self.addButton(
            "Start New Test", QMessageBox.ButtonRole.ActionRole
        )
        self.cancel_button = self.addButton(
            "Cancel", QMessageBox.ButtonRole.RejectRole
        )

    def exec(self) -> int:
        result = super().exec()
        clicked = self.clickedButton()
        if clicked == self.continue_button:
            item = self.list_widget.currentItem()
            if item is not None:
                self.selected_session = Path(item.data(Qt.ItemDataRole.UserRole))
        return result


class VideoPlayer(QWidget):
    errorOccurred = Signal(str)

    def __init__(self):
        super().__init__()
        self.video_path: Path | None = None
        self.reader = None
        self.fps = 30.0
        self.playback_rate = 1.0
        self.playing = False
        self.frame_loaded = False

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.read_next_frame)

        self.video_label = QLabel("No video loaded")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(520, 260)
        self.video_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_label.setObjectName("VideoSurface")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.video_label)

    def load(self, video_path: Path):
        self.stop()
        self.close_reader()
        self.video_path = video_path
        try:
            self.reader = imageio.get_reader(str(video_path), format="ffmpeg")
            metadata = self.reader.get_meta_data()
        except Exception as exc:
            self.close_reader()
            self.video_label.setText("Video could not be opened.")
            self.errorOccurred.emit(f"Could not open video: {video_path.name}")
            get_logger().exception("Video player could not open %s: %s", video_path, exc)
            return

        fps = metadata.get("fps")
        self.fps = fps if fps and fps > 1 else 30.0
        self.frame_loaded = False
        get_logger().info("Video player opened with imageio video=%s fps=%s", video_path, self.fps)
        self.read_next_frame(startup=True)

    def play(self):
        if self.reader is None:
            if self.video_path is not None:
                self.load(self.video_path)
            else:
                self.errorOccurred.emit("No video is loaded.")
                return

        self.playing = True
        self.timer.start(self.timer_interval_ms())

    def pause(self):
        self.playing = False
        self.timer.stop()

    def stop(self):
        self.playing = False
        self.timer.stop()

    def replay(self):
        if self.video_path is None:
            self.errorOccurred.emit("No video is loaded.")
            return

        self.load(self.video_path)
        self.play()

    def set_rate(self, rate: float):
        self.playback_rate = rate
        if self.playing:
            self.timer.start(self.timer_interval_ms())

    def timer_interval_ms(self) -> int:
        return max(1, int(1000 / (self.fps * self.playback_rate)))

    def read_next_frame(self, startup: bool = False) -> bool:
        if self.reader is None:
            return False

        try:
            frame = self.reader.get_next_data()
        except IndexError:
            if self.frame_loaded:
                self.pause()
                return False
            self.pause()
            name = self.video_path.name if self.video_path else "current video"
            self.errorOccurred.emit(f"Could not read frames from video: {name}")
            return False
        except Exception as exc:
            self.pause()
            name = self.video_path.name if self.video_path else "current video"
            self.errorOccurred.emit(f"Video playback failed: {name}")
            get_logger().exception("Video player read failed for %s: %s", self.video_path, exc)
            return False

        self.frame_loaded = True
        if frame.ndim != 3 or frame.shape[2] < 3:
            self.pause()
            self.errorOccurred.emit("Video playback returned an unsupported frame format.")
            return False
        frame_rgb = frame[:, :, :3].copy()
        height, width, _ = frame_rgb.shape
        image = QImage(
            frame_rgb.data,
            width,
            height,
            frame_rgb.strides[0],
            QImage.Format.Format_RGB888,
        ).copy()
        pixmap = QPixmap.fromImage(image)
        scaled = pixmap.scaled(
            self.video_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.video_label.setPixmap(scaled)
        if startup:
            self.pause()
        return True

    def resizeEvent(self, event):
        super().resizeEvent(event)
        pixmap = self.video_label.pixmap()
        if pixmap is not None:
            self.video_label.setPixmap(
                pixmap.scaled(
                    self.video_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def close_reader(self):
        if self.reader is not None:
            try:
                self.reader.close()
            except Exception:
                pass
            self.reader = None

    def closeEvent(self, event):
        self.stop()
        self.close_reader()
        super().closeEvent(event)


class ExamPage(QWidget):
    def __init__(self, finish_callback):
        super().__init__()
        self.finish_callback = finish_callback
        self.root = app_root()
        self.subject_name = ""
        self.subject_id = ""
        self.exam_date = ""
        self.questions: list[VideoQuestion] = []
        self.answers: list[str | None] = []
        self.confidence_levels: list[int | None] = []
        self.current_index = 0
        self.furthest_index = 0
        self.completed = False
        self.result_path: Path | None = None
        self.session_path: Path | None = None

        self.build_ui()

    def build_ui(self):
        self.header_label = QLabel()
        self.header_label.setObjectName("Header")

        self.video_player = VideoPlayer()
        self.video_player.errorOccurred.connect(self.show_video_error)

        self.play_button = QPushButton("Play")
        self.pause_button = QPushButton("Pause")
        self.replay_button = QPushButton("Replay")
        self.download_button = QPushButton("Download Video")
        self.play_button.clicked.connect(self.video_player.play)
        self.pause_button.clicked.connect(self.video_player.pause)
        self.replay_button.clicked.connect(self.video_player.replay)
        self.download_button.clicked.connect(self.download_video)

        control_layout = QHBoxLayout()
        for button in (self.play_button, self.pause_button, self.replay_button):
            control_layout.addWidget(button)

        for rate in (0.5, 1.0, 1.5, 2.0):
            rate_button = QPushButton(f"{rate:g}x")
            rate_button.clicked.connect(lambda checked=False, r=rate: self.set_rate(r))
            control_layout.addWidget(rate_button)
        control_layout.addWidget(self.download_button)
        control_layout.addStretch()

        diagnosis_box = QGroupBox("Diagnosis")
        self.answer_group = QButtonGroup(self)
        self.answer_group.setExclusive(True)
        diagnosis_layout = QGridLayout(diagnosis_box)
        diagnosis_layout.setContentsMargins(10, 10, 10, 8)
        diagnosis_layout.setHorizontalSpacing(12)
        diagnosis_layout.setVerticalSpacing(2)
        for index, category in enumerate(CATEGORIES):
            radio = QRadioButton(category)
            self.answer_group.addButton(radio, index)
            row = index // 3
            column = index % 3
            diagnosis_layout.addWidget(radio, row, column)

        confidence_box = QGroupBox("Confidence Level")
        confidence_layout = QVBoxLayout(confidence_box)
        confidence_layout.setContentsMargins(10, 10, 10, 8)
        confidence_layout.setSpacing(3)
        confidence_prompt = QLabel("How confident are you in this answer?")
        confidence_prompt.setObjectName("Subtitle")
        confidence_help = QLabel("1 = Not confident at all    5 = Very confident")
        confidence_help.setObjectName("Subtitle")
        confidence_layout.addWidget(confidence_prompt)
        confidence_layout.addWidget(confidence_help)
        confidence_buttons_layout = QHBoxLayout()
        self.confidence_group = QButtonGroup(self)
        self.confidence_group.setExclusive(True)
        for level in range(1, 6):
            radio = QRadioButton(str(level))
            self.confidence_group.addButton(radio, level)
            confidence_buttons_layout.addWidget(radio)
        confidence_buttons_layout.addStretch()
        confidence_layout.addLayout(confidence_buttons_layout)

        self.back_button = QPushButton("Back")
        self.next_button = QPushButton("Next")
        self.new_question_button = QPushButton("Go to New Question")
        self.confirm_button = QPushButton("Confirm")
        self.back_button.clicked.connect(self.go_back)
        self.next_button.clicked.connect(self.go_next)
        self.new_question_button.clicked.connect(self.go_to_new_question)
        self.confirm_button.clicked.connect(self.confirm_answer)

        nav_layout = QHBoxLayout()
        nav_layout.addWidget(self.back_button)
        nav_layout.addWidget(self.next_button)
        nav_layout.addWidget(self.new_question_button)
        nav_layout.addStretch()
        nav_layout.addWidget(self.confirm_button)

        exam_content = QWidget()
        layout = QVBoxLayout(exam_content)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addWidget(self.header_label)
        layout.addWidget(self.video_player, stretch=1)
        layout.addLayout(control_layout)
        layout.addWidget(diagnosis_box)
        layout.addWidget(confidence_box)
        layout.addLayout(nav_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(exam_content)

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(8, 8, 8, 8)
        page_layout.addWidget(scroll)

    def start_exam(self, subject_name: str):
        self.root = app_root()
        self.subject_name = subject_name
        now = datetime.now()
        self.subject_id = f"S{now.strftime('%Y%m%d_%H%M%S')}"
        self.exam_date = now.strftime("%Y-%m-%d %H:%M:%S")
        self.questions = load_questions(self.root)
        self.answers = [None] * len(self.questions)
        self.confidence_levels = [None] * len(self.questions)
        self.current_index = 0
        self.furthest_index = 0
        self.completed = False
        self.result_path = self.make_result_path()
        self.session_path = self.make_session_path()
        self.save_progress()
        self.load_current_question()

    def resume_exam(self, session_path: Path):
        self.root = app_root()
        with session_path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        self.subject_name = data["subject_name"]
        self.subject_id = data["subject_id"]
        self.exam_date = data["exam_date"]
        self.answers = data["answers"]
        self.confidence_levels = data.get("confidence_levels", [None] * len(self.answers))
        if len(self.confidence_levels) != len(self.answers):
            self.confidence_levels = [None] * len(self.answers)
        self.current_index = min(data.get("current_index", 0), len(self.answers) - 1)
        self.furthest_index = min(
            data.get("furthest_index", self.current_index), len(self.answers) - 1
        )
        self.completed = bool(data.get("completed", False))
        self.session_path = session_path
        stored_result = data.get("result_path")
        self.result_path = self.root / stored_result if stored_result else self.make_result_path()

        self.questions = []
        for item in data["questions"]:
            path = self.root / item["relative_path"]
            self.questions.append(
                VideoQuestion(
                    video_id=item["video_id"],
                    correct_answer=item["correct_answer"],
                    path=path,
                )
            )
        self.save_progress()
        self.load_current_question()

    def make_result_path(self) -> Path:
        filename = (
            f"result_{safe_filename(self.subject_name)}_"
            f"{self.subject_id}.csv"
        )
        return result_dir(self.root) / filename

    def make_session_path(self) -> Path:
        filename = (
            f"session_{safe_filename(self.subject_name)}_"
            f"{self.subject_id}.json"
        )
        return result_dir(self.root) / filename

    def load_current_question(self):
        question = self.questions[self.current_index]
        self.video_player.set_rate(1.0)
        self.video_player.load(question.path)
        self.header_label.setText(
            f"Subject: {self.subject_name}      ID: {self.subject_id}      "
            f"Question {self.current_index + 1} / {len(self.questions)}"
        )
        self.restore_answer_selection()
        self.restore_confidence_selection()
        self.update_navigation_buttons()

    def restore_answer_selection(self):
        self.answer_group.setExclusive(False)
        for button in self.answer_group.buttons():
            button.setChecked(False)
        self.answer_group.setExclusive(True)

        answer = self.answers[self.current_index]
        if answer is None:
            return
        for button in self.answer_group.buttons():
            if button.text() == answer:
                button.setChecked(True)
                break

    def restore_confidence_selection(self):
        self.confidence_group.setExclusive(False)
        for button in self.confidence_group.buttons():
            button.setChecked(False)
        self.confidence_group.setExclusive(True)

        confidence = self.confidence_levels[self.current_index]
        if confidence is None:
            return
        button = self.confidence_group.button(int(confidence))
        if button is not None:
            button.setChecked(True)

    def selected_answer(self) -> str | None:
        button = self.answer_group.checkedButton()
        if button is None:
            return None
        return button.text()

    def selected_confidence(self) -> int | None:
        checked_id = self.confidence_group.checkedId()
        if checked_id < 1:
            return None
        return checked_id

    def update_navigation_buttons(self):
        self.back_button.setEnabled(self.current_index > 0)
        self.next_button.setEnabled(self.current_index < self.furthest_index)
        self.new_question_button.setEnabled(self.first_unanswered_index() is not None)

    def set_rate(self, rate: float):
        self.video_player.set_rate(rate)
        self.video_player.play()

    def go_back(self):
        if self.current_index <= 0:
            return
        self.current_index -= 1
        self.save_progress()
        self.load_current_question()

    def go_next(self):
        if self.current_index >= self.furthest_index:
            return
        self.current_index += 1
        self.save_progress()
        self.load_current_question()

    def go_to_new_question(self):
        index = self.first_unanswered_index()
        if index is None:
            return
        self.current_index = index
        self.furthest_index = max(self.furthest_index, self.current_index)
        self.save_progress()
        self.load_current_question()

    def confirm_answer(self):
        answer = self.selected_answer()
        if answer is None:
            QMessageBox.warning(
                self,
                "Answer Required",
                "Please select an answer before continuing.",
            )
            return
        confidence = self.selected_confidence()
        if confidence is None:
            QMessageBox.warning(
                self,
                "Confidence Required",
                "Please select your confidence level before continuing.",
            )
            return

        self.answers[self.current_index] = answer
        self.confidence_levels[self.current_index] = confidence
        if all(item is not None for item in self.answers):
            self.finish_exam()
            return

        next_index = self.current_index + 1
        first_unanswered = self.first_unanswered_index()
        if first_unanswered is not None and first_unanswered <= self.furthest_index:
            next_index = first_unanswered

        if next_index < len(self.questions):
            self.current_index = next_index
            self.furthest_index = max(self.furthest_index, self.current_index)
            self.save_progress()
            self.load_current_question()
        else:
            self.save_progress()
            self.go_to_new_question()

    def first_unanswered_index(self) -> int | None:
        for index, answer in enumerate(self.answers):
            if answer is None:
                return index
        return None

    def download_video(self):
        question = self.questions[self.current_index]
        target_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Video",
            str(Path.home() / question.video_id),
            f"Video Files (*{question.path.suffix});;All Files (*)",
        )
        if not target_path:
            return
        try:
            shutil.copy2(question.path, target_path)
        except OSError as exc:
            QMessageBox.critical(self, "Download Failed", str(exc))
            return
        QMessageBox.information(self, "Download Complete", "The video has been saved.")

    def finish_exam(self):
        self.video_player.stop()
        self.completed = True
        try:
            result_path = self.save_progress()
        except OSError as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))
            return
        self.finish_callback(result_path)

    def save_progress(self) -> Path:
        result_path = self.save_results()
        self.save_session()
        return result_path

    def save_results(self) -> Path:
        if self.result_path is None:
            self.result_path = self.make_result_path()
        result_path = self.result_path
        with result_path.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "Subject ID",
                    "Name",
                    "Date",
                    "Video ID",
                    "Correct Answer",
                    "Subject Answer",
                    "Confidence Level",
                ]
            )
            for question, answer, confidence in zip(
                self.questions, self.answers, self.confidence_levels
            ):
                writer.writerow(
                    [
                        self.subject_id,
                        self.subject_name,
                        self.exam_date,
                        question.video_id,
                        question.correct_answer,
                        answer or "",
                        confidence or "",
                    ]
                )
        return result_path

    def save_session(self):
        if self.session_path is None:
            self.session_path = self.make_session_path()
        if self.result_path is None:
            self.result_path = self.make_result_path()

        data = {
            "subject_name": self.subject_name,
            "subject_id": self.subject_id,
            "exam_date": self.exam_date,
            "current_index": self.current_index,
            "furthest_index": self.furthest_index,
            "completed": self.completed,
            "result_path": relative_to_root(self.result_path, self.root),
            "questions": [
                {
                    "video_id": question.video_id,
                    "correct_answer": question.correct_answer,
                    "relative_path": relative_to_root(question.path, self.root),
                }
                for question in self.questions
            ],
            "answers": self.answers,
            "confidence_levels": self.confidence_levels,
        }
        with self.session_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2)

    def show_video_error(self, error_string: str):
        QMessageBox.warning(
            self,
            "Video Playback Error",
            error_string or "The current video could not be played.",
        )


class CompletePage(QWidget):
    def __init__(self, exit_callback):
        super().__init__()
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        self.result_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        title = QLabel("Exam Completed")
        title.setObjectName("Title")
        message = QLabel("Your responses have been saved.")
        message.setObjectName("Subtitle")

        exit_button = QPushButton("Exit")
        exit_button.setMinimumHeight(38)
        exit_button.clicked.connect(exit_callback)

        panel = QFrame()
        panel.setObjectName("Panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(28, 28, 28, 28)
        panel_layout.setSpacing(16)
        panel_layout.addWidget(title)
        panel_layout.addWidget(message)
        panel_layout.addWidget(QLabel("Result file:"))
        panel_layout.addWidget(self.result_label)
        panel_layout.addWidget(exit_button)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.addWidget(panel)

    def set_result_path(self, result_path: Path):
        self.result_label.setText(str(result_path))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Otoscope Exam")
        self.resize(1040, 760)

        self.stack = QStackedWidget()
        self.start_page = StartPage(self.start_exam)
        self.exam_page = ExamPage(self.finish_exam)
        self.complete_page = CompletePage(QApplication.instance().quit)
        self.stack.addWidget(self.start_page)
        self.stack.addWidget(self.exam_page)
        self.stack.addWidget(self.complete_page)
        self.setCentralWidget(self.stack)

    def start_exam(self, subject_name: str):
        sessions = []
        for session_path in find_subject_sessions(app_root(), subject_name):
            try:
                sessions.append(read_session_summary(session_path))
            except (OSError, json.JSONDecodeError, KeyError):
                continue

        if sessions:
            dialog = ResumeDialog(subject_name, sessions, self)
            dialog.exec()
            clicked = dialog.clickedButton()
            if clicked == dialog.cancel_button:
                return
            if clicked == dialog.continue_button and dialog.selected_session is not None:
                try:
                    self.exam_page.resume_exam(dialog.selected_session)
                except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
                    QMessageBox.critical(self, "Cannot Resume Exam", str(exc))
                    return
                self.stack.setCurrentWidget(self.exam_page)
                return

        try:
            self.exam_page.start_exam(subject_name)
        except (FileNotFoundError, ValueError) as exc:
            QMessageBox.critical(self, "Cannot Start Exam", str(exc))
            return
        self.stack.setCurrentWidget(self.exam_page)

    def finish_exam(self, result_path: Path):
        self.complete_page.set_result_path(result_path)
        self.stack.setCurrentWidget(self.complete_page)


def apply_styles(app: QApplication):
    app.setStyleSheet(
        """
        QWidget {
            font-family: Segoe UI, Arial, sans-serif;
            font-size: 14px;
            color: #1f2933;
            background: #f5f7fa;
        }
        #Title {
            font-size: 30px;
            font-weight: 700;
        }
        #Subtitle {
            color: #53616f;
        }
        #Header {
            font-size: 16px;
            font-weight: 600;
        }
        #VideoSurface {
            background: #111820;
            color: #dce6f0;
            border: 1px solid #202a34;
            border-radius: 4px;
        }
        #Panel, QGroupBox {
            background: #ffffff;
            border: 1px solid #d8dee6;
            border-radius: 6px;
        }
        QGroupBox {
            margin-top: 12px;
            padding: 12px;
            font-weight: 600;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 4px;
        }
        QLineEdit {
            background: #ffffff;
            border: 1px solid #b9c2cc;
            border-radius: 4px;
            padding: 7px 9px;
        }
        QPushButton {
            background: #ffffff;
            border: 1px solid #aeb8c4;
            border-radius: 4px;
            padding: 8px 14px;
            min-width: 70px;
        }
        QPushButton:hover {
            background: #eef3f8;
        }
        QPushButton:pressed {
            background: #dce6f0;
        }
        QPushButton:disabled {
            color: #9aa6b2;
            background: #edf0f3;
            border-color: #d3d9df;
        }
        QRadioButton {
            padding: 6px 10px;
            font-weight: 400;
        }
        """
    )


def main():
    root = app_root()
    setup_diagnostics(root)
    configure_bundled_ffmpeg(root)
    app = QApplication(sys.argv)
    apply_styles(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
