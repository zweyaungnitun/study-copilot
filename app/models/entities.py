import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    JSON,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


def utcnow() -> datetime:
    """Return timezone-naive UTC timestamp for DB compatibility."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def generate_uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True, index=True)
    password_hash = Column(String(255), nullable=True)
    role = Column(String(20), nullable=False, default="student", server_default="student")  # student, admin
    token_limit = Column(Integer, nullable=True)  # monthly LLM token budget; None = platform default, 0 = unlimited
    storage_page_limit = Column(Integer, nullable=True)  # pages across all materials; None = default, 0 = unlimited
    created_at = Column(DateTime, default=utcnow)

    # Relationships
    profile = relationship("UserProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    roadmaps = relationship("Roadmap", back_populates="user", cascade="all, delete-orphan")
    sessions = relationship("StudySession", back_populates="user", cascade="all, delete-orphan")
    mistakes = relationship("MistakeRecord", back_populates="user", cascade="all, delete-orphan")
    materials = relationship("MaterialUpload", back_populates="user", cascade="all, delete-orphan")


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    goal = Column(String(255), nullable=False)
    deadline = Column(DateTime, nullable=False)
    hours_per_day = Column(Float, nullable=False, default=2.0)
    level = Column(String(50), nullable=False, default="beginner")  # beginner, intermediate, advanced
    learning_style = Column(JSON, default=list)  # ["reading", "practice", "video"]
    language = Column(String(10), default="en")  # "en", "my", etc.
    preferred_study_time = Column(String(20), default="evening")  # morning, afternoon, evening
    weak_areas = Column(JSON, default=list)
    current_streak = Column(Integer, default=0)
    total_xp = Column(Integer, default=0)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="profile")


class Roadmap(Base):
    __tablename__ = "roadmaps"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    specialization = Column(String(255), nullable=False)
    total_estimated_hours = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, default=utcnow)
    is_active = Column(Boolean, default=True)

    user = relationship("User", back_populates="roadmaps")
    subjects = relationship("Subject", back_populates="roadmap", cascade="all, delete-orphan", order_by="Subject.order_index")


class Subject(Base):
    __tablename__ = "subjects"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    roadmap_id = Column(String(36), ForeignKey("roadmaps.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    order_index = Column(Integer, default=0)

    roadmap = relationship("Roadmap", back_populates="subjects")
    chapters = relationship("Chapter", back_populates="subject", cascade="all, delete-orphan")


class Chapter(Base):
    __tablename__ = "chapters"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    subject_id = Column(String(36), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    estimated_hours = Column(Float, default=1.0)
    prerequisites = Column(JSON, default=list)  # List of chapter IDs
    resources = Column(JSON, default=list)      # [{type, label, url}]
    status = Column(String(20), default="locked")  # locked, unlocked, in_progress, completed
    mastery_score = Column(Float, default=0.0)     # 0.0 to 100.0
    last_reviewed_at = Column(DateTime, nullable=True)

    subject = relationship("Subject", back_populates="chapters")
    notes = relationship("Note", back_populates="chapter", uselist=False, cascade="all, delete-orphan")
    guide = relationship("ChapterGuide", back_populates="chapter", uselist=False, cascade="all, delete-orphan")
    mistakes = relationship("MistakeRecord", back_populates="chapter")


class ChapterGuide(Base):
    """Structured learning content for a chapter. Its links live in ``Chapter.resources``."""
    __tablename__ = "chapter_guides"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    chapter_id = Column(String(36), ForeignKey("chapters.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    overview = Column(Text, nullable=False, default="")
    objectives = Column(JSON, default=list)   # ["Explain ...", ...]
    lesson_steps = Column(JSON, default=list)  # [{title, minutes, activity}]
    practice = Column(JSON, default=list)      # ["Exercise ...", ...]
    created_at = Column(DateTime, default=utcnow)

    chapter = relationship("Chapter", back_populates="guide")


class Note(Base):
    __tablename__ = "notes"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    chapter_id = Column(String(36), ForeignKey("chapters.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    simple_content = Column(Text, nullable=False)
    detailed_content = Column(Text, nullable=False)
    exam_content = Column(Text, nullable=False)
    cheat_sheet = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    chapter = relationship("Chapter", back_populates="notes")


class MistakeRecord(Base):
    __tablename__ = "mistake_records"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_id = Column(String(36), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, index=True)
    question = Column(Text, nullable=False)
    student_answer = Column(Text, nullable=False)
    correct_answer = Column(Text, nullable=False)
    misconception_tag = Column(String(100), nullable=True)
    explanation = Column(Text, nullable=False)
    retest_date = Column(DateTime, nullable=False, index=True)
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)

    user = relationship("User", back_populates="mistakes")
    chapter = relationship("Chapter", back_populates="mistakes")


class StudySession(Base):
    __tablename__ = "study_sessions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    energy_level = Column(String(20), default="ok")  # low, ok, high
    duration_minutes = Column(Integer, default=0)
    cards_reviewed = Column(Integer, default=0)
    cards_correct = Column(Integer, default=0)
    tasks_completed = Column(JSON, default=list)
    created_at = Column(DateTime, default=utcnow)

    user = relationship("User", back_populates="sessions")


class MaterialUpload(Base):
    __tablename__ = "material_uploads"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(512), nullable=False)  # storage key (local path or object key)
    file_type = Column(String(50), nullable=False)
    file_size_bytes = Column(Integer, default=0)
    chunk_count = Column(Integer, default=0)
    # pending -> extracting -> outlining -> embedding -> ready | failed
    status = Column(String(50), default="pending")
    sha256 = Column(String(64), nullable=True, index=True)
    page_count = Column(Integer, default=0)
    progress = Column(Integer, default=0)       # 0-100 within the whole pipeline
    error = Column(Text, nullable=True)
    embed_model = Column(String(100), nullable=True)
    ocr_pages = Column(Integer, default=0)
    outline_source = Column(String(20), nullable=True)  # bookmarks, headings, markdown, llm, pages
    created_at = Column(DateTime, default=utcnow)
    processed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="materials")
    sections = relationship("MaterialSection", back_populates="material", cascade="all, delete-orphan",
                            order_by="MaterialSection.order")


class MaterialSection(Base):
    """One node of a material's outline (from bookmarks, detected headings, or LLM segmentation)."""
    __tablename__ = "material_sections"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    material_id = Column(String(36), ForeignKey("material_uploads.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id = Column(String(36), nullable=True)
    level = Column(Integer, default=1)
    order = Column(Integer, default=0)
    title = Column(String(300), nullable=False)
    page_start = Column(Integer, default=1)
    page_end = Column(Integer, default=1)
    word_count = Column(Integer, default=0)
    summary = Column(Text, nullable=True)
    key_concepts = Column(JSON, default=list)

    material = relationship("MaterialUpload", back_populates="sections")


class ChapterSource(Base):
    """Links a roadmap chapter to the material sections it covers (grounds notes, cards, exams, tutor)."""
    __tablename__ = "chapter_sources"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    chapter_id = Column(String(36), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, index=True)
    section_id = Column(String(36), ForeignKey("material_sections.id", ondelete="CASCADE"), nullable=False, index=True)
    material_id = Column(String(36), nullable=False, index=True)
    page_start = Column(Integer, nullable=True)
    page_end = Column(Integer, nullable=True)


class ScheduledTask(Base):
    """One block of a learner's day, produced by the deterministic scheduler."""
    __tablename__ = "scheduled_tasks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    roadmap_id = Column(String(36), nullable=True, index=True)
    chapter_id = Column(String(36), nullable=True, index=True)
    date = Column(DateTime, nullable=False, index=True)  # the day (00:00 UTC)
    order = Column(Integer, default=0)
    kind = Column(String(20), nullable=False)  # learn, review, practice, buffer, mock
    title = Column(String(300), nullable=False)
    minutes = Column(Integer, default=0)
    status = Column(String(20), default="pending")  # pending, done, skipped, missed
    created_at = Column(DateTime, default=utcnow)


class ChatSession(Base):
    """A saved conversation with the AI tutor or the roadmap advisor."""
    __tablename__ = "chat_sessions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(20), nullable=False, default="tutor")  # tutor, roadmap
    chapter_id = Column(String(36), nullable=True)
    title = Column(String(120), nullable=False, default="New chat")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow)

    messages = relationship(
        "ChatMessage", back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.created_at"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    session_id = Column(String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(10), nullable=False)  # user, ai
    content = Column(Text, nullable=False)
    meta = Column(JSON, default=dict)  # badges, follow-up, suggestions, proposal, applied ...
    created_at = Column(DateTime, default=utcnow)

    session = relationship("ChatSession", back_populates="messages")


class TokenUsage(Base):
    """One metered LLM call (generation, stream, embedding or agent turn)."""
    __tablename__ = "token_usage"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    feature = Column(String(50), nullable=False, default="other")  # API area that made the call: tutor, roadmap ...
    model = Column(String(100), nullable=False, default="")
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    thinking_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow, index=True)


class AppSetting(Base):
    """Platform settings an admin can change at runtime (e.g. the default token quota)."""
    __tablename__ = "app_settings"

    key = Column(String(100), primary_key=True)
    value = Column(JSON, nullable=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class ExamAttempt(Base):
    """A mock exam sitting: the answer key stays server-side; proctoring state is tracked live."""
    __tablename__ = "exam_attempts"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    question_count = Column(Integer, default=0)
    time_limit_minutes = Column(Integer, default=30)
    is_exam_mode = Column(Boolean, default=False)
    answer_key = Column(JSON, default=dict)      # question_id -> correct option index
    question_meta = Column(JSON, default=dict)   # question_id -> {chapter_id, chapter_title}
    status = Column(String(20), default="in_progress", index=True)  # in_progress, submitted, terminated
    started_at = Column(DateTime, default=utcnow, index=True)
    submitted_at = Column(DateTime, nullable=True)
    score = Column(Integer, nullable=True)
    percentage = Column(Float, nullable=True)
    # Proctoring
    integrity_score = Column(Integer, default=100)  # 100 minus weighted violations
    flag_count = Column(Integer, default=0)
    last_heartbeat_at = Column(DateTime, nullable=True)
    pending_warning = Column(Text, nullable=True)   # admin message not yet delivered to the student
    termination_reason = Column(Text, nullable=True)
    review_verdict = Column(String(20), nullable=True)  # cleared, confirmed
    review_note = Column(Text, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)

    user = relationship("User")
    events = relationship("ProctorEvent", back_populates="attempt", cascade="all, delete-orphan",
                          order_by="ProctorEvent.created_at")


class ProctorEvent(Base):
    __tablename__ = "proctor_events"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    attempt_id = Column(String(36), ForeignKey("exam_attempts.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(40), nullable=False)  # tab_hidden, window_blur, fullscreen_exit, copy, paste, admin_warning ...
    detail = Column(String(500), nullable=True)
    weight = Column(Integer, default=0)        # integrity points deducted
    created_at = Column(DateTime, default=utcnow)

    attempt = relationship("ExamAttempt", back_populates="events")
