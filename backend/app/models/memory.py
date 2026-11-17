from datetime import datetime

from sqlalchemy import String, ForeignKey, DateTime, Text, Float, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pgvector.sqlalchemy import Vector

from app.db.base import Base


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id"),
        nullable=True
    )

    content: Mapped[str] = mapped_column(Text)

    memory_type: Mapped[str] = mapped_column(
        String,
        default="general"
    )

    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1024),
        nullable=True
    )

    salience: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
    )

    importance: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
    )

    retrieval_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    last_accessed: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now
    )

    conversation = relationship(
        "Conversation",
        back_populates="memories"
    )
