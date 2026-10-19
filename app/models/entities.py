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
    flashcards = relationship("Flashcard", back_populates="chapter", cascade="all, delete-orphan")
    notes = relationship("Note", back_populates="chapter", uselist=False, cascade="all, delete-orphan")
    mistakes = relationship("MistakeRecord", back_populates="chapter")


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


class Flashcard(Base):
    __tablename__ = "flashcards"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    chapter_id = Column(String(36), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(20), default="qa")  # qa, cloze, truefalse
    front = Column(Text, nullable=False)
    back = Column(Text, nullable=False)
    source = Column(String(50), default="ai_generated")  # "user_notes" | "ai_generated"
    source_citation = Column(String(255), nullable=True)

    # SM-2 Algorithm State
    reps = Column(Integer, default=0)
    ease = Column(Float, default=2.5)
    interval = Column(Integer, default=0)
    next_review = Column(DateTime, default=utcnow, index=True)
    last_quality = Column(Integer, nullable=True)

    chapter = relationship("Chapter", back_populates="flashcards")
    reviews = relationship("CardReview", back_populates="flashcard", cascade="all, delete-orphan")


class CardReview(Base):
    __tablename__ = "card_reviews"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    flashcard_id = Column(String(36), ForeignKey("flashcards.id", ondelete="CASCADE"), nullable=False, index=True)
    quality = Column(Integer, nullable=False)
    reviewed_at = Column(DateTime, default=utcnow)
    interval_before = Column(Integer, default=0)
    interval_after = Column(Integer, default=0)
    ease_before = Column(Float, default=2.5)
    ease_after = Column(Float, default=2.5)

    flashcard = relationship("Flashcard", back_populates="reviews")


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
    file_path = Column(String(512), nullable=False)
    file_type = Column(String(50), nullable=False)
    file_size_bytes = Column(Integer, default=0)
    chunk_count = Column(Integer, default=0)
    status = Column(String(50), default="processed")  # pending, processing, processed, failed
    created_at = Column(DateTime, default=utcnow)

    user = relationship("User", back_populates="materials")
