"""SQLAlchemy table models (persistence layer).

These mirror :mod:`wattly.core.models` dataclasses; repositories convert
between the two worlds. Money is always integer minor units (cents).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Table,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class DocumentRow(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    sha256 = Column(String(64), unique=True, nullable=False, index=True)
    original_filename = Column(String(255), nullable=False)
    stored_path = Column(String(512), nullable=False)
    mime_type = Column(String(100))
    page_count = Column(Integer)
    ocr_used = Column(Boolean, default=False)
    uploaded_at = Column(DateTime, default=utcnow)


class BillRow(Base):
    __tablename__ = "bills"

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    provider_name = Column(String(120), default="", index=True)
    account_number = Column(String(60))
    pod_identifier = Column(String(30))
    issue_date = Column(Date)
    billing_period_start = Column(Date, index=True)
    billing_period_end = Column(Date)
    total_amount_cents = Column(Integer)
    currency = Column(String(3), default="EUR")
    total_kwh = Column(Float)
    avg_daily_kwh = Column(Float)
    avg_cost_per_kwh = Column(Float)
    effective_total_cost_per_kwh = Column(Float)
    fixed_charges_cents = Column(Integer)
    energy_charges_cents = Column(Integer)
    taxes_and_fees_cents = Column(Integer)
    previous_reading = Column(Float)
    current_reading = Column(Float)
    reading_start_date = Column(Date)
    reading_end_date = Column(Date)
    tariff_type = Column(String(60))
    parse_method = Column(String(30), default="manual")
    parse_confidence = Column(Float)
    field_sources = Column(JSON, default=dict)
    notes = Column(Text, default="")
    status = Column(String(20), default="confirmed")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    bands = relationship(
        "TimeBandRow", back_populates="bill", cascade="all, delete-orphan", order_by="TimeBandRow.id"
    )


class TimeBandRow(Base):
    __tablename__ = "bill_time_bands"

    id = Column(Integer, primary_key=True)
    bill_id = Column(Integer, ForeignKey("bills.id", ondelete="CASCADE"), nullable=False, index=True)
    label = Column(String(20), nullable=False)
    kwh = Column(Float)
    amount_cents = Column(Integer)

    bill = relationship("BillRow", back_populates="bands")


class ParsingLogRow(Base):
    __tablename__ = "parsing_logs"

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True)
    bill_id = Column(Integer, ForeignKey("bills.id", ondelete="SET NULL"), nullable=True, index=True)
    step = Column(String(30), nullable=False)
    status = Column(String(20), nullable=False)
    confidence = Column(Float)
    message = Column(Text, default="")
    excerpt = Column(Text)
    created_at = Column(DateTime, default=utcnow)


class SettingRow(Base):
    __tablename__ = "settings"

    key = Column(String(60), primary_key=True)
    value = Column(Text)
