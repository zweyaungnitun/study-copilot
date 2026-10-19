from datetime import datetime, timedelta, timezone
import pytest
from pydantic import ValidationError

from app.schemas.intake import IntakeProfileRequest
from app.schemas.flashcard import FlashcardReviewRequest


def test_intake_deadline_validation():
    """Deadline must be in the future."""
    # Past deadline should fail
    with pytest.raises(ValidationError):
        IntakeProfileRequest(
            user_id="u123",
            goal="Master Linear Algebra",
            deadline=datetime.now(timezone.utc) - timedelta(days=2),
            hours_per_day=2.0,
        )

    # Valid future deadline passes
    req = IntakeProfileRequest(
        user_id="u123",
        goal="Master Linear Algebra",
        deadline=datetime.now(timezone.utc) + timedelta(days=30),
        hours_per_day=2.5,
    )
    assert req.hours_per_day == 2.5


def test_flashcard_review_score_range():
    """Quality rating must be between 0 and 5."""
    with pytest.raises(ValidationError):
        FlashcardReviewRequest(quality=6)

    with pytest.raises(ValidationError):
        FlashcardReviewRequest(quality=-1)

    valid = FlashcardReviewRequest(quality=4)
    assert valid.quality == 4
