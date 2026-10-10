from datetime import datetime
from app.services.sm2_service import SM2Engine


def test_sm2_initial_review_success():
    """First successful review should set interval to 1 and reps to 1."""
    res = SM2Engine.calculate(quality=5, current_reps=0, current_interval=0, current_ease=2.5)
    assert res.reps == 1
    assert res.interval == 1
    assert res.ease >= 2.5


def test_sm2_second_review_success():
    """Second successful review should set interval to 6 and reps to 2."""
    res = SM2Engine.calculate(quality=4, current_reps=1, current_interval=1, current_ease=2.6)
    assert res.reps == 2
    assert res.interval == 6


def test_sm2_subsequent_review_multiplication():
    """Subsequent successful review scales interval by ease factor."""
    res = SM2Engine.calculate(quality=5, current_reps=2, current_interval=6, current_ease=2.5)
    assert res.reps == 3
    # interval should be round(6 * new_ease)
    assert res.interval >= 15


def test_sm2_failure_resets():
    """Quality below 3 resets reps to 0 and interval to 1."""
    res = SM2Engine.calculate(quality=2, current_reps=5, current_interval=30, current_ease=2.5)
    assert res.reps == 0
    assert res.interval == 1
    # Ease decreases but stays above 1.3
    assert res.ease >= 1.3


def test_sm2_ease_floor():
    """Ease factor should never drop below 1.3 even after multiple consecutive failures."""
    ease = 1.3
    for _ in range(5):
        res = SM2Engine.calculate(quality=0, current_reps=0, current_interval=1, current_ease=ease)
        ease = res.ease
        assert ease >= 1.3
