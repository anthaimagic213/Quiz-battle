from sqlalchemy import Column, Integer, Float, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from uuid import uuid4
from app.db.base_class import BaseModel
1

class UserStats(BaseModel):
    """
    User aggregated statistics - domain: USER STATISTICS & ANALYTICS
    Denormalized cache of player performance metrics (updated after each game)
    Primary key is user_id (1:1 relationship with User)
    """
    __tablename__ = "user_stats"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    total_games = Column(Integer, default=0)
    total_score = Column(Integer, default=0)
    avg_score = Column(Float, default=0.0)
    wins = Column(Integer, default=0)

    user = relationship("User", back_populates="user_stats")
