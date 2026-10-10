from datetime import datetime, timedelta
from typing import NamedTuple


class SM2Result(NamedTuple):
    reps: int
    interval: int  # in days
    ease: float
    next_review: datetime


class SM2Engine:
    """SuperMemo SM-2 Spaced Repetition Algorithm Implementation.

    Formulas:
        EF' = EF + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
        EF' = max(1.3, EF')

        If q < 3 (failure):
            reps = 0
            interval = 1
        Else (success):
            If reps == 0: interval = 1
            Elif reps == 1: interval = 6
            Else: interval = round(interval * EF')
            reps = reps + 1
    """

    MIN_EASE: float = 1.3
    DEFAULT_EASE: float = 2.5

    @classmethod
    def calculate(
        cls,
        quality: int,
        current_reps: int = 0,
        current_interval: int = 0,
        current_ease: float = 2.5,
        review_time: datetime = None,
    ) -> SM2Result:
        """Calculate next review schedule based on quality score (0 to 5)."""
        if review_time is None:
            review_time = datetime.utcnow()

        # Clamp quality to 0..5
        q = max(0, min(5, quality))

        # Calculate new Ease Factor
        # EF' = EF + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
        delta = 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)
        new_ease = max(cls.MIN_EASE, current_ease + delta)

        if q < 3:
            # Memory lapsed, reset repetition cycle
            new_reps = 0
            new_interval = 1
        else:
            # Successful recall
            if current_reps == 0:
                new_interval = 1
            elif current_reps == 1:
                new_interval = 6
            else:
                new_interval = max(1, round(current_interval * new_ease))
            new_reps = current_reps + 1

        next_review = review_time + timedelta(days=new_interval)
        return SM2Result(
            reps=new_reps,
            interval=new_interval,
            ease=round(new_ease, 3),
            next_review=next_review,
        )
