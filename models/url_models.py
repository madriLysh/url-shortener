import secrets
from datetime import datetime
from typing import List, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.database import Base


class URL(Base):
    __tablename__ = "urls"

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    short_code: Mapped[str] = mapped_column(String(10), nullable=False)
    long_url: Mapped[str] = mapped_column(Text, nullable=False)
    creator_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    click_count: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    edit_token: Mapped[str] = mapped_column(
        String(32),
        unique=True,
        nullable=False,
        default=lambda: secrets.token_urlsafe(16))

    clicks: Mapped[List["Click"]] = relationship(
        back_populates="url", cascade="all, delete"
    )
    referrer_stats: Mapped[List["ReferrerState"]] = relationship(
        back_populates="url", cascade="all, delete"
    )

    __table_args__ = (
        Index("ix_urls_short_code_active", "short_code", "is_active"),
        # Only *active* short codes must be unique; deleted codes may be reused.
        Index(
            "ix_urls_short_code_active_unique",
            "short_code",
            unique=True,
            postgresql_where=is_active.is_(True),
            sqlite_where=is_active.is_(True),
        ),
    )

    def __repr__(self) -> str:
        return f"<URL(id={self.id}, short_code={self.short_code}, long_url={self.long_url})>"


class Click(Base):
    __tablename__ = "clicks"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    url_id: Mapped[int] = mapped_column(ForeignKey("urls.id", ondelete="CASCADE"), nullable=False)
    clicked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    referrer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    country_code: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)

    url: Mapped["URL"] = relationship(back_populates="clicks")

    __table_args__ = (
        Index("ix_clicks_url_id_clicked_at", "url_id", "clicked_at"),
    )

    def __repr__(self) -> str:
        return f"<Click(id={self.id}, url_id={self.url_id}, clicked_at={self.clicked_at})>"


class ReferrerState(Base):
    __tablename__ = "referrer_stats"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    url_id: Mapped[int] = mapped_column(ForeignKey("urls.id", ondelete="CASCADE"), nullable=False)
    referrer_domain: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    click_count: Mapped[int] = mapped_column(default=1)
    last_clicked: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())

    url: Mapped["URL"] = relationship(back_populates="referrer_stats")

    __table_args__ = (
        Index("ix_referrer_stats_url_id_referrer_domain", "url_id", "referrer_domain"),
    )

    def __repr__(self) -> str:
        return (
            f"<ReferrerState(id={self.id}, url_id={self.url_id}, "
            f"referrer_domain={self.referrer_domain})>"
        )
