"""Master danh sách 63 tỉnh/thành VN + alias để normalize free-text location.

Dùng để:
  - Normalize Tour.diem_kh → province_code (vd "TP. HCM", "HCMC", "Sài Gòn" → "HCM")
  - Normalize Festival.location_text → province_code → cross-ref tour
  - Group theo region (bac/trung/nam) cho heatmap, stats

Phase 2 dùng module Python (in-memory). Nếu cần CRUD UI → Phase sau migrate sang table.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache


# (province_code, name_vi, region, aliases tuple)
# region: bac | trung | nam
PROVINCES: list[tuple[str, str, str, tuple[str, ...]]] = [
    # ── BẮC ─────────────────────────────────────────────────────────────
    ("HN",   "Hà Nội",            "bac", ("hanoi", "ha noi", "hà nội", "hn")),
    ("HP",   "Hải Phòng",         "bac", ("hai phong", "haiphong", "hp")),
    ("QN",   "Quảng Ninh",        "bac", ("quang ninh", "qn", "ha long", "hạ long", "halong")),
    ("LC",   "Lào Cai",           "bac", ("lao cai", "sapa", "sa pa")),
    ("NB",   "Ninh Bình",         "bac", ("ninh binh", "ninh bình", "trang an", "tràng an", "tam coc")),
    ("HG",   "Hà Giang",          "bac", ("ha giang", "hà giang", "dong van", "đồng văn", "ma pi leng")),
    ("TN",   "Thái Nguyên",       "bac", ("thai nguyen", "thái nguyên")),
    ("BN",   "Bắc Ninh",          "bac", ("bac ninh", "bắc ninh")),
    ("PT",   "Phú Thọ",           "bac", ("phu tho", "phú thọ", "viet tri", "đền hùng", "den hung")),
    ("YB",   "Yên Bái",           "bac", ("yen bai", "yên bái", "mu cang chai", "mù cang chải")),
    ("DB",   "Điện Biên",         "bac", ("dien bien", "điện biên")),
    ("LS",   "Lạng Sơn",          "bac", ("lang son", "lạng sơn")),
    ("TQ",   "Tuyên Quang",       "bac", ("tuyen quang", "tuyên quang")),
    ("BG",   "Bắc Giang",         "bac", ("bac giang", "bắc giang")),
    ("BK",   "Bắc Kạn",           "bac", ("bac kan", "bắc kạn", "ba be", "ba bể")),
    ("CB",   "Cao Bằng",          "bac", ("cao bang", "cao bằng", "ban gioc", "bản giốc")),
    ("HB",   "Hòa Bình",          "bac", ("hoa binh", "hòa bình", "mai chau", "mai châu")),
    ("HD",   "Hải Dương",         "bac", ("hai duong", "hải dương")),
    ("HY",   "Hưng Yên",          "bac", ("hung yen", "hưng yên")),
    ("LĐ",   "Lai Châu",          "bac", ("lai chau", "lai châu")),
    ("ND",   "Nam Định",          "bac", ("nam dinh", "nam định")),
    ("NA",   "Nghệ An",           "bac", ("nghe an", "nghệ an", "vinh", "kim lien", "kim liên")),
    ("SL",   "Sơn La",            "bac", ("son la", "sơn la", "moc chau", "mộc châu")),
    ("TB",   "Thái Bình",         "bac", ("thai binh", "thái bình")),
    ("TH",   "Thanh Hóa",         "bac", ("thanh hoa", "thanh hóa", "sam son", "sầm sơn")),
    ("VP",   "Vĩnh Phúc",         "bac", ("vinh phuc", "vĩnh phúc", "tam dao", "tam đảo")),
    ("HM",   "Hà Nam",            "bac", ("ha nam", "hà nam", "tam chuc", "tam chúc")),

    # ── TRUNG ───────────────────────────────────────────────────────────
    ("HUE",  "Thừa Thiên Huế",    "trung", ("hue", "huế", "thua thien hue", "thừa thiên huế", "thừa thiên-huế")),
    ("DN",   "Đà Nẵng",           "trung", ("da nang", "đà nẵng", "dn", "danang")),
    ("QNM",  "Quảng Nam",         "trung", ("quang nam", "quảng nam", "hoi an", "hội an", "my son", "mỹ sơn")),
    ("QB",   "Quảng Bình",        "trung", ("quang binh", "quảng bình", "phong nha", "son doong", "sơn đoòng")),
    ("QT",   "Quảng Trị",         "trung", ("quang tri", "quảng trị", "dong ha", "đông hà")),
    ("KH",   "Khánh Hòa",         "trung", ("khanh hoa", "khánh hòa", "nha trang")),
    ("PY",   "Phú Yên",           "trung", ("phu yen", "phú yên", "tuy hoa", "tuy hòa")),
    ("BD",   "Bình Định",         "trung", ("binh dinh", "bình định", "quy nhon", "quy nhơn")),
    ("NT",   "Ninh Thuận",        "trung", ("ninh thuan", "ninh thuận", "phan rang")),
    ("BT",   "Bình Thuận",        "trung", ("binh thuan", "bình thuận", "phan thiet", "phan thiết", "mui ne", "mũi né")),
    ("ĐL",   "Lâm Đồng",          "trung", ("lam dong", "lâm đồng", "da lat", "đà lạt", "dalat")),
    ("KT",   "Kon Tum",           "trung", ("kon tum", "ngọc linh", "ngoc linh")),
    ("GL",   "Gia Lai",           "trung", ("gia lai", "pleiku")),
    ("DL",   "Đắk Lắk",           "trung", ("dak lak", "đắk lắk", "buon ma thuot", "buôn ma thuột", "bmt")),
    ("DKL",  "Đắk Nông",          "trung", ("dak nong", "đắk nông", "gia nghia", "gia nghĩa")),
    ("QNG",  "Quảng Ngãi",        "trung", ("quang ngai", "quảng ngãi", "ly son", "lý sơn")),
    ("HT",   "Hà Tĩnh",           "trung", ("ha tinh", "hà tĩnh")),

    # ── NAM ─────────────────────────────────────────────────────────────
    ("HCM",  "TP. Hồ Chí Minh",   "nam", ("ho chi minh", "hồ chí minh", "tp.hcm", "tphcm", "tp hcm", "saigon", "sài gòn", "hcm city", "sg", "hcmc")),
    ("CT",   "Cần Thơ",           "nam", ("can tho", "cần thơ", "ct")),
    ("VT",   "Bà Rịa - Vũng Tàu", "nam", ("vung tau", "vũng tàu", "ba ria", "bà rịa", "ba ria - vung tau", "vt")),
    ("DNI",  "Đồng Nai",          "nam", ("dong nai", "đồng nai", "bien hoa", "biên hòa")),
    ("BDU",  "Bình Dương",        "nam", ("binh duong", "bình dương", "thu dau mot", "thủ dầu một")),
    ("LA",   "Long An",           "nam", ("long an",)),
    ("TG",   "Tiền Giang",        "nam", ("tien giang", "tiền giang", "my tho", "mỹ tho")),
    ("BTR",  "Bến Tre",           "nam", ("ben tre", "bến tre")),
    ("VL",   "Vĩnh Long",         "nam", ("vinh long", "vĩnh long")),
    ("AG",   "An Giang",          "nam", ("an giang", "chau doc", "châu đốc", "long xuyen", "long xuyên")),
    ("KG",   "Kiên Giang",        "nam", ("kien giang", "kiên giang", "phu quoc", "phú quốc", "ha tien", "hà tiên", "rach gia", "rạch giá")),
    ("CM",   "Cà Mau",            "nam", ("ca mau", "cà mau", "đất mũi", "dat mui")),
    ("ST",   "Sóc Trăng",         "nam", ("soc trang", "sóc trăng")),
    ("TV",   "Trà Vinh",          "nam", ("tra vinh", "trà vinh")),
    ("ĐT",   "Đồng Tháp",         "nam", ("dong thap", "đồng tháp", "cao lanh", "cao lãnh", "sa dec", "sa đéc")),
    ("HU",   "Hậu Giang",         "nam", ("hau giang", "hậu giang", "vi thanh", "vị thanh")),
    ("BL",   "Bạc Liêu",          "nam", ("bac lieu", "bạc liêu")),
    ("BP",   "Bình Phước",        "nam", ("binh phuoc", "bình phước", "dong xoai", "đồng xoài")),
    ("TNI",  "Tây Ninh",          "nam", ("tay ninh", "tây ninh", "nui ba den", "núi bà đen", "cu chi", "củ chi")),
]


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


@lru_cache(maxsize=1)
def _alias_index() -> dict[str, str]:
    """Build {normalized_alias: province_code} cho lookup nhanh."""
    idx: dict[str, str] = {}
    for code, name_vi, _region, aliases in PROVINCES:
        # Add code itself + name_vi + aliases
        for a in (code.lower(), name_vi.lower(), *(al.lower() for al in aliases)):
            norm = _strip_accents(a).strip()
            if norm:
                idx[norm] = code
                # Cũng lưu phiên bản dấu cách thay bằng "-" hoặc bỏ space
                idx[norm.replace(" ", "")] = code
                idx[norm.replace(" ", "-")] = code
    return idx


@lru_cache(maxsize=2)
def _region_by_code() -> dict[str, str]:
    return {code: region for code, _name, region, _al in PROVINCES}


@lru_cache(maxsize=2)
def _name_by_code() -> dict[str, str]:
    return {code: name for code, name, _r, _al in PROVINCES}


def resolve_province_code(text: str) -> str:
    """Convert free-text location → province_code (vd "Hà Nội" → "HN").

    Match heuristic theo thứ tự:
      1. Exact alias match (lower + strip accent + remove punct)
      2. Substring match — tìm alias dài nhất xuất hiện trong text
      3. "" nếu không match

    Args:
        text: "Hà Nội", "TP. HCM", "Tour Đà Nẵng - Hội An 4 ngày"

    Returns:
        province_code uppercase 2-3 ký tự, hoặc "" nếu không khớp.
    """
    if not text:
        return ""
    t = _strip_accents(text.lower()).strip()
    # Remove punctuation phổ biến
    t = re.sub(r"[.,;:/\\()|]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        return ""
    idx = _alias_index()
    # Exact match
    if t in idx:
        return idx[t]
    # Substring — duyệt alias theo độ dài giảm dần (alias dài hơn ưu tiên)
    keys_sorted = sorted(idx.keys(), key=len, reverse=True)
    for k in keys_sorted:
        if len(k) < 3:
            continue  # skip alias ngắn (vd "vt") dễ false match
        if k in t:
            return idx[k]
    # Match từ riêng lẻ với alias 2 ký tự (codes)
    tokens = set(t.split())
    for k in idx:
        if k in tokens:
            return idx[k]
    return ""


def get_region_for_code(code: str) -> str:
    """province_code → region (bac/trung/nam) hoặc ""."""
    return _region_by_code().get(code, "")


def get_name_for_code(code: str) -> str:
    return _name_by_code().get(code, "")


def all_provinces() -> list[dict[str, str]]:
    """List 63 tỉnh cho UI dropdown / map."""
    return [
        {"code": code, "name": name, "region": region}
        for code, name, region, _ in PROVINCES
    ]
