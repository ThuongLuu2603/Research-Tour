from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    role: Mapped[str] = mapped_column(String(32), default="analyst")  # admin | analyst
    avatar_url: Mapped[str] = mapped_column(String(512), default="")  # emoji or image URL
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ScrapeJob(Base):
    __tablename__ = "scrape_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    scraper_name: Mapped[str] = mapped_column(String(64), nullable=False)  # vietravel | findtourgo
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|running|success|failed
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    tours_added: Mapped[int] = mapped_column(Integer, default=0)
    tours_updated: Mapped[int] = mapped_column(Integer, default=0)
    tours_total: Mapped[int] = mapped_column(Integer, default=0)
    triggered_by: Mapped[str] = mapped_column(String(64), default="manual")  # manual | scheduler
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    tours: Mapped[list[Tour]] = relationship("Tour", back_populates="scrape_job")


class Tour(Base):
    __tablename__ = "tours"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Core fields matching sheet columns A–N
    cong_ty: Mapped[str] = mapped_column(String(256), default="", index=True)
    thi_truong: Mapped[str] = mapped_column(String(128), default="", index=True)
    tuyen_tour: Mapped[str] = mapped_column(String(256), default="", index=True)
    ten_tour: Mapped[str] = mapped_column(String(512), default="")
    lich_trinh: Mapped[str] = mapped_column(Text, default="")
    diem_kh: Mapped[str] = mapped_column(String(256), default="")
    thoi_gian: Mapped[str] = mapped_column(String(64), default="")
    gia: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    gia_raw: Mapped[str] = mapped_column(String(64), default="")
    lich_kh: Mapped[str] = mapped_column(Text, default="")
    link_url: Mapped[str] = mapped_column(Text, default="")
    ma_tour: Mapped[str] = mapped_column(String(64), default="", index=True)
    khach_san: Mapped[str] = mapped_column(String(256), default="")
    hang_khong: Mapped[str] = mapped_column(String(256), default="")

    # Derived/computed
    so_ngay: Mapped[float | None] = mapped_column(Float, nullable=True)
    phan_khuc: Mapped[str] = mapped_column(String(64), default="")

    # Source tracking
    nguon: Mapped[str] = mapped_column(String(64), default="", index=True)  # Vietravel|FindTourGo|Manual
    scrape_job_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("scrape_jobs.id"), nullable=True)
    scrape_job: Mapped[ScrapeJob | None] = relationship("ScrapeJob", back_populates="tours")

    # Analyst fields
    analyst_note: Mapped[str] = mapped_column(Text, default="")
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MarketKeywordRule(Base):
    """Quy tắc keyword → Thị trường (thay thế hardcode market_rules.py)."""
    __tablename__ = "market_keyword_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market: Mapped[str] = mapped_column(String(128), index=True)
    keyword: Mapped[str] = mapped_column(String(256), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RouteKeywordRule(Base):
    """Quy tắc keyword → Tuyến tour (trong 1 thị trường). Keywords: comma-separated, ALL must match."""
    __tablename__ = "route_keyword_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thi_truong: Mapped[str] = mapped_column(String(128), index=True)
    tuyen_tour: Mapped[str] = mapped_column(String(256), index=True)
    keywords: Mapped[str] = mapped_column(String(512))  # e.g. "bangkok,pattaya"
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CompanyAliasRule(Base):
    """Chuẩn hóa tên công ty từ nhiều nguồn → tên chính thức."""
    __tablename__ = "company_alias_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(256), index=True)
    alias: Mapped[str] = mapped_column(String(256), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DepartureAliasRule(Base):
    """Chuẩn hóa điểm khởi hành từ nhiều nguồn → tên chính thức."""
    __tablename__ = "departure_alias_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(256), index=True)
    alias: Mapped[str] = mapped_column(String(256), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
