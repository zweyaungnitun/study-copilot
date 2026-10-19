from typing import List
from pydantic import BaseModel


class LeaderboardEntry(BaseModel):
    rank: int
    user_id: str
    username: str
    streak_days: int
    sessions_completed: int
    consistency_score: int


class LeaderboardResponse(BaseModel):
    total_participants: int
    rankings: List[LeaderboardEntry]
