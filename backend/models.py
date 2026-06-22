from __future__ import annotations

from datetime import datetime, date

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, Integer, String, Text, ForeignKey, UniqueConstraint
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
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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
    phan_khuc: Mapped[str] = mapped_column(String(64), default="")  # phân khúc giá tự tính: Standard/Premium/Luxury
    dong_tour: Mapped[str] = mapped_column(String(64), default="", index=True)  # Dòng tour marketing của VTR (scrape travel.com.vn)
    # Admin sửa tay Thị trường/Tuyến/Thời gian → khóa: quy tắc + dữ liệu sheet KHÔNG ghi đè khi tour update
    # (chừng nào tên không đổi). Đổi tên = tour mới → tự bỏ khóa.
    manual_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    search_text: Mapped[str] = mapped_column(Text, default="")
    search_text_folded: Mapped[str] = mapped_column(Text, default="")
    segment_key: Mapped[str] = mapped_column(String(512), default="", index=True)
    classification_rule_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("route_keyword_rules.id"), nullable=True, index=True
    )
    classified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # PostgreSQL: cột search_tsv (tsvector) thêm qua migration — không map ORM

    # Source tracking
    nguon: Mapped[str] = mapped_column(String(64), default="", index=True)  # Main|Vietravel|Manual (FindTourGo chỉ Sheet)
    scrape_job_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("scrape_jobs.id"), nullable=True)
    scrape_job: Mapped[ScrapeJob | None] = relationship("ScrapeJob", back_populates="tours")

    # Analyst fields
    analyst_note: Mapped[str] = mapped_column(Text, default="")
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)

    # T3 Phase 2 — Festival cross-ref
    # festival_slug: slug của lễ hội PRIMARY (gần date nhất / overlap nhiều nhất).
    # Multi-festival hiếm gặp → giữ 1 slug đơn giản. NULL = không gắn lễ.
    festival_slug: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    # festival_distance_days: số ngày từ tour.lich_kh tới festival.date_start gần nhất.
    # 0 = trùng ngày, âm = lễ đã qua, dương = lễ chưa diễn ra. Dùng cho UI label.
    festival_distance_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # province_code: derived từ diem_kh khi tagging. Cache để filter/join nhanh.
    province_code: Mapped[str] = mapped_column(String(16), default="", index=True)

    # Stable identity & sheet sync metadata
    external_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    sheet_source: Mapped[str] = mapped_column(String(64), default="")
    sheet_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    overrides: Mapped[list[TourOverride]] = relationship("TourOverride", back_populates="tour")


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
    keywords: Mapped[str] = mapped_column(String(512))  # comma = AND, e.g. "canada,cuba,mexico"
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
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


class DurationAliasRule(Base):
    """Chuẩn hóa thời gian tour (alias text → số ngày chuẩn)."""
    __tablename__ = "duration_alias_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_days: Mapped[float] = mapped_column(Float, index=True)
    alias: Mapped[str] = mapped_column(String(256), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ScheduleAliasRule(Base):
    """Chuẩn hóa lịch khởi hành (lich_kh) — map text lạ ('Theo yêu cầu', 'Liên hệ'…)
    về canonical. canonical_name="" = bỏ qua tour khỏi thống kê tần suất đoàn."""
    __tablename__ = "schedule_alias_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(128), index=True)  # "" hoặc "Theo yêu cầu"…
    alias: Mapped[str] = mapped_column(String(256), index=True)  # "theo yêu cầu", "liên hệ"…
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DateFormatRule(Base):
    """Pattern-based rule cho parse lich_kh — DSL với placeholder {dd}/{mm}/{yyyy}/{yy}/{weekday}.

    Priority asc — rule có priority nhỏ thử trước. Output type quyết định cách convert
    captured groups → list[datetime] (dates|weekly|monthly_recurring|skip|verbatim).
    Xem backend/date_format_rules.py để biết DSL grammar + compiler.
    """
    __tablename__ = "date_format_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pattern: Mapped[str] = mapped_column(String(512), index=True)
    output_type: Mapped[str] = mapped_column(String(32))  # dates|weekly|monthly_recurring|skip|verbatim|explicit_dates
    # output_value: chỉ dùng khi output_type='explicit_dates' — user nhập tay list ngày
    # đầy đủ (vd "25/06/2026, 28/07/2026") để gán cho alias.
    # Text (không giới hạn) — list ngày explicit_dates có thể rất dài (cả năm ~200 ngày).
    output_value: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    priority: Mapped[int] = mapped_column(Integer, default=100, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str] = mapped_column(String(256), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FestivalTourMappingRule(Base):
    """Rule map ĐỊA ĐIỂM TỔ CHỨC lễ ↔ Thị trường/Tuyến tour.

    User chọn 1 ĐỊA ĐIỂM (vd "Đắk Lắk", "Hàn Quốc") thay vì 1 lễ cụ thể.
    Rule sẽ apply cho TẤT CẢ lễ tổ chức ở địa điểm đó (current + future).

    Vd:
      location_keyword="Đắk Lắk"  → match mọi festival.location_text chứa
                                     "Đắk Lắk" (Lễ Sầu Riêng, Lễ Cà Phê, ...)
      market_keyword="Việt Nam"   → tour có thi_truong = "Việt Nam"
      route_keyword="Đắk Lắk"     → AND tour có tuyen_tour = "Đắk Lắk"
      → mọi tour matching được tag vào festival GẦN NHẤT (theo date)
        ở location đó.
    """
    __tablename__ = "festival_tour_mapping_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Địa điểm tổ chức (match substring với Festival.location_text)
    location_keyword: Mapped[str] = mapped_column(String(256), index=True)
    market_keyword: Mapped[str] = mapped_column(String(256), default="")
    route_keyword: Mapped[str] = mapped_column(String(256), default="")
    date_window_days: Mapped[int] = mapped_column(Integer, default=7)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Festival(Base):
    """Sự kiện & Lễ hội VN — scrape từ vietnam.travel/event hàng tuần.

    Phase 1: display-only timeline + calendar.
    Phase 2: cross-ref với tours.lich_kh để tag tour gắn lễ.
    Phase 3: insight (pricing premium, demand forecast, lunar planner).
    """
    __tablename__ = "festivals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    name_vi: Mapped[str] = mapped_column(String(512))
    name_en: Mapped[str] = mapped_column(String(512), default="")
    date_start: Mapped[date] = mapped_column(Date, index=True)
    date_end: Mapped[date] = mapped_column(Date, index=True)
    is_lunar: Mapped[bool] = mapped_column(Boolean, default=False)
    # Cho lễ âm lịch — month/day theo âm. lunar_month=1,lunar_day=1 = Tết Nguyên Đán.
    lunar_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lunar_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location_text: Mapped[str] = mapped_column(String(256), default="")
    # Mã tỉnh chuẩn (vd "HN", "HCM", "DN", "HUE"...) — Phase 2 normalize từ
    # location_text để join với tours.diem_kh.
    province_code: Mapped[str] = mapped_column(String(32), default="", index=True)
    # Vùng miền: "bac" | "trung" | "nam" (derived từ province_code)
    region: Mapped[str] = mapped_column(String(16), default="", index=True)
    # Loại lễ: "cultural" | "religious" | "music" | "food" | "sport" | "other"
    category: Mapped[str] = mapped_column(String(32), default="other", index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str] = mapped_column(String(1024), default="")
    source_url: Mapped[str] = mapped_column(String(1024), default="")
    # Hash content để detect change (avoid no-op writes mỗi tuần)
    content_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    scraped_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FestivalTourMapping(Base):
    """Bảng NỐI tour ↔ lễ hội (nhiều-nhiều) — nguồn sự thật cho việc gắn lễ.

    Thay cho cột text đơn-trị Tour.festival_slug (giờ chỉ là CACHE lễ primary).
    1 tour có thể gắn nhiều lễ (trùng mùa). `source` phân biệt nguồn tag để re-tag
    theo ngày KHÔNG xoá link do rule/manual tạo.
    """
    __tablename__ = "festival_tour_mappings"
    __table_args__ = (
        UniqueConstraint("festival_id", "tour_id", name="uq_festival_tour"),
    )

    # BigInteger (INT8): CockroachDB sinh id qua unique_rowid() cỡ ~1.18e18 > INT4
    # max (2.1 tỷ). Nếu để Integer (INT4) → "integer out of range" khi insert →
    # bảng nối không bao giờ ghi được. id + cả 2 FK đều phải INT8 để khớp tours.id
    # / festivals.id (vốn đã là INT8 trong DB).
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    festival_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("festivals.id", ondelete="CASCADE"), index=True)
    tour_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tours.id", ondelete="CASCADE"), index=True)
    festival_slug: Mapped[str] = mapped_column(String(256), default="", index=True)  # denormalize tiện query
    distance_days: Mapped[int | None] = mapped_column(Integer, nullable=True)  # |lich_kh - date_start| gần nhất
    source: Mapped[str] = mapped_column(String(16), default="date")  # 'date' | 'rule' | 'manual'
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DailySnapshot(Base):
    """Snapshot KPI hàng ngày — trend & báo cáo."""
    __tablename__ = "daily_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True, unique=True)
    total_tours: Mapped[int] = mapped_column(Integer, default=0)
    vtr_tours: Mapped[int] = mapped_column(Integer, default=0)
    segment_count: Mapped[int] = mapped_column(Integer, default=0)
    cheaper_segments: Mapped[int] = mapped_column(Integer, default=0)
    expensive_segments: Mapped[int] = mapped_column(Integer, default=0)
    similar_segments: Mapped[int] = mapped_column(Integer, default=0)
    avg_gap_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    freq_leading_segments: Mapped[int] = mapped_column(Integer, default=0)
    freq_lagging_segments: Mapped[int] = mapped_column(Integer, default=0)
    vtr_departures_monthly: Mapped[float] = mapped_column(Float, default=0)
    unclassified_tours: Mapped[int] = mapped_column(Integer, default=0)
    flagged_tours: Mapped[int] = mapped_column(Integer, default=0)
    insights_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SegmentSnapshot(Base):
    __tablename__ = "segment_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    segment_key: Mapped[str] = mapped_column(String(512), index=True)
    thi_truong: Mapped[str] = mapped_column(String(128))
    tuyen_tour: Mapped[str] = mapped_column(String(256))
    diem_kh: Mapped[str] = mapped_column(String(128))
    so_ngay: Mapped[float] = mapped_column(Float)
    gap_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    freq_gap_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    vtr_avg_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    comparison_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    vtr_avg_departures: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_avg_departures: Mapped[float | None] = mapped_column(Float, nullable=True)
    vtr_tour_count: Mapped[int] = mapped_column(Integer, default=0)
    market_tour_count: Mapped[int] = mapped_column(Integer, default=0)


class RouteDailyMetrics(Base):
    """Snapshot KPI theo Tuyến tour — nền Market Lab trend."""
    __tablename__ = "route_daily_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    route_key: Mapped[str] = mapped_column(String(512), index=True)
    thi_truong: Mapped[str] = mapped_column(String(128), index=True)
    tuyen_tour: Mapped[str] = mapped_column(String(256), index=True)
    vtr_tour_count: Mapped[int] = mapped_column(Integer, default=0)
    market_tour_count: Mapped[int] = mapped_column(Integer, default=0)
    market_departures_monthly: Mapped[float] = mapped_column(Float, default=0)
    vtr_departures_monthly: Mapped[float] = mapped_column(Float, default=0)
    avg_gap_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    freq_gap_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_price_day: Mapped[float | None] = mapped_column(Float, nullable=True)
    phase: Mapped[str] = mapped_column(String(32), default="stable")
    opportunity_score: Mapped[float] = mapped_column(Float, default=0)
    competitor_count: Mapped[int] = mapped_column(Integer, default=0)
    market_slots_json: Mapped[str] = mapped_column(Text, default="{}")
    vtr_slots_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class IntelAlert(Base):
    __tablename__ = "intel_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="info")
    category: Mapped[str] = mapped_column(String(32), default="price")
    title: Mapped[str] = mapped_column(String(512))
    message: Mapped[str] = mapped_column(Text, default="")
    link_path: Mapped[str] = mapped_column(String(256), default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class SavedView(Base):
    __tablename__ = "saved_views"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    page: Mapped[str] = mapped_column(String(64))
    filters_json: Mapped[str] = mapped_column(Text, default="{}")
    workspace_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("workspaces.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(128), default="Workspace của tôi")
    visibility: Mapped[str] = mapped_column(String(32), default="private")  # private | shared
    is_personal: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    owner: Mapped[User] = relationship("User", foreign_keys=[owner_user_id])
    members: Mapped[list[WorkspaceMember]] = relationship("WorkspaceMember", back_populates="workspace")
    overrides: Mapped[list[TourOverride]] = relationship("TourOverride", back_populates="workspace")


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(Integer, ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    permission: Mapped[str] = mapped_column(String(16), default="view")  # view | edit | copy
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    workspace: Mapped[Workspace] = relationship("Workspace", back_populates="members")
    user: Mapped[User] = relationship("User", foreign_keys=[user_id])


class TourOverride(Base):
    __tablename__ = "tour_overrides"
    __table_args__ = (UniqueConstraint("workspace_id", "tour_id", name="uq_workspace_tour_override"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(Integer, ForeignKey("workspaces.id"), index=True)
    tour_id: Mapped[int] = mapped_column(Integer, ForeignKey("tours.id"), index=True)
    updated_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    overrides_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    workspace: Mapped[Workspace] = relationship("Workspace", back_populates="overrides")
    tour: Mapped[Tour] = relationship("Tour", back_populates="overrides")
    editor: Mapped[User] = relationship("User", foreign_keys=[updated_by])


class RouteRuleToken(Base):
    """Inverted index token → rule (lọc incremental nhanh)."""

    __tablename__ = "route_rule_tokens"
    __table_args__ = (UniqueConstraint("rule_id", "token", name="uq_rule_token"),)

    # BigInteger vì rule_id reference route_keyword_rules.id có thể > 2^31
    # (CRDB unique_rowid sinh ~1.18e18). SQLAlchemy Integer cast INSERT thành
    # INTEGER → NumericValueOutOfRange. BigInteger map sang BIGINT correct.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rule_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("route_keyword_rules.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(128), index=True)


class AppKv(Base):
    """Key-value nhỏ (job status, v.v.) — dùng chung mọi worker."""
    __tablename__ = "app_kv"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class JobLock(Base):
    """Khóa thuê (lease) cấp DB cho job ghi bảng Tour — thay advisory lock (CockroachDB không hỗ trợ).

    Một dòng = một khóa. Job giành khóa bằng UPSERT có điều kiện expires_at < now (nguyên tử),
    gia hạn định kỳ (heartbeat), nhả khi xong. Khóa hết hạn tự nhường cho job khác (chống treo).
    Hoạt động xuyên process/instance (Render chạy nhiều worker) vì chỉ là 1 dòng dữ liệu.
    """
    __tablename__ = "job_lock"

    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    holder: Mapped[str] = mapped_column(String(64), default="")
    # timezone=True → so sánh với now() (timestamptz) không bị lệch tz dù đổi session TimeZone.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
