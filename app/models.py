from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CampaignRecord(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    alias: Mapped[str | None] = mapped_column(String(255), nullable=True)
    domain_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    group_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    streams: Mapped[list["StreamRecord"]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
    )


class StreamRecord(Base):
    __tablename__ = "streams"
    __table_args__ = (UniqueConstraint("campaign_id", "keitaro_id", name="uq_streams_campaign_keitaro"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    keitaro_id: Mapped[int]
    name: Mapped[str] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(default=0)
    offer_stream: Mapped[bool] = mapped_column(Boolean, default=False)
    dirty: Mapped[bool] = mapped_column(Boolean, default=False)
    published_json: Mapped[str] = mapped_column(Text, default="[]")

    campaign: Mapped[CampaignRecord] = relationship(back_populates="streams")
    bindings: Mapped[list["OfferBinding"]] = relationship(
        back_populates="stream",
        cascade="all, delete-orphan",
    )


class OfferBinding(Base):
    __tablename__ = "offer_bindings"
    __table_args__ = (UniqueConstraint("stream_id", "offer_id", name="uq_offer_bindings_stream_offer"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id", ondelete="CASCADE"), index=True)
    offer_id: Mapped[int]
    name: Mapped[str] = mapped_column(String(500))
    share: Mapped[int] = mapped_column(default=0)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="active")
    pending_add: Mapped[bool] = mapped_column(Boolean, default=False)

    stream: Mapped[StreamRecord] = relationship(back_populates="bindings")
