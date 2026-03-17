from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from database.db import Base


class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    header = Column(String(255), nullable=True)
    date_range = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    rows = relationship("ReceivableRow", back_populates="report", cascade="all, delete-orphan")


class ReceivableRow(Base):
    __tablename__ = "receivable_rows"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("reports.id"), index=True, nullable=False)

    region = Column(String(100), index=True, nullable=False)
    customer_name = Column(String(255), nullable=False, index=True)

    payment_status = Column(String(32), nullable=False, default="Unpaid")  # Paid | Unpaid | Partially Paid

    safe = Column(Float, default=0.0)
    warning = Column(Float, default=0.0)
    danger = Column(Float, default=0.0)
    doubtful = Column(Float, default=0.0)
    total = Column(Float, default=0.0)

    original_safe = Column(Float, default=0.0)
    original_warning = Column(Float, default=0.0)
    original_danger = Column(Float, default=0.0)
    original_doubtful = Column(Float, default=0.0)
    original_total = Column(Float, default=0.0)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    report = relationship("Report", back_populates="rows")

