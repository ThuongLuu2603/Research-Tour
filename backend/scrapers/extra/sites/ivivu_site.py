"""Extra scraper: iVIVU.com (https://www.ivivu.com/du-lich/).

ivivu là SPA, KHÔNG render tour trong HTML — load qua API JSON nội bộ:
  POST https://apiportal.ivivu.com/web_prot/mercurius-tour/api/TourDataSearchApi/TourSearchWithIdsV2
  body: {"DepartureTime": "YYYY-MM-DD", "TourIds": "id1,id2,..."}
  -> trả mảng tour: Code/Name/Time/Departured/Contract[].PriceAdult/DepartureDate[].

`TourIds` là danh sách tour của trang du-lich (frontend nạp sẵn). Ta nhúng seed
list (_SEED_TOUR_IDS) để chạy được ngay; mỗi lần chạy POST lại -> GIÁ + LỊCH KH
luôn mới (API realtime), chỉ tập tour là cố định. Khi biết endpoint trả danh sách
ID, set _TOUR_IDS_URL để tự bắt tour mới (xem _fetch_tour_ids).

KHÔNG bịa lịch trình: API này không trả itinerary -> lich_trinh = "".
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Callable

import pandas as pd
import requests

from scrapers.extra.registry import ExtraScraper, register
from scrapers.extra.sites.example_site import STANDARD_COLUMNS

logger = logging.getLogger(__name__)

_API_BASE = "https://apiportal.ivivu.com/web_prot/mercurius-tour/api/TourDataSearchApi"
_SEARCH_URL = f"{_API_BASE}/TourSearchWithIdsV2"

# Nếu sau này biết request trả về danh sách TourIds (GET/POST), điền URL vào đây để
# scraper tự lấy tour mới thay vì dùng seed cứng. None = dùng _SEED_TOUR_IDS.
_TOUR_IDS_URL: str | None = None

_COMPANY = "iVIVU.com"
_BATCH = 300          # số ID / 1 POST (API nhận cả ~600 trong 1 request, chia nhỏ cho chắc)
_TIMEOUT = 60

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://www.ivivu.com",
    "Referer": "https://www.ivivu.com/",
}

# Seed danh sách tour của trang du-lich (capture 2026-06). API trả giá/lịch mới mỗi lần.
_SEED_TOUR_IDS = (
    "4252,1783,4361,4745,2387,4284,3086,2385,2441,628,2876,4764,1896,5167,5261,5100,"
    "2903,4991,5019,4136,4898,4953,2328,3094,4125,2632,1049,4999,2139,2126,1519,2087,"
    "348,795,2909,2326,686,2444,2196,780,2211,4741,4701,5138,4992,2997,5169,4978,4988,"
    "5211,2193,2274,4364,4788,2152,5110,5121,4643,5213,4960,2551,673,2601,4531,4270,"
    "2921,4792,1644,5178,1691,4525,122,1764,2618,2313,4542,4976,1685,2938,341,2837,"
    "2567,4190,1523,2289,4369,1745,1574,2163,2974,747,1909,1699,4265,4495,2294,2617,"
    "1514,716,1365,290,4208,4440,1511,2834,536,971,1441,2109,3003,1323,3005,2858,1309,"
    "539,1500,635,1412,452,1498,5206,637,2682,2814,2832,2913,3099,4167,1237,1314,1380,"
    "5222,5239,4481,4122,2350,2745,2073,4717,4758,5115,5124,5151,5158,5215,5251,5258,"
    "70,3078,4257,2703,2785,4389,4571,4950,4964,5014,5032,4279,4951,1231,1649,2360,"
    "2249,5228,4928,5013,5162,5177,4826,3075,2603,2805,5175,5257,2413,4203,2932,2949,"
    "2996,3081,4450,5085,5254,1678,1695,1696,1278,1292,1409,5194,4894,2137,4645,4743,"
    "2871,2924,4143,4443,2188,1437,1686,1653,1785,1968,83,2406,2687,3057,4393,4763,"
    "4878,5197,5214,5227,1706,1999,1413,2842,2442,2524,2549,2599,4264,4382,5000,5025,"
    "5118,4434,2812,4219,4283,1726,5248,1361,2998,4134,2448,2497,2833,3019,1933,1890,"
    "5198,4798,3016,4202,4502,2730,2915,1308,1729,5238,1651,5202,4837,4259,1787,1855,"
    "1936,2085,2455,2689,1790,5246,5161,4927,5029,4442,1315,886,1672,2351,3037,4366,"
    "5116,5159,5166,5209,1355,662,2359,2602,2691,2734,3002,3061,4138,4197,4363,4733,"
    "1934,1998,1312,1439,1705,1741,2175,2477,5255,5170,5105,4784,4905,4969,1932,2000,"
    "2425,2459,2727,5233,5242,1455,5226,5026,5126,4790,3018,3020,5240,5108,5142,5155,"
    "2031,5154,4770,314,4365,1347,439,880,1712,5253,509,513,4913,4945,5099,5092,526,"
    "2006,2496,2095,2514,4289,4416,649,2945,655,4987,2103,4979,664,1267,2041,2015,"
    "2916,4958,739,746,5190,4144,5191,4145,4691,2577,4966,5216,2003,790,799,2608,2818,"
    "4655,4132,2355,4686,827,2077,831,2975,847,4941,4940,2597,4971,4267,4824,901,1806,"
    "1877,4809,4808,903,948,997,1001,4514,4126,5217,1022,2851,2377,2518,4565,2770,"
    "2221,2279,4183,4519,4520,4569,4570,2919,2533,2283,4522,4115,2546,2696,4286,4141,"
    "1905,3028,2642,2374,2521,5244,4796,2522,2528,2646,1036,2607,4435,5141,4234,4851,"
    "5212,4795,5012,4563,5260,5245,4557,4739,4757,5103,2435,1996,4970,4395,4748,4398,"
    "4934,5184,5234,4687,1112,5256,2877,5066,5231,4236,1618,4411,5237,5148,4766,1129,"
    "2115,1131,1145,1151,1159,1163,4273,2464,1883,1939,5011,4700,5038,4888,4884,5200,"
    "2568"
)


def _fmt_price(contracts: list[dict]) -> str:
    """Giá đại diện = PriceAdult nhỏ nhất (>0) trong Contract -> '3.990.000'."""
    vals: list[float] = []
    for c in contracts or []:
        for k in ("PriceAdult", "PriceAdultAvg"):
            v = c.get(k)
            if isinstance(v, (int, float)) and v > 0:
                vals.append(float(v))
                break
    if not vals:
        return ""
    return f"{int(round(min(vals))):,}".replace(",", ".")


def _fmt_dates(raw: list[str]) -> str:
    """['2026-06-18T00:00:00', ...] -> '18/06/2026, 19/06/2026, ...' (bỏ trùng, giữ thứ tự)."""
    out: list[str] = []
    seen: set[str] = set()
    for s in raw or []:
        d = str(s)[:10]  # 'YYYY-MM-DD'
        try:
            y, m, day = d.split("-")
            ddmm = f"{int(day):02d}/{int(m):02d}/{y}"
        except Exception:  # noqa: BLE001
            continue
        if ddmm not in seen:
            seen.add(ddmm)
            out.append(ddmm)
    return ", ".join(out)


def _fetch_tour_ids(session: requests.Session) -> str:
    """Lấy chuỗi TourIds. Mặc định seed cứng; nếu set _TOUR_IDS_URL thì lấy động."""
    if not _TOUR_IDS_URL:
        return _SEED_TOUR_IDS
    try:
        r = session.get(_TOUR_IDS_URL, headers=_HEADERS, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        # TODO: tùy shape thật của endpoint -> rút list id. Hiện chưa biết -> fallback seed.
        if isinstance(data, list) and data and isinstance(data[0], (int, str)):
            return ",".join(str(x) for x in data)
        ids = data.get("TourIds") or data.get("Ids") or data.get("ids")
        if isinstance(ids, str) and ids.strip():
            return ids
        if isinstance(ids, list) and ids:
            return ",".join(str(x) for x in ids)
    except Exception as e:  # noqa: BLE001
        logger.warning("ivivu: lấy TourIds động lỗi (%s) -> dùng seed", e)
    return _SEED_TOUR_IDS


def _row_from_tour(t: dict) -> dict:
    return {
        "cong_ty": _COMPANY,
        "thi_truong": "",                         # để rule phân loại tự gán
        "tuyen_tour": "",
        "ten_tour": (t.get("Name") or "").strip(),
        "lich_trinh": "",                         # API không trả itinerary -> KHÔNG bịa
        "diem_kh": (t.get("Departured") or "").strip(),
        "thoi_gian": (t.get("Time") or "").strip(),
        "gia": _fmt_price(t.get("Contract") or []),
        "lich_kh": _fmt_dates(t.get("DepartureDate") or []),
        "link_url": "",                           # API không trả URL; xem ghi chú cuối file
        "ma_tour": (t.get("Code") or "").strip(),
        "khach_san": "",
        "hang_khong": "",
    }


def scrape(progress: Callable[[int, str], None] | None = None) -> pd.DataFrame:
    if progress:
        progress(5, "iVIVU: chuẩn bị danh sách tour")

    session = requests.Session()
    ids_csv = _fetch_tour_ids(session)
    all_ids = [x for x in (ids_csv or "").split(",") if x.strip()]
    if not all_ids:
        if progress:
            progress(100, "iVIVU: không có TourIds")
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    # DepartureTime = hôm nay (lấy mọi lịch KH từ nay trở đi).
    dep = _dt.date.today().strftime("%Y-%m-%d")

    rows: list[dict] = []
    batches = [all_ids[i:i + _BATCH] for i in range(0, len(all_ids), _BATCH)]
    for bi, batch in enumerate(batches):
        if progress:
            progress(10 + int(80 * bi / max(len(batches), 1)),
                     f"iVIVU: tải lô {bi + 1}/{len(batches)} ({len(batch)} tour)")
        body = {"DepartureTime": dep, "TourIds": ",".join(batch)}
        try:
            r = session.post(_SEARCH_URL, json=body, headers=_HEADERS, timeout=_TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except Exception as e:  # noqa: BLE001
            logger.warning("ivivu: lô %s lỗi: %s", bi + 1, e)
            continue
        if not isinstance(data, list):
            continue
        for t in data:
            if isinstance(t, dict) and (t.get("Name") or "").strip():
                rows.append(_row_from_tour(t))

    df = pd.DataFrame(rows, columns=STANDARD_COLUMNS)
    if progress:
        progress(100, f"iVIVU xong: {len(df)} tour")
    return df


register(ExtraScraper(
    key="ivivu",
    name="iVIVU.com",
    scrape=scrape,
))
