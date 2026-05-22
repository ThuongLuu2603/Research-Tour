"""
Phân loại Thị trường từ Tên tour + Lịch trình (logic MARKET_KEYWORDS / gettuyenkh).
Nguồn: thi truong.md (Google Apps Script).
"""

from __future__ import annotations

MARKET_KEYWORDS: dict[str, list[str]] = {
    "Thái Lan": ["thái lan", "phuket", "bangkok", "chiangmai", "chiangrai", "chiang mai", "chiang rai", "sunthai", "wat arun"],
    "Trung Quốc": ["trung quốc", "hongkong", "hồng kông", "tây tạng", "trung hoa", "thượng hải", "quảng châu", "phượng hoàng cổ trấn", "cáp nhĩ tân", "cửu trại câu", "shangrila", "bắc kinh", "trùng khánh", "mông tự", "hải khẩu", "nam ninh", "tân cương", "giang nam", "lệ giang", "hong kong", "hải nam", "giang tây", "khai phong", "trương gia giới", "thâm quyến", "tây an", "vọng tiên cốc", "tashilhunpo", "hạ môn", "quý dương", "thiên hộ miêu trại", "cam túc", "shangri-la", "tam quốc diễn nghĩa", "côn minh", "đại lý", "kiệu tử", "trà cổ", "đông hưng", "tứ xuyên", "hồng kong", "tam á", "nam sơn", "thiên nhai hải giác", "quế lâm", "dương sóc", "thanh đảo", "hồ nam", "thành đô", "gia cô sơn", "cứu trại câu", "đôn hoàng", "vũ hán"],
    "Châu Á khác": ["mông cổ", "trung á"],
    "Hàn Quốc": ["hàn quốc", "xứ sở kim chi", "seoul", "busan", "jeju"],
    "Đài Loan": ["đài loan", "đài bắc", "cao hùng"],
    "Singapore - Malaysia": ["singapore", "malaysia", "penang", "sing - mã - indo", "sing - mã"],
    "Đông Nam Á khác": ["bali", "philippines", "brunei", "campuchia", "lào", "xiengthong", "cam - lào", "siem reap", "jakarta", "xứ sở triệu voi", "viêng chăn", "tanah lot", "myanmar", "yangon", "núi lửa bromo", "philipines", "cambodia", "luang prabang", "viettel marathon 2024 - lao", "khám phá quốc phật", "sihanouk", "nusa penida", "indonesia", "angkor"],
    "Châu Úc": ["tour úc", "châu úc", "australia", "sydney", "new zealand", "du lịch úc", "brisbane", "du lich úc", "nước úc", "melbourne", "perth"],
    "Nhật Bản": ["nhật bản", "cung đường vàng", "tokyo", "kagoshima", "sapporo", "yamagata", "narita", "nagoya", "hokkaido", "fukuoka", 'xứ sở "mặt trời mọc"', "fukushima", "shirakawago", "hiroshima", "osaka", "kobe", "du lịch nhật bản"],
    "Nam Á": ["ấn độ", "bhutan", "nepal", "maldives", "kathmandu", "delhi", "tứ động tâm", "himalayas", "srilanka"],
    "Châu Phi": ["ai cập", "nam phi", "madagascar", "châu phi", "maroc", "cairo", "johannesburg", "kenya", "tazania"],
    "Trung Đông": ["dubai", "qatar", "jordan", "azerbaijan", "armenia", "georgia"],
    "Châu Mỹ": ["hoa kỳ", "canada", "châu mỹ", "nước mỹ", "tây mỹ", "los angeles", "honolulu", "hoa kì", "san francisco", "liên tuyến đông tây", "philadelphia", "toronto", "thị thực mỹ", "capilano vancouver", "mexico", "brazil", "amazon", "bờ đông mỹ", "du lịch mỹ", "trung mỹ", "yellowstone", "bờ tây hoa kỳ", "rocky mountains", "làng whistler", "alaska", "xứ cờ hoa", "mỹ bờ tây", "đông bắc mỹ", "giấc mơ mỹ", "du lich mỹ", "tour mỹ", "vancouver", "tuyến đông tây: mùa hoa phượng tím", "đông - tây hòa kỳ", "tuyến mỹ đông tây", "chicago", "houston", "bờ đông - bờ tây nước mỹ"],
    "Châu Âu": ["châu âu", "thổ nhĩ kỳ", "anh quốc", "nga", "bắc âu", "matxcova", "moscow", "petersburg", "pháp", "phần lan", "tây ban nha", "scotland", "zurich", "du lịch ý", "thổ nhĩ kì", "thụy sĩ", "hà lan", "thị thực đức", "thị thực ý", "xứ sở sương mù 8 ngày 7 đêm", "xứ sở sương mù 7 ngày 6 đêm", "luxembourg", "thuỵ sĩ", "london", "ý mono", "thụy sỹ", "istanbul", "croatia", "đông âu", "xứ sở bạch dương", "wales", "địa trung hải", "tây nam âu", "nam âu", "nice", "cannes", "vatican", "balkans", "santorini", "athens", "hy lạp", "iceland"],
    "Phú Quốc": ["phú quốc", "grand world - bãi sao", "dinh cậu"],
    "Nha Trang": ["nha trang", "bình ba", "bình hưng", "hòn tằm", "tứ bình", "tam bình", "selectum noa cam ranh resort", "đảo điệp sơn", "tour nha ttang"],
    "Côn Đảo": ["côn đảo", "hòn bảy cạnh"],
    "Vũng Tàu": ["vũng tàu", "hồ tràm", "hồ cóc", "núi dinh"],
    "Phan Thiết": ["phan thiết", "mũi né", "phú quý", "lagi", "bình châu", "tà pao", "coco beach"],
    "Ninh Thuận": ["ninh thuận", "phan rang", "vĩnh hy", "hang rái"],
    "Phú Yên - Quy Nhơn": ["phú yên", "quy nhơn", "bình định", "kỳ co", "bảo tàng quang trung", "gành đá đĩa", "hòn khô", "eo gió", "tây sơn", "asteria"],
    "Đồng Bằng Sông Hồng": ["hạ long", "ninh bình", "sapa", "hà nam", "bắc ninh", "nam định", "phú thọ", "tràng an", "chùa hương", "thủ đô hà nội", "yên tử", "cát bà", "fansipan", "cô tô", "city tour hà nội", "nghệ an", "đảo quan lạn", "miền bắc 5n4đ  (kh: thứ 2, 4 hàng tuần)", "quan lạn", "sầm sơn", "hải tiến", "đồ sơn", "cửa lò", "hoa lư", "y tý", "tam chúc", "địa tạng phi lai tự", "du lịch hà nội 1 ngày", "du kịch miền bắc 6n5đ", "trúc lâm an tâm", "bình liêu", "xương giang", "khám phá tour miền bắc 5 ngày 4 đêm", "nhà thờ bùi chu", "đồng bằng sông hồng", "du lịch miền bắc", "bắc hà", "khám phá miền bắc️", "hải hòa", "pù luông", "tam đảo", "chợ phiên bắc hà", "vân đồn", "đền hùng", "vịnh hạ long", "đường lâm", "tour hà nội city", "hang múa", "tam cốc", "chùa cái bầu", "hà nội city tour", "tour hà nội 1 ngày", "tour hà nội luxury city tour", "hà nội"],
    "Đông Bắc": ["hà giang", "đồng văn", "cao bằng", "bắc cạn", "thác bản giốc", "lũng cú", "đông bắc", "hoàng su phì", "pác bó", "ba bể", "na hang"],
    "Tây Bắc": ["mù cang chải", "yên bái", "tú lệ", "mai châu", "mộc châu", "tây bắc", "điện biên", "tà xùa", "thung nai", "mù căng chải", "nhìu cồ san", "tà chì nhù", "cầu kính bạch long", "lạng sơn", "lùng cúng"],
    "Bắc Trung Bộ": ["lý sơn", "hội an", "huế", "quảng bình", "cù lao chàm", "quãng ngãi", "ngũ hành sơn", "bà nà", "sơn trà", "bạch mã", "hòa phú thành", "marble mountain", "bana hill", "호이안 - 짬섬 - 다낭", "띠엔무 파고다", "vi vu đà nẵng", "động phong nha", "tour đà nẵng 4 ngày 3 đêm", "núi thần tài", "thủy biều", "di sản miền trung", "lăng cô", "pháo hoa đà nẵng", "maximilan danang", "canvas 4* đà nẵng", "tour ghép tại đà nẵng", "suối khoáng thần tài", "làng bích hoạ tam thanh", "tour ghép miền trung", "green world đà nẵng", "rừng dừa bảy mẫu", "pilgrimage village boutique resort", "sepon boutique resort", "du lịch sinh thái nam đông", "cổng trời đông giang", "le pavillon paradise hoi an", "little hawaii (thuận an beach)", "hà nội - đà nẵng", "tour miền trung", "tour kích cầu đà nẵng", "đà nẵng khởi hành từ hà nội", "đà nẵng 3 ngày 2 đêm", "vũng chùa", "suối mọoc", "thiên đường miền trung", "văn hóa cộng đồng đông giang", "làng cổ phước tích", "suối hầm heo", "du lịch đà nẵng", "tour đà nẵng", "phiêu du - đà nẵng", "khám phá đà nẵng", "hải phòng đà nẵng", "khám phá thành phố đà nẵng", "gold coast hotel resort", "đảo cồn cỏ", "tour tết đà nẵng", "mikazuki japanese resort", "cham island", "hành hương la vang", "thánh địa mỹ sơn", "suối khoáng nóng thần tài", "suối khoáng nóng thanh tân", "danang downtown", "cung đình triều nguyễn", "làng nghề truyền thống tại huế", "a lưới", "phá tam giang", "sunspa resort", "vedana lagoon resort", "little hawaii thuận an beach", "cù lao xanh", "alba thanh tân hot springs", "đà nẵng"],
    "Miền Tây": ["long an", "tiền giang", "bến tre", "đồng tháp", "vĩnh long", "trà vinh", "hậu giang", "an giang", "sóc trăng", "kiên giang", "bạc liêu", "cà mau", "châu đốc", "miền tây", "hòn sơn", "đảo bà lụa", "hà tiên", "đám giỗ bên cồn", "cái răng", "nam du", "u minh thượng", "u minh hạ", "cái bè", "cồn sơn", "lung ngọc hoàng", "mẹ nam hải", "đức mẹ mekong", "vinh sang", "chợ nổi xứ dừa", "cồn thới sơn", "chùa bà chúa xứ", "vi vu ngày tếtđà nẵng", "rừng tràm", "hòn đá bạc", "đất mũi", "tràm chim", "sa đéc", "nghỉ dưỡng cần thơ", "tour cần thơ", "cần thơ eco resort", "hành hương cha diệp", "cần thơ"],
    "Đông Nam Bộ": ["tây ninh", "nam cát tiên", "đồng nai", "cần giờ", "củ chi", "núi bà đen", "cát tiên", "hồ trị an", "saigon sniper", "bù gia mập", "tour tết sài gòn", "sài gòn", "tp hcm", "hồ chí minh"],
    "Tây Nguyên": ["đà lạt", "măng đen", "buôn ma thuột", "buôn mê thuột", "pleiku", "kontum", "bảo lộc", "tà đùng", "tour camping 2n1đ: trải nghiệm cắm trại và chèo thuyền sup", "tà năng phan dũng", "bidoup", "hang động núi lửa chư bluk", "tây nguyên", "tà năng", "madagui", "tour đà lat", "langbiang", "da lat"],
    "Du Thuyền": ["du thuyền"],
    "Voucher": ["voucher"],
}

_SORTED_KEYWORDS: list[tuple[str, str]] = []


def _build_sorted_keywords() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for market, keywords in MARKET_KEYWORDS.items():
        for kw in keywords:
            pairs.append((kw.lower().strip(), market))
    pairs.sort(key=lambda x: len(x[0]), reverse=True)
    return pairs


def resolve_thi_truong(ten_tour: str, lich_trinh: str = "") -> str:
    """Map tour name + itinerary to Thị trường label."""
    global _SORTED_KEYWORDS
    if not _SORTED_KEYWORDS:
        _SORTED_KEYWORDS = _build_sorted_keywords()

    combined = f"{ten_tour or ''} {lich_trinh or ''}".lower().strip()
    if not combined:
        return "Khác"

    for keyword, market in _SORTED_KEYWORDS:
        if keyword in combined:
            return market
    return "Khác"
