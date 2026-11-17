from datetime import datetime

from sqlalchemy import String, ForeignKey, DateTime, Text, Float, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pgvector.sqlalchemy import Vector

from app.db.base import Base


class Reflection(Base):
    __tablename__ = "reflections"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    content: Mapped[str] = mapped_column(Text)

    importance: Mapped[float] = mapped_column(
        Float,
        default=1.0,
        nullable=False,
    )

    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    embedding: Mapped[list[float]] = mapped_column(
        Vector(1024),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now
    )

    # Relationship back to the junction table, NOT directly to memories
    memory_links: Mapped[list["ReflectionMemoryLink"]] = relationship(
        back_populates="reflection",
        cascade="all, delete-orphan",
    )


class ReflectionMemoryLink(Base):
    __tablename__ = "reflection_memory_links"

    reflection_id: Mapped[int] = mapped_column(
        ForeignKey("reflections.id", ondelete="CASCADE"),
        primary_key=True,
    )

    memory_id: Mapped[int] = mapped_column(
        ForeignKey("memories.id", ondelete="RESTRICT"),
        primary_key=True,
    )

    reflection = relationship(
        "Reflection",
        back_populates="memory_links",
    )