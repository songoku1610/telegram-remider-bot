"""
Chuyển đổi lịch Dương <-> lịch Âm Việt Nam
Thuật toán dựa trên công trình của Ho Ngoc Duc (2004)
https://www.informatik.uni-leipzig.de/~duc/amlich/
"""

import math
from datetime import date


# ─────────────────────────────────────────────────────────────
# Hằng số múi giờ Việt Nam: UTC+7
# ─────────────────────────────────────────────────────────────
TZ_OFFSET = 7  # giờ


# ─────────────────────────────────────────────────────────────
# Hàm nội bộ
# ─────────────────────────────────────────────────────────────

def _jd_from_date(dd: int, mm: int, yy: int) -> int:
    """Chuyển ngày Dương lịch sang Julian Day Number."""
    a = (14 - mm) // 12
    y = yy + 4800 - a
    m = mm + 12 * a - 3
    jd = dd + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045
    if jd < 2299161:
        jd = dd + (153 * m + 2) // 5 + 365 * y + y // 4 - 32083
    return jd


def _jd_to_date(jd: int) -> tuple[int, int, int]:
    """Chuyển Julian Day Number về ngày Dương lịch (dd, mm, yy)."""
    if jd > 2299160:
        a = jd + 32044
        b = (4 * a + 3) // 146097
        c = a - (b * 146097) // 4
    else:
        b = 0
        c = jd + 32082

    d = (4 * c + 3) // 1461
    e = c - (1461 * d) // 4
    m = (5 * e + 2) // 153

    day = e - (153 * m + 2) // 5 + 1
    month = m + 3 - 12 * (m // 10)
    year = b * 100 + d - 4800 + m // 10
    return day, month, year


def _new_moon(k: int) -> float:
    """Thời điểm trăng non thứ k (tính từ 1/1/1900) theo Julian Day, múi giờ UTC."""
    T = k / 1236.85
    T2 = T * T
    T3 = T2 * T
    dr = math.pi / 180

    Jd1 = 2415020.75933 + 29.53058868 * k + 0.0001178 * T2 - 0.000000155 * T3
    Jd1 += 0.00033 * math.sin((166.56 + 132.87 * T - 0.009173 * T2) * dr)

    M = 359.2242 + 29.10535608 * k - 0.0000333 * T2 - 0.00000347 * T3
    Mpr = 306.0253 + 385.81691806 * k + 0.0107306 * T2 + 0.00001236 * T3
    F = 21.2964 + 390.67050646 * k - 0.0016528 * T2 - 0.00000239 * T3

    C1 = (0.1734 - 0.000393 * T) * math.sin(M * dr) + 0.0021 * math.sin(2 * dr * M)
    C1 -= 0.4068 * math.sin(Mpr * dr) + 0.0161 * math.sin(dr * 2 * Mpr)
    C1 -= 0.0004 * math.sin(dr * 3 * Mpr)
    C1 += 0.0104 * math.sin(dr * 2 * F) - 0.0051 * math.sin(dr * (M + Mpr))
    C1 -= 0.0074 * math.sin(dr * (M - Mpr)) + 0.0004 * math.sin(dr * (2 * F + M))
    C1 -= 0.0004 * math.sin(dr * (2 * F - M)) - 0.0006 * math.sin(dr * (2 * F + Mpr))
    C1 += 0.0010 * math.sin(dr * (2 * F - Mpr)) + 0.0005 * math.sin(dr * (M + 2 * Mpr))

    if T < -11:
        deltat = 0.001 + 0.000839 * T + 0.0002261 * T2 - 0.00000845 * T3 - 0.000000081 * T * T3
    else:
        deltat = -0.000278 + 0.000265 * T + 0.000262 * T2

    return Jd1 + C1 - deltat


def _sun_longitude(jdn: float) -> float:
    """Kinh độ mặt trời tại thời điểm Julian Day (độ, 0–11 tương ứng 12 cung hoàng đạo)."""
    T = (jdn - 2451545.0) / 36525
    T2 = T * T
    dr = math.pi / 180
    M = 357.52910 + 35999.05030 * T - 0.0001559 * T2 - 0.00000048 * T * T2
    L0 = 280.46645 + 36000.76983 * T + 0.0003032 * T2
    DL = (1.9146 - 0.004817 * T - 0.000014 * T2) * math.sin(dr * M)
    DL += (0.019993 - 0.000101 * T) * math.sin(dr * 2 * M) + 0.00029 * math.sin(dr * 3 * M)
    theta = L0 + DL
    omega = 125.04 - 1934.136 * T
    theta -= 0.00569 + 0.00478 * math.sin(omega * dr)
    theta = theta * dr
    theta = theta - math.pi * 2 * math.floor(theta / (math.pi * 2))
    return int(theta / math.pi * 6)


def _get_new_moon_day(k: int, tz: int) -> int:
    """Ngày Julian của trăng non thứ k, theo múi giờ tz."""
    return int(_new_moon(k) + 0.5 + tz / 24)


def _get_lunar_month11(yy: int, tz: int) -> int:
    """Ngày Julian của trăng non tháng 11 âm lịch năm yy."""
    off = _jd_from_date(31, 12, yy) - 2415021
    k = int(off / 29.530588853)
    nm = _get_new_moon_day(k, tz)
    sunLong = _sun_longitude(nm)
    if sunLong >= 9:
        nm = _get_new_moon_day(k - 1, tz)
    return nm


def _get_leap_month_offset(a11: int, tz: int) -> int:
    """Trả về vị trí tháng nhuận (0-based) trong năm âm bắt đầu từ a11."""
    k = int((a11 - 2415021.076998695) / 29.530588853 + 0.5)
    last = 0
    i = 1
    arc = _sun_longitude(_get_new_moon_day(k + i, tz))
    while True:
        last = arc
        i += 1
        arc = _sun_longitude(_get_new_moon_day(k + i, tz))
        if arc == last or i >= 14:
            break
    return i - 1


# ─────────────────────────────────────────────────────────────
# API công khai
# ─────────────────────────────────────────────────────────────

def solar_to_lunar(dd: int, mm: int, yy: int) -> tuple[int, int, int, bool]:
    """
    Chuyển ngày Dương lịch (dd, mm, yy) sang Âm lịch Việt Nam.

    Trả về:
        (ngay_am, thang_am, nam_am, la_thang_nhuan)
        la_thang_nhuan = True nếu tháng đó là tháng nhuận.

    Ví dụ:
        >>> solar_to_lunar(2, 6, 2026)
        (7, 5, 2026, False)
    """
    tz = TZ_OFFSET
    dayNumber = _jd_from_date(dd, mm, yy)
    k = int((dayNumber - 2415021.076998695) / 29.530588853)
    monthStart = _get_new_moon_day(k + 1, tz)
    if monthStart > dayNumber:
        monthStart = _get_new_moon_day(k, tz)

    a11 = _get_lunar_month11(yy, tz)
    b11 = a11
    if a11 >= monthStart:
        lunarYear = yy
        a11 = _get_lunar_month11(yy - 1, tz)
    else:
        lunarYear = yy + 1
        b11 = _get_lunar_month11(yy + 1, tz)

    lunarDay = dayNumber - monthStart + 1
    diff = int((monthStart - a11) / 29)
    lunarLeap = False
    lunarMonth = diff + 11

    if b11 - a11 > 365:
        leapMonthDiff = _get_leap_month_offset(a11, tz)
        if diff >= leapMonthDiff:
            lunarMonth = diff + 10
            if diff == leapMonthDiff:
                lunarLeap = True

    if lunarMonth > 12:
        lunarMonth -= 12
    if lunarMonth >= 11 and diff < 4:
        lunarYear -= 1

    return lunarDay, lunarMonth, lunarYear, lunarLeap


def lunar_to_solar(lunar_day: int, lunar_month: int, lunar_year: int,
                   lunar_leap: bool = False) -> tuple[int, int, int]:
    """
    Chuyển ngày Âm lịch Việt Nam sang Dương lịch.

    Tham số:
        lunar_day   : ngày âm lịch
        lunar_month : tháng âm lịch
        lunar_year  : năm âm lịch
        lunar_leap  : True nếu là tháng nhuận (mặc định False)

    Trả về:
        (dd, mm, yy) theo Dương lịch

    Ví dụ:
        >>> lunar_to_solar(7, 5, 2026)
        (2, 6, 2026)
    """
    tz = TZ_OFFSET

    if lunar_month < 11:
        a11 = _get_lunar_month11(lunar_year - 1, tz)
        b11 = _get_lunar_month11(lunar_year, tz)
    else:
        a11 = _get_lunar_month11(lunar_year, tz)
        b11 = _get_lunar_month11(lunar_year + 1, tz)

    k = int(0.5 + (a11 - 2415021.076998695) / 29.530588853)
    off = lunar_month - 11
    if off < 0:
        off += 12

    if b11 - a11 > 365:
        leapOff = _get_leap_month_offset(a11, tz)
        leapMonth = leapOff - 2
        if leapMonth < 0:
            leapMonth += 12
        if lunar_leap and lunar_month != leapMonth:
            return (0, 0, 0)  # tháng nhuận không hợp lệ
        if lunar_leap or off >= leapOff:
            off += 1

    monthStart = _get_new_moon_day(k + off, tz)
    jd = monthStart + lunar_day - 1
    return _jd_to_date(jd)
