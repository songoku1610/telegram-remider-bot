import os
import re
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

import mysql.connector
import dateparser
import unicodedata
from dateutil.relativedelta import relativedelta
from weatherAPI import format_tomorrow_7am_forecast, format_tomorrow_day_forecast, format_weather_info
from lunarcalendar import solar_to_lunar, lunar_to_solar


from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
BOT_TOKEN = None
TIME_INFORMATION = None
WEATHER_INFORMATION_TIMEZONE = None
db = None
cursor = None


def init():
    global BOT_TOKEN, TIME_INFORMATION, WEATHER_INFORMATION_TIMEZONE, db, cursor

    load_dotenv()

    BOT_TOKEN = os.getenv("BOT_TOKEN")
    TIME_INFORMATION = os.getenv("TIME_INFORMATION")
    WEATHER_INFORMATION_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")

    db = mysql.connector.connect(
        host=os.getenv("DB_HOST", "db"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "reminder_db"),
    )

    cursor = db.cursor(dictionary=True)
    migrate()


def migrate():
    """Tự động thêm cột mới nếu chưa có. An toàn khi chạy nhiều lần."""
    migrations = [
        "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS is_lunar     BOOLEAN          DEFAULT FALSE",
        "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS lunar_day    TINYINT UNSIGNED DEFAULT NULL",
        "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS lunar_month  TINYINT UNSIGNED DEFAULT NULL",
        "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS lunar_year   SMALLINT UNSIGNED DEFAULT NULL",
        "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS lunar_leap   BOOLEAN          DEFAULT FALSE",
    ]
    c = db.cursor()
    for sql in migrations:
        try:
            c.execute(sql)
        except Exception as e:
            print(f"MIGRATE SKIP: {e}", flush=True)
    db.commit()
    c.close()
    print("DB migration done.", flush=True)


def ensure_connection():
    """Ping DB và tạo lại cursor. Raise exception nếu không kết nối được."""
    global cursor
    db.ping(reconnect=True, attempts=3, delay=2)
    cursor = db.cursor(dictionary=True)


# =========================
# REPEAT
# =========================
def normalize_repeat(text):
    text = text.lower().strip()
    mapping = {
        "daily": "daily",
        "weekly": "weekly",
        "monthly": "monthly",
        "yearly": "yearly",
        "hàng ngày": "daily",
        "hang ngay": "daily",
        "hàng tuần": "weekly",
        "hang tuan": "weekly",

        "hàng tháng": "monthly",
        "hang thang": "monthly",
        "hàng năm": "yearly",
        "hang nam": "yearly",
    }
    return mapping.get(text, None)

# =========================
# CUSTOM INTERVAL REPEAT
# =========================
_CUSTOM_REPEAT_RE = re.compile(
    r"(?:lặp\s+lại\s+|lap\s+lai\s+)?(?:repeat\s+)?(?:mỗi|moi|every)\s+(\d+)\s*"
    r"(ngày|ngay|tuần|tuan|tháng|thang|năm|nam|days?|weeks?|months?|years?)",
    re.IGNORECASE,
)
_INTERVAL_UNIT_MAP = {
    "ngày": "d", "ngay": "d", "day": "d", "days": "d",
    "tuần": "w", "tuan": "w", "week": "w", "weeks": "w",
    "tháng": "m", "thang": "m", "month": "m", "months": "m",
    "năm": "y",  "nam": "y",  "year": "y", "years": "y",
}


def extract_custom_repeat(text):
    """Trích xuất 'mỗi N <đơn vị>' / 'every N <unit>' từ text.
    Trả về (encoded_type, cleaned_text) hoặc (None, text).
    Encoded format: every_Nd / every_Nw / every_Nm / every_Ny"""
    m = _CUSTOM_REPEAT_RE.search(text)
    if not m:
        return None, text
    n = int(m.group(1))
    unit = _INTERVAL_UNIT_MAP.get(m.group(2).lower())
    if not unit or n < 1:
        return None, text
    encoded = f"every_{n}{unit}"
    cleaned = (text[: m.start()] + text[m.end() :]).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return encoded, cleaned


def decode_interval(repeat_type):
    """Giải mã every_Nd → 'mỗi N ngày'. Trả None nếu không phải custom interval."""
    m = re.fullmatch(r"every_(\d+)([dwmy])", repeat_type)
    if not m:
        return None
    n, u = int(m.group(1)), m.group(2)
    unit_vi = {"d": "ngày", "w": "tuần", "m": "tháng", "y": "năm"}[u]
    return f"mỗi {n} {unit_vi}"


def format_repeat_type(repeat_type):
    """Chuyển repeat_type sang chuỗi tiếng Việt để hiển thị."""
    _MAP = {
        "none":    "không lặp",
        "daily":   "hàng ngày",
        "weekly":  "hàng tuần",
        "monthly": "hàng tháng",
        "yearly":  "hàng năm",
    }
    if repeat_type in _MAP:
        return _MAP[repeat_type]
    decoded = decode_interval(repeat_type)
    return decoded if decoded else repeat_type


# =========================
# LUNAR CALENDAR
# =========================
LUNAR_KEYWORDS_RE = re.compile(r'lịch\s*âm|âm\s*lịch', re.IGNORECASE)


def _extract_lunar_date_parts(text_norm):
    """Trích xuất (ngay, thang, chuỗi_khớp) từ text âm lịch đã normalize. Trả None nếu không tìm thấy."""
    # rằm tháng X (X = số hoặc giêng)
    m = re.search(r'rằm\s+tháng\s+(giêng|\d{1,2})', text_norm)
    if m:
        month = 1 if 'giêng' in m.group(1) else int(m.group(1))
        return 15, month, m.group(0)

    # [ngày/mùng/mung] DD tháng [giêng/MM]
    m = re.search(r'(?:(?:ngày|mùng|mung)\s+)?(\d{1,2})\s+tháng\s+(giêng|\d{1,2})', text_norm)
    if m:
        month = 1 if 'giêng' in m.group(2) else int(m.group(2))
        return int(m.group(1)), month, m.group(0)

    # DD/MM[/YYYY]
    m = re.search(r'\b(\d{1,2})/(\d{1,2})(?:/\d{4})?\b', text_norm)
    if m:
        return int(m.group(1)), int(m.group(2)), m.group(0)

    return None


def parse_lunar_reminder(original_text):
    """
    Parse câu lệnh có chứa 'lịch âm' / 'âm lịch'.
    Trả về (message, remind_time, repeat_type, lunar_day, lunar_month, lunar_year, lunar_leap)
    hoặc None nếu không parse được.
    """
    lines = [l.strip() for l in original_text.splitlines() if l.strip()]
    first_line = lines[0] if lines else original_text
    extra_lines = lines[1:]

    # 1. Tách repeat type
    repeat_type = "none"
    _custom, first_line = extract_custom_repeat(first_line)
    if _custom:
        repeat_type = _custom
    else:
        repeat_match = re.search(
            r"(repeat\s+)?(hàng ngày|hang ngay|daily|hàng tuần|hang tuan|weekly|hàng tháng|hang thang|monthly|hàng năm|hang nam|yearly)",
            first_line, re.IGNORECASE)
        if repeat_match:
            repeat_type = normalize_repeat(repeat_match.group(2))
            first_line = first_line.replace(repeat_match.group(0), "").strip()

    # 2. Xóa lunar keyword
    first_line = LUNAR_KEYWORDS_RE.sub(' ', first_line).strip()

    # 3. Normalize để tìm kiếm
    first_norm = normalize(first_line)

    # 4. Trích xuất ngày âm lịch
    date_result = _extract_lunar_date_parts(first_norm)
    if not date_result:
        return None
    lunar_day, lunar_month, _date_matched = date_result

    # 5. Xác định năm âm lịch
    now = datetime.now()
    m_year = re.search(r'năm\s+(\d{4})', first_norm)
    if m_year:
        lunar_year = int(m_year.group(1))
    else:
        _, _, lunar_year, _ = solar_to_lunar(now.day, now.month, now.year)

    # 6. Xóa date/năm khỏi first_line để lấy giờ + message
    stripped = first_line
    stripped = re.sub(r'rằm\s+tháng\s+(?:giêng|\d{1,2})', ' ', stripped, flags=re.IGNORECASE)
    stripped = re.sub(r'(?:ngày\s+|mùng\s+|mung\s+)?\d{1,2}\s+tháng\s+(?:giêng|\d{1,2})', ' ', stripped, flags=re.IGNORECASE)
    stripped = re.sub(r'\b\d{1,2}/\d{1,2}(?:/\d{4})?\b', ' ', stripped)
    stripped = re.sub(r'năm\s+\d{4}', ' ', stripped, flags=re.IGNORECASE)
    stripped = re.sub(r'\bngày\b', ' ', stripped, flags=re.IGNORECASE)
    stripped = stripped.strip()

    # 7. Trích giờ từ phần còn lại
    hour, minute = extract_time(normalize(stripped)) if re.search(r'\d', stripped) else (9, 0)

    # 8. Xóa giờ và giới từ để lấy message
    msg = re.sub(r'\b\d{1,2}(?:[:.h]\d{0,2})?\s*(?:giờ(?:\s+\d{1,2})?)?\s*(?:sáng|chiều|tối)?\b', ' ', stripped, flags=re.IGNORECASE)
    msg = re.sub(r'\b(?:lúc|luc|vào|vao|at)\b', ' ', msg, flags=re.IGNORECASE)
    msg = re.sub(r'\s+', ' ', msg).strip()

    if extra_lines:
        msg = msg + '\n' + '\n'.join(extra_lines)

    if not msg:
        return None

    # 9. Convert âm → dương
    sol_d, sol_m, sol_y = lunar_to_solar(lunar_day, lunar_month, lunar_year)
    if sol_d == 0:
        return None

    remind_time = datetime(sol_y, sol_m, sol_d, hour, minute, 0)
    if remind_time <= now:
        sol_d2, sol_m2, sol_y2 = lunar_to_solar(lunar_day, lunar_month, lunar_year + 1)
        if sol_d2 > 0:
            remind_time = datetime(sol_y2, sol_m2, sol_d2, hour, minute, 0)
            lunar_year += 1

    # Xác nhận lại thông tin âm lịch từ ngày dương vừa tính
    act_d, act_m, act_y, act_leap = solar_to_lunar(remind_time.day, remind_time.month, remind_time.year)

    return msg, remind_time, repeat_type, act_d, act_m, act_y, act_leap


# =========================
# TIME PARSER
# =========================
WEEKDAY_MAP = {
    "thứ 2": 0,
    "thứ 3": 1,
    "thứ 4": 2,
    "thứ 5": 3,
    "thứ 6": 4,
    "thứ 7": 5,
    "chủ nhật": 6,
    "t2": 0,
    "t3": 1,
    "t4": 2,
    "t5": 3,
    "t6": 4,
    "t7": 5,
}


# =========================
# NORMALIZE
# =========================
def normalize(text):
    text = unicodedata.normalize("NFKC", text)
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text

# =========================
# EXTRACT TIME
# =========================
def extract_time(text):
    m = re.search(r"(\d{1,2})(?:[:h](\d{1,2}))?", text)
    if not m:
        return 9, 0

    hour = int(m.group(1))
    minute = int(m.group(2) or 0)

    # Ưu tiên dạng "X giờ Y" — phải parse trước AM/PM adjustment
    m2 = re.search(r"(\d{1,2})\s*giờ\s*(\d{1,2})?", text)
    if m2:
        hour = int(m2.group(1))
        minute = int(m2.group(2) or 0)

    # sáng / chiều / tối (áp dụng sau khi đã có giờ cuối cùng)
    if "chiều" in text or "tối" in text:
        if hour < 12:
            hour += 12

    if "sáng" in text and hour == 12:
        hour = 0

    return hour, minute


def get_weekday(base, weekday, offset):
    start = base - timedelta(days=base.weekday())
    return start + timedelta(days=weekday + 7 * offset)


WEEKDAY_VI = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]

def weekday_vi(dt: datetime) -> str:
    return WEEKDAY_VI[dt.weekday()]

# =========================
# EXTRACT TIME (xịn)
# =========================
def extract_time_advanced(text):
    text = text.lower()

    match = re.search(r"(\d{1,2})(?:[:h](\d{1,2}))?", text)
    if not match:
        return 9, 0  # default

    hour = int(match.group(1))
    minute = int(match.group(2) or 0)

    # xử lý sáng / chiều / tối
    if "chiều" in text or "tối" in text:
        if hour < 12:
            hour += 12

    if "sáng" in text:
        if hour == 12:
            hour = 0

    return hour, minute




# =========================
# MAIN PARSER
# =========================
def parse_time(text):
    try:
        text = normalize(text)
        now = datetime.now()
        print("Now:", now, flush=True)
        print("PARSING:", text, flush=True)

        # =========================
        # 1. RELATIVE TIME
        # =========================
        m = re.search(r"(\d+)\s*(phút|phut|p|')\s*nữa", text)
        if m:
            return now + timedelta(minutes=int(m.group(1)))

        m = re.search(r"(\d+)\s*(giờ|gio|h)\s*nữa", text)
        if m:
            return now + timedelta(hours=int(m.group(1)))

        # =========================
        # 2. EXTRACT TIME
        # =========================
        hour, minute = extract_time(text)

        # =========================
        # 3. TODAY / TOMORROW
        # =========================
        if "hôm nay" in text:
            return now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        if "mai" in text:
            return (now + timedelta(days=1)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )

        # =========================
        # 4. WEEKDAY
        # =========================
        for k, v in WEEKDAY_MAP.items():
            if k in text:
                # Tách weekday token ra trước khi extract giờ để tránh "t6" → hour=6
                time_only = text.replace(k, "").strip()
                hour, minute = extract_time(time_only) if re.search(r'\d', time_only) else (9, 0)

                if "tuần tới" in text or "tuần sau" in text:
                    dt = get_weekday(now, v, 1)
                elif "tuần này" in text:
                    dt = get_weekday(now, v, 0)
                else:
                    dt = get_weekday(now, v, 0)
                    dt = dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    if dt <= now:
                        dt += timedelta(days=7)
                    return dt

                return dt.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # =========================
        # 5. ONLY TIME (CHỈ KHI TEXT NGẮN)
        # =========================
        
        if re.fullmatch(r"^\d{1,2}(?:[:h]\d{0,2})?$", text):
            dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            print("ONLY TIME PARSED:", dt, flush=True)
            if dt <= now:
                dt += timedelta(days=1)
                print("ADJUSTED TO TOMORROW:", dt, flush=True)
            print("FINAL ONLY TIME:", dt, flush=True)
            return dt

        # =========================
        #  dạng "14 giờ 30" hoặc "14 giờ"
        # =========================
        m = re.fullmatch(r"(\d{1,2})\s*giờ(?:\s*(\d{1,2}))?", text)
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2) or 0)
            dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if dt <= now:
                dt += timedelta(days=1)
            return dt

        # =========================
        # 6. FALLBACK
        # =========================
        print("FALLBACK PARSE Text:", text, flush=True)
        text = re.sub(r"(\d{1,2})\s*h\s*(\d{1,2})", r"\1:\2", text)
        text = re.sub(r"(\d{1,2})\s*h\b", r"\1:00", text)
        print("FALLBACK PARSE Text after:", text, flush=True)
        
        dt = dateparser.parse(
            text,
            languages=["vi", "en"],
            settings={
                "TIMEZONE": "Asia/Ho_Chi_Minh",
                "PREFER_DATES_FROM": "future",
                "DATE_ORDER": "DMY",
            },
        )

        print("FALLBACK PARSED:", dt, flush=True)
        # Nếu dateparser không tìm thấy giờ → trả về 00:00, chuẩn hóa về 09:00
        if dt and dt.hour == 0 and dt.minute == 0:
            # Kiểm tra text gốc có chứa thông tin giờ không
            if not re.search(r'\d{1,2}\s*(?:h|giờ|gio|:|\.)\s*\d{0,2}|\b0\d\b', text):
                dt = dt.replace(hour=9, minute=0, second=0)
        return dt

    except Exception as e:
        print("PARSE ERROR:", e, flush=True)
        return None


def parse_time_new(text):
    try:
        text = normalize(text)
        now = datetime.now()
        print("Now(new):", now, flush=True)
        print("PARSING(new):", text, flush=True)

        m = re.match(
            r"^(thứ\s*[2-7]|t[2-7]|chủ nhật)\s*[,\-]?\s*(\d{1,2}(?:[.:h]\d{1,2})?)\s*$",
            text,
            re.IGNORECASE,
        )
        if not m:
            return None

        weekday_text = normalize(m.group(1))
        time_text = m.group(2)

        weekday_map = {
            "thứ 2": 0,
            "thứ 3": 1,
            "thứ 4": 2,
            "thứ 5": 3,
            "thứ 6": 4,
            "thứ 7": 5,
            "chủ nhật": 6,
            "t2": 0,
            "t3": 1,
            "t4": 2,
            "t5": 3,
            "t6": 4,
            "t7": 5,
        }

        weekday = weekday_map.get(weekday_text)
        if weekday is None:
            return None

        time_norm = re.sub(r"\s*[.:h]\s*", ":", time_text)
        hour, minute = extract_time(time_norm)
        # remind_before = timedelta(minutes=15)
        dt = get_weekday(now, weekday, 0)
        dt = dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if dt <= now:
            dt += timedelta(days=7)
        # dt -= remind_before
        return dt

    except Exception as e:
        print("PARSE NEW ERROR:", e, flush=True)
        return None
# =========================
# PARSE MESSAGE
# =========================
def parse_message(text):
    try:
        repeat_type = "none"

        _custom, text = extract_custom_repeat(text)
        if _custom:
            repeat_type = _custom
        else:
            repeat_match = re.search(
                r"(repeat\s+)?(hàng ngày|hang ngay|daily|hàng tuần|hang tuan|weekly|hàng tháng|hang thang|monthly|hàng năm|hang nam|yearly)",
                text,
                re.IGNORECASE,
            )
            if repeat_match:
                repeat_type = normalize_repeat(repeat_match.group(2))
                text = text.replace(repeat_match.group(0), "")

        parts = re.split(r"\s(at|lúc|luc|vao|vào|@)\s", text, maxsplit=1, flags=re.IGNORECASE)

        # Xử lý edge case: sau khi strip repeat, separator lúc/at/vào còn đứng đầu text
        if len(parts) < 3:
            text2 = re.sub(r"^(?:lúc|luc|vào|vao|at)\s+", "", text.strip(), flags=re.IGNORECASE)
            if text2 != text:
                parts = re.split(r"\s(at|lúc|luc|vao|vào|@)\s", text2, maxsplit=1, flags=re.IGNORECASE)
                if len(parts) < 3:
                    text = text2  # cập nhật text cho timefirst fallback

        if len(parts) < 3:
            result = parse_message_timefirst(text)
            if result and repeat_type != "none":
                return result[0], result[1], repeat_type
            return result

        message = parts[0].strip()
        time_part = parts[2].strip()
        remind_time =  parse_time(time_part) or parse_time_new(time_part)
        if not remind_time:
            result = parse_message_timefirst(text)
            if result and repeat_type != "none":
                return result[0], result[1], repeat_type
            return result

        return message, remind_time, repeat_type or "none"

    except Exception as e:
        print("PARSE ERROR:", e, flush=True)
        return None


def parse_message_timefirst(text):
    try:
        repeat_type = "none"
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return None

        first_line = lines[0]
        extra_lines = lines[1:]

        # Dạng: "14.00 nội dung..." hoặc "Thứ 4, 14.00 nội dung..."
        m = re.match(
            r"^(?:(thứ\s*[2-7]|t[2-7]|chủ nhật)\s*[,\-]?\s*)?(\d{1,2}(?:[.:h]\d{1,2})?)\s+(.*)$",
            first_line,
            re.IGNORECASE,
        )

        if m:
            prefix = m.group(1) or ""
            time_text = m.group(2)
            message = m.group(3).strip()

            if extra_lines:
                message = message + "\n" + "\n".join(extra_lines)

            time_part = f"{prefix} {time_text}".strip()
            remind_time = parse_time_new(time_part) or parse_time(time_part)
            if not remind_time:
                return None
            print("new parse message:", message, "time part:", time_part, "remind_time:", remind_time, flush=True)
            remind_before = timedelta(minutes=15)
            remind_time -= remind_before
            return message, remind_time, repeat_type or "none"

        return None

    except Exception as e:
        print("PARSE ERROR:", e, flush=True)
        return None
# =========================
# HANDLER
# =========================
async def send_help(update: Update):
    await update.message.reply_text(
         "<b>📌 Cách dùng</b>\n\n"
            "1. <b>Thêm reminder</b>\n"
            "   Dạng đầy đủ: <code>Nội dung at/lúc/vào thời gian [repeat tần suất]</code>\n"
            "   Dạng nhanh — thời gian đứng đầu:\n"
            "   • <code>14.00 Nội dung</code>\n"
            "   • <code>Thứ 4, 14.00 Nội dung</code>\n"
            "   • <code>T4 14.00 Nội dung</code>  |  <code>T4, 14.00 Nội dung</code>  |  <code>T4-14.00 Nội dung</code>\n"
            "   Hỗ trợ T2 T3 T4 T5 T6 T7 và Thứ 2 … Thứ 7\n"
            "   Nếu không nhập giờ, mặc định nhắc lúc <b>9:00</b>\n\n"
            "   <b>Tần suất lặp cố định:</b> <code>hàng ngày</code> | <code>hàng tuần</code> | <code>hàng tháng</code> | <code>hàng năm</code>\n"
            "   <b>Tần suất lặp tuỳ ý:</b> <code>mỗi N ngày</code> | <code>mỗi N tuần</code> | <code>mỗi N tháng</code> | <code>mỗi N năm</code>\n"
            "   Ví dụ:\n"
            "   • <code>Họp với team lúc 3h chiều hàng ngày</code>\n"
            "   • <code>T4, 14.00 A.XYZ họp rà soát Kế hoạch</code>\n"
            "   • <code>Làm dự toán vào 8h ngày 02/05/2026 hàng tháng</code>\n"
            "   • <code>Khám định kỳ lúc 9h ngày 15/07/2026 mỗi 6 tháng</code>\n"
            "   • <code>Uống thuốc lúc 8h hôm nay mỗi 3 ngày</code>\n"
            "   • <code>Gia hạn domain lúc 9h ngày 05/06/2027 mỗi 2 năm</code>\n\n"
            "   <b>🌙 Lịch âm</b> — thêm <code>âm lịch</code> hoặc <code>lịch âm</code> vào cuối:\n"
            "   • <code>Giỗ ông nội lúc 8h ngày 15/3 âm lịch hàng năm</code>\n"
            "   • <code>Cúng rằm tháng 7 lúc 9h âm lịch hàng năm</code>\n"
            "   • <code>Mùng 1 tháng giêng 8h Chúc tết âm lịch</code>\n"
            "   Bot tự convert sang dương lịch, nhắc đúng theo âm lịch mỗi chu kỳ.\n"
            "   Tần suất tuỳ ý cũng áp dụng cho lịch âm:\n"
            "   • <code>Giỗ cụ lúc 8h ngày 10/2 âm lịch mỗi 1 năm</code>\n"
            "   • <code>Cúng tổ lúc 9h ngày 15/3 âm lịch mỗi 3 năm</code>\n"
            "   • <code>Cúng mùng 1 lúc 6h tháng giêng âm lịch mỗi 6 tháng</code>\n"
            "   Lịch <b>hàng tháng / hàng năm</b> và <b>mỗi N tháng / mỗi N năm</b> sẽ được nhắc thêm <b>trước 1 ngày</b> cùng giờ.\n\n"
            "2. <b>Xem reminder:</b> <code>ls</code> — xem tất cả\n"
            "   Lọc theo loại: <code>ls none</code> | <code>ls daily</code> | <code>ls monthly</code> | <code>ls weekly</code> | <code>ls yearly</code>\n"
            "   Lọc theo thời gian: <code>ls today</code> hoặc <code>ls hôm nay</code> — hôm nay, chưa nhắc\n"
            "                       <code>ls week</code> hoặc <code>ls tuần</code> — lịch tuần này\n"
            "                       <code>ls month</code> hoặc <code>ls tháng</code> — lịch tháng này\n"
            "   Tìm kiếm: <code>ls từ khoá</code>\n"
            "   Reminder âm lịch hiển thị thêm dòng ngày tháng âm lịch tương ứng.\n\n"
            "3. <b>Xoá reminder:</b> <code>del ID</code> hoặc <code>delete ID</code>\n"
            "   ID lấy từ lệnh xem reminder\n\n"
            "4. <b>Tra cứu lịch âm/dương:</b>\n"
            "   • <code>al</code> — ngày âm lịch hôm nay\n"
            "   • <code>al 15/3/2026</code> — dương → âm\n"
            "   • <code>dl 15/3/2026</code> — âm → dương\n\n"
            "5. <b>Thời tiết hiện tại:</b> <code>weather</code> hoặc <code>wt</code> hoặc <code>tt</code>\n\n"
            "5. <b>Thời tiết theo thành phố:</b> <code>wt {tên thành phố}</code>\n"
            "   Ví dụ: <code>wt Bac Ninh</code>, <code>wt Ha Noi</code>, <code>wt Singapore</code>\n"
            "   Bot gửi thời tiết hiện tại + dự báo cả ngày mai.\n"
            "   Ngoài ra bot tự động gửi dự báo thời tiết vào giờ TIME_INFORMATION trong .env.",
        parse_mode="HTML",
    )


async def add_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id
    try:
        ensure_connection()
    except Exception as e:
        print("DB RECONNECT ERROR:", e, flush=True)
        await update.message.reply_text("❌ Lỗi kết nối database, vui lòng thử lại sau.")
        return
    text_lower = text.lower()
    if text_lower in ["weather", "wt", "tt"]:
        try:
            weather_text = await asyncio.to_thread(format_weather_info)
            await update.message.reply_text(weather_text)
        except Exception as exc:
            await update.message.reply_text(f"Khong lay duoc thong tin thoi tiet: {exc}")
        return

    if text_lower.startswith("wt "):
        city = text[3:].strip()
        if city:
            try:
                weather_text = await asyncio.to_thread(format_weather_info, city)
                await update.message.reply_text(weather_text)
            except Exception as exc:
                await update.message.reply_text(f"Không lấy được thời tiết hiện tại: {exc}")
            try:
                forecast_text = await asyncio.to_thread(format_tomorrow_day_forecast, city)
                await update.message.reply_text(forecast_text)
            except Exception as exc:
                await update.message.reply_text(f"Không lấy được dự báo ngày mai: {exc}")
            return

    # ====== HELP =====
    if text in ["help", "h", "giúp", "giup"]:
        await send_help(update)
        return

    # ====== AL: dương → âm ======
    if text_lower == "al" or text_lower.startswith("al "):
        arg = text[2:].strip()
        try:
            if arg:
                m = re.fullmatch(r'(\d{1,2})[/\-\.](\d{1,2})(?:[/\-\.](\d{2,4}))?', arg)
                if not m:
                    await update.message.reply_text("❌ Định dạng không hợp lệ. Dùng: <code>al dd/mm/yyyy</code> hoặc <code>al dd/mm/yy</code>", parse_mode="HTML")
                    return
                dd, mm = int(m.group(1)), int(m.group(2))
                yy = int(m.group(3)) if m.group(3) else datetime.now().year
                if yy < 100:
                    yy += 2000
            else:
                now = datetime.now()
                dd, mm, yy = now.day, now.month, now.year
            ld, lm, ly, lleap = solar_to_lunar(dd, mm, yy)
            leap_str = " (nhuận)" if lleap else ""
            await update.message.reply_text(
                f"🗓 <b>{dd:02d}/{mm:02d}/{yy} dương lịch</b>\n"
                f"🌙 Tức ngày <b>{ld} tháng {lm}{leap_str} năm {ly}</b> âm lịch",
                parse_mode="HTML"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Lỗi: {e}")
        return

    # ====== DL: âm → dương ======
    if text_lower.startswith("dl "):
        arg = text[3:].strip()
        try:
            m = re.fullmatch(r'(\d{1,2})[/\-\.](\d{1,2})(?:[/\-\.](\d{2,4}))?', arg)
            if not m:
                await update.message.reply_text("❌ Định dạng không hợp lệ. Dùng: <code>dl dd/mm/yyyy</code>", parse_mode="HTML")
                return
            ld, lm = int(m.group(1)), int(m.group(2))
            ly = int(m.group(3)) if m.group(3) else solar_to_lunar(datetime.now().day, datetime.now().month, datetime.now().year)[2]
            if ly < 100:
                ly += 2000
            sd, sm, sy = lunar_to_solar(ld, lm, ly)
            if sd == 0:
                await update.message.reply_text("❌ Ngày âm lịch không hợp lệ.")
                return
            await update.message.reply_text(
                f"🌙 <b>{ld} tháng {lm} năm {ly} âm lịch</b>\n"
                f"🗓 Tức ngày <b>{sd:02d}/{sm:02d}/{sy}</b> dương lịch",
                parse_mode="HTML"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Lỗi: {e}")
        return


    # ===== LIST tự nhiên =====
    _ls_prefixes = ["ls", "list", "xem", "danh sách", "danhsach"]
    _is_ls = (
        text.lower() in _ls_prefixes
        or any(text.lower().startswith(p + " ") for p in _ls_prefixes)
    )
    if _is_ls:
        # Xác định filter
        _filter_type = None   # None = tất cả
        _keyword = None

        # Tách phần sau prefix
        _suffix = ""
        for _p in sorted(_ls_prefixes, key=len, reverse=True):
            if text.lower() == _p:
                _suffix = ""
                break
            if text.lower().startswith(_p + " "):
                _suffix = text[len(_p):].strip()
                break

        _REPEAT_FILTERS = {
            "none": "none",
            "daily": "daily",
            "hàng ngày": "daily",
            "hang ngay": "daily",
            "weekly": "weekly",
            "hàng tuần": "weekly",
            "hang tuan": "weekly",
            "monthly": "monthly",
            "hàng tháng": "monthly",
            "hang thang": "monthly",
            "yearly": "yearly",
            "hàng năm": "yearly",
            "hang nam": "yearly",
        }

        _WEEK_KEYWORDS  = {"week", "tuần", "tuan", "tuần này", "tuan nay"}
        _MONTH_KEYWORDS = {"month", "tháng", "thang", "tháng này", "thang nay"}
        _TODAY_KEYWORDS = {"today", "hôm nay", "hom nay"}

        _suffix_lower = _suffix.lower()

        if _suffix_lower in _TODAY_KEYWORDS:
            # Reminders trong ngày hôm nay chưa được nhắc (remind_at >= now)
            now_local = datetime.now(WEATHER_INFORMATION_TIMEZONE)
            today_end = (now_local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            now_naive = now_local.replace(tzinfo=None)
            today_end_naive = today_end.replace(tzinfo=None)
            cursor.execute(
                """
                SELECT * FROM reminders
                WHERE user_id = %s AND is_active = TRUE
                  AND remind_at >= %s AND remind_at < %s
                ORDER BY remind_at ASC
                """,
                (user_id, now_naive, today_end_naive),
            )
            rows = cursor.fetchall()
            title = f"📅 Lịch hôm nay ({now_local.strftime('%d/%m/%Y')}) — chưa nhắc"

        elif _suffix_lower in _WEEK_KEYWORDS:
            # Reminders trong tuần hiện tại (T2–CN)
            now_local = datetime.now(WEATHER_INFORMATION_TIMEZONE)
            week_start = (now_local - timedelta(days=now_local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            week_end   = week_start + timedelta(days=7)
            cursor.execute(
                """
                SELECT * FROM reminders
                WHERE user_id = %s AND is_active = TRUE
                  AND remind_at >= %s AND remind_at < %s
                ORDER BY remind_at ASC
                """,
                (user_id, week_start, week_end),
            )
            rows = cursor.fetchall()
            title = f"📅 Lịch tuần {week_start.strftime('%d/%m')}–{(week_end - timedelta(days=1)).strftime('%d/%m/%Y')}"

        elif _suffix_lower in _MONTH_KEYWORDS:
            # Reminders trong tháng hiện tại
            now_local = datetime.now(WEATHER_INFORMATION_TIMEZONE)
            month_start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if now_local.month == 12:
                month_end = now_local.replace(year=now_local.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            else:
                month_end = now_local.replace(month=now_local.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
            cursor.execute(
                """
                SELECT * FROM reminders
                WHERE user_id = %s AND is_active = TRUE
                  AND remind_at >= %s AND remind_at < %s
                ORDER BY remind_at ASC
                """,
                (user_id, month_start, month_end),
            )
            rows = cursor.fetchall()
            title = f"📅 Lịch tháng {now_local.strftime('%m/%Y')}"

        else:
            title = "📋 Reminder"
            if _suffix_lower in _REPEAT_FILTERS:
                _filter_type = _REPEAT_FILTERS[_suffix_lower]
            elif _suffix:
                _keyword = _suffix_lower

            if _filter_type is not None:
                cursor.execute(
                    "SELECT * FROM reminders WHERE user_id=%s AND is_active=TRUE AND repeat_type=%s ORDER BY remind_at DESC",
                    (user_id, _filter_type),
                )
            elif _keyword is not None:
                cursor.execute(
                    "SELECT * FROM reminders WHERE user_id=%s AND is_active=TRUE AND LOWER(message) LIKE %s ORDER BY remind_at DESC",
                    (user_id, f"%{_keyword}%"),
                )
            else:
                cursor.execute(
                    "SELECT * FROM reminders WHERE user_id=%s AND is_active=TRUE ORDER BY remind_at DESC",
                    (user_id,),
                )
            rows = cursor.fetchall()

        if not rows:
            await update.message.reply_text("📭 Dạ anh chưa có lịch gì ạ!")
            return

        msg = f"{title}:\n\n"
        for r in rows:
            lunar_line = ""
            if r.get("is_lunar") and r.get("lunar_day"):
                lunar_label = f"tháng {r['lunar_month']}" + (" nhuận" if r.get("lunar_leap") else "")
                lunar_line = f"\n🌙 Âm lịch: ngày {r['lunar_day']} {lunar_label} năm {r['lunar_year']} {r['remind_at'].strftime('%H:%M')}"
            wd = weekday_vi(r['remind_at'])
            msg += f"""ID: {r['id']}
⏰ {wd}, {r['remind_at'].strftime('%d-%m-%Y %H:%M')}{lunar_line}
📌 {r['message']}
🔁 {format_repeat_type(r['repeat_type'])}

"""
        await update.message.reply_text(msg)
        return

    # ===== DELETE tự nhiên =====
    match_del = re.match(r"(del|delete|xoá|xoa)\s+(\d+)", text)
    if match_del:
        rid = match_del.group(2)

        cursor.execute(
            "UPDATE reminders SET is_active=FALSE WHERE id=%s AND user_id=%s",
            (rid, user_id),
        )
        db.commit()

        await update.message.reply_text(f"🗑️ Em đã bỏ {rid} ra khỏi lịch của anh ạ")
        return

    # ===== ADD =====
    is_lunar = bool(LUNAR_KEYWORDS_RE.search(text))
    lunar_day = lunar_month = lunar_year = None
    lunar_leap = False

    if is_lunar:
        lunar_parsed = parse_lunar_reminder(text)
        if not lunar_parsed:
            await update.message.reply_text(
                "❌ Em chưa hiểu ngày âm lịch anh nhập ạ!\n"
                "Thử dạng: <code>Giỗ ông nội lúc 8h ngày 15/3 âm lịch</code>\n"
                "hoặc: <code>Rằm tháng Giêng 9h Cúng nhà âm lịch hàng năm</code>\n\n"
                "💡 Gửi <code>h</code> để xem hướng dẫn cú pháp chi tiết.",
                parse_mode="HTML"
            )
            return
        message, remind_time, repeat_type, lunar_day, lunar_month, lunar_year, lunar_leap = lunar_parsed
    else:
        parsed = parse_message(text)
        print("PARSED:", parsed, flush=True)
        if not parsed:
            await update.message.reply_text(
                "❌ Em chưa hiểu ý anh, anh có thể nói rõ hơn được không ạ?\n"
                "Ví dụ: <code>Họp với team lúc 3h chiều hàng ngày</code>\n\n"
                "💡 Gửi <code>h</code> để xem hướng dẫn cú pháp chi tiết.",
                parse_mode="HTML"
            )
            return
        message, remind_time, repeat_type = parsed

    text_repeat = format_repeat_type(repeat_type) if repeat_type != "none" else ""

    wd = weekday_vi(remind_time)
    solar_str = f"{wd}, {remind_time.strftime('%d-%m-%Y %H:%M')}"
    if is_lunar and lunar_day:
        lunar_label = f"tháng {lunar_month}" + (" nhuận" if lunar_leap else "")
        lunar_str = f"ngày {lunar_day} {lunar_label} năm {lunar_year} âm lịch"
        time_display = f"{solar_str} dương lịch, tức {lunar_str}"
    else:
        time_display = solar_str

    text_reply = (
        f"✅ <b>Dạ em đã thêm vào lịch của anh</b>\n"
        f"🕒 <b>Thời gian:</b> <i>{time_display}</i>\n"
        f"📌 <b>Nội dung:</b> <i>{message}</i>\n"
    )
    if repeat_type != "none":
        text_reply += f"🔁 <b>Tần suất:</b> {text_repeat}"

    cursor.execute(
        "SELECT id FROM reminders WHERE user_id=%s AND message=%s AND remind_at=%s AND is_active=TRUE ORDER BY remind_at DESC",
        (user_id, message, remind_time),
    )

    if cursor.fetchone():
        await update.message.reply_text("⚠️ Dạ, lịch này trước đó em đã note rồi ạ!")
        return

    cursor.execute(
        "INSERT INTO reminders (user_id, message, remind_at, repeat_type, is_lunar, lunar_day, lunar_month, lunar_year, lunar_leap)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (user_id, message, remind_time, repeat_type,
         is_lunar, lunar_day, lunar_month, lunar_year, lunar_leap),
    )
    db.commit()

    print(f"ADD: {message} at {remind_time} (lunar={is_lunar})", flush=True)

    await update.message.reply_text(text_reply, parse_mode="HTML")

# =========================
# COMMANDS
# =========================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_help(update)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_help(update)


async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await add_reminder(update, context)

async def delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ /delete ID")
        return

    rid = context.args[0]

    try:
        ensure_connection()
    except Exception as e:
        print("DB RECONNECT ERROR:", e, flush=True)
        await update.message.reply_text("❌ Lỗi kết nối database, vui lòng thử lại sau.")
        return

    cursor.execute(
        "UPDATE reminders SET is_active=FALSE WHERE id=%s AND user_id=%s",
        (rid, update.effective_user.id),
    )
    db.commit()

    await update.message.reply_text("🗑️ Đã xoá")

# =========================
# WORKER
# =========================
async def worker(app):
    while True:
        now = datetime.now()

        try:
            ensure_connection()
        except Exception as e:
            print("DB RECONNECT ERROR:", e, flush=True)
            await asyncio.sleep(30)
            continue

        cursor.execute(
            "SELECT * FROM reminders WHERE remind_at<=%s AND is_active=TRUE",
            (now,),
        )

        rows = cursor.fetchall()

        # Nhắc trước 1 ngày cho monthly/yearly (chỉ check 1 lần mỗi phút)
        if now.second < 10:
            pre_window_start = now.replace(second=0, microsecond=0) - timedelta(seconds=1)
            pre_window_end   = now.replace(second=0, microsecond=0) + timedelta(seconds=1)
            cursor.execute(
                """
                SELECT * FROM reminders
                WHERE (repeat_type IN ('monthly', 'yearly')
                       OR repeat_type LIKE 'every_%m'
                       OR repeat_type LIKE 'every_%y')
                  AND is_active = TRUE
                  AND DATE_SUB(remind_at, INTERVAL 1 DAY) > %s
                  AND DATE_SUB(remind_at, INTERVAL 1 DAY) <= %s
                """,
                (pre_window_start, pre_window_end),
            )
            pre_rows = cursor.fetchall()
            for r in pre_rows:
                try:
                    remind_date = r["remind_at"].strftime("%d-%m-%Y %H:%M")
                    await app.bot.send_message(
                        chat_id=r["user_id"],
                        text=f"🔔 <b>Nhắc trước 1 ngày</b>\n📌 {r['message']}\n⏰ {remind_date}",
                        parse_mode="HTML",
                    )
                except Exception as e:
                    print("PRE-REMIND ERROR:", e, flush=True)

        for r in rows:
            try:
                await app.bot.send_message(
                    chat_id=r["user_id"],
                    text=f"⏰ {r['message']}\n\n<i>ID: {r['id']}</i>",
                    parse_mode="HTML",
                )

                if r["repeat_type"] == "daily":
                    next_time = r["remind_at"] + timedelta(days=1)
                    next_lunar_update = {}
                elif r["repeat_type"] == "weekly":
                    next_time = r["remind_at"] + timedelta(days=7)
                    next_lunar_update = {}
                elif r["repeat_type"] == "monthly":
                    if r.get("is_lunar") and r.get("lunar_day"):
                        lm = r["lunar_month"] % 12 + 1
                        ly = r["lunar_year"] + (1 if r["lunar_month"] == 12 else 0)
                        sol_d, sol_m, sol_y = lunar_to_solar(r["lunar_day"], lm, ly, bool(r.get("lunar_leap")))
                        if sol_d > 0:
                            next_time = r["remind_at"].replace(year=sol_y, month=sol_m, day=sol_d)
                            next_lunar_update = {"lunar_month": lm, "lunar_year": ly}
                        else:
                            next_time = r["remind_at"] + relativedelta(months=1)
                            next_lunar_update = {}
                    else:
                        next_time = r["remind_at"] + relativedelta(months=1)
                        next_lunar_update = {}
                elif r["repeat_type"] == "yearly":
                    if r.get("is_lunar") and r.get("lunar_day"):
                        ly = r["lunar_year"] + 1
                        sol_d, sol_m, sol_y = lunar_to_solar(r["lunar_day"], r["lunar_month"], ly, bool(r.get("lunar_leap")))
                        if sol_d > 0:
                            next_time = r["remind_at"].replace(year=sol_y, month=sol_m, day=sol_d)
                            next_lunar_update = {"lunar_year": ly}
                        else:
                            next_time = r["remind_at"] + relativedelta(years=1)
                            next_lunar_update = {}
                    else:
                        next_time = r["remind_at"] + relativedelta(years=1)
                        next_lunar_update = {}
                elif r["repeat_type"] and r["repeat_type"].startswith("every_"):
                    _cm = re.fullmatch(r"every_(\d+)([dwmy])", r["repeat_type"])
                    if _cm:
                        _n, _u = int(_cm.group(1)), _cm.group(2)
                        if _u == "d":
                            next_time = r["remind_at"] + timedelta(days=_n)
                            next_lunar_update = {}
                        elif _u == "w":
                            next_time = r["remind_at"] + timedelta(weeks=_n)
                            next_lunar_update = {}
                        elif _u == "m":
                            if r.get("is_lunar") and r.get("lunar_day"):
                                _total = r["lunar_month"] + _n
                                _new_ly = r["lunar_year"] + (_total - 1) // 12
                                _new_lm = (_total - 1) % 12 + 1
                                sol_d, sol_m, sol_y = lunar_to_solar(r["lunar_day"], _new_lm, _new_ly, bool(r.get("lunar_leap")))
                                if sol_d > 0:
                                    next_time = r["remind_at"].replace(year=sol_y, month=sol_m, day=sol_d)
                                    next_lunar_update = {"lunar_month": _new_lm, "lunar_year": _new_ly}
                                else:
                                    next_time = r["remind_at"] + relativedelta(months=_n)
                                    next_lunar_update = {}
                            else:
                                next_time = r["remind_at"] + relativedelta(months=_n)
                                next_lunar_update = {}
                        elif _u == "y":
                            if r.get("is_lunar") and r.get("lunar_day"):
                                _new_ly = r["lunar_year"] + _n
                                sol_d, sol_m, sol_y = lunar_to_solar(r["lunar_day"], r["lunar_month"], _new_ly, bool(r.get("lunar_leap")))
                                if sol_d > 0:
                                    next_time = r["remind_at"].replace(year=sol_y, month=sol_m, day=sol_d)
                                    next_lunar_update = {"lunar_year": _new_ly}
                                else:
                                    next_time = r["remind_at"] + relativedelta(years=_n)
                                    next_lunar_update = {}
                            else:
                                next_time = r["remind_at"] + relativedelta(years=_n)
                                next_lunar_update = {}
                        else:
                            next_time = None
                            next_lunar_update = {}
                    else:
                        next_time = None
                        next_lunar_update = {}
                else:
                    next_time = None
                    next_lunar_update = {}

                if next_time:
                    if next_lunar_update:
                        if "lunar_month" in next_lunar_update and "lunar_year" in next_lunar_update:
                            cursor.execute(
                                "UPDATE reminders SET lunar_month=%s, lunar_year=%s, remind_at=%s WHERE id=%s",
                                (next_lunar_update["lunar_month"], next_lunar_update["lunar_year"], next_time, r["id"]),
                            )
                        elif "lunar_year" in next_lunar_update:
                            cursor.execute(
                                "UPDATE reminders SET lunar_year=%s, remind_at=%s WHERE id=%s",
                                (next_lunar_update["lunar_year"], next_time, r["id"]),
                            )
                    else:
                        cursor.execute(
                            "UPDATE reminders SET remind_at=%s WHERE id=%s",
                            (next_time, r["id"]),
                        )
                else:
                    cursor.execute(
                        "UPDATE reminders SET is_active=FALSE WHERE id=%s",
                        (r["id"],),
                    )

                db.commit()

            except Exception as e:
                print("SEND ERROR:", e, flush=True)

        await asyncio.sleep(10)


def parse_time_information(value):
    if not value:
        return None

    try:
        return datetime.strptime(value.strip(), "%H:%M").time()
    except ValueError as exc:
        raise ValueError("TIME_INFORMATION must use HH:MM format, for example 21:00") from exc


async def weather_information_worker(app):
    try:
        target_time = parse_time_information(TIME_INFORMATION)
    except ValueError as exc:
        print(f"WEATHER INFO DISABLED: {exc}", flush=True)
        return

    if not target_time:
        print("WEATHER INFO DISABLED: Missing TIME_INFORMATION in .env", flush=True)
        return

    sent_date = None

    while True:
        now = datetime.now(WEATHER_INFORMATION_TIMEZONE)

        if (
            now.hour == target_time.hour
            and now.minute == target_time.minute
            and sent_date != now.date()
        ):
            try:
                cursor.execute("SELECT DISTINCT user_id FROM reminders WHERE user_id IS NOT NULL")
                users = cursor.fetchall()

                if users:
                    weather_7am_text = await asyncio.to_thread(format_tomorrow_7am_forecast)
                    weather_day_text = await asyncio.to_thread(format_tomorrow_day_forecast)

                    for user in users:
                        try:
                            await app.bot.send_message(
                                chat_id=user["user_id"],
                                text=weather_7am_text,
                            )
                            await app.bot.send_message(
                                chat_id=user["user_id"],
                                text=weather_day_text,
                            )
                        except Exception as exc:
                            print(f"WEATHER INFO SEND ERROR user_id={user['user_id']}: {exc}", flush=True)

                sent_date = now.date()
            except Exception as exc:
                sent_date = now.date()
                print("WEATHER INFO ERROR:", exc, flush=True)

        await asyncio.sleep(30)


async def monthly_summary_worker(app):
    sent_month = None

    while True:
        now = datetime.now(WEATHER_INFORMATION_TIMEZONE)

        if now.day == 1 and now.hour == 9 and now.minute == 0 and sent_month != (now.year, now.month):
            try:
                ensure_connection()
                # Tìm các reminder trong tháng hiện tại
                month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                if now.month == 12:
                    month_end = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
                else:
                    month_end = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)

                cursor.execute("SELECT DISTINCT user_id FROM reminders WHERE is_active=TRUE")
                users = cursor.fetchall()

                for user in users:
                    uid = user["user_id"]
                    cursor.execute(
                        """
                        SELECT * FROM reminders
                        WHERE user_id = %s AND is_active = TRUE
                          AND remind_at >= %s AND remind_at < %s
                        ORDER BY remind_at ASC
                        """,
                        (uid, month_start, month_end),
                    )
                    rows = cursor.fetchall()
                    if not rows:
                        continue

                    month_name = now.strftime("%m/%Y")
                    msg = f"📅 <b>Lịch tháng {month_name}</b>\n\n"
                    for r in rows:
                        lunar_line = ""
                        if r.get("is_lunar") and r.get("lunar_day"):
                            lunar_label = f"tháng {r['lunar_month']}" + (" nhuận" if r.get("lunar_leap") else "")
                            lunar_line = f"\n🌙 Âm lịch: ngày {r['lunar_day']} {lunar_label} năm {r['lunar_year']} {r['remind_at'].strftime('%H:%M')}"
                        wd = weekday_vi(r["remind_at"])
                        msg += f"ID: {r['id']}\n"
                        msg += f"⏰ {wd}, {r['remind_at'].strftime('%d-%m-%Y %H:%M')}{lunar_line}\n"
                        msg += f"📌 {r['message']}\n"
                        msg += f"🔁 {format_repeat_type(r['repeat_type'])}\n\n"

                    try:
                        await app.bot.send_message(chat_id=uid, text=msg, parse_mode="HTML")
                    except Exception as e:
                        print(f"MONTHLY SUMMARY SEND ERROR uid={uid}: {e}", flush=True)

                sent_month = (now.year, now.month)
            except Exception as e:
                print(f"MONTHLY SUMMARY ERROR: {e}", flush=True)

        await asyncio.sleep(30)


def run():
    init()
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .get_updates_connect_timeout(30)
        .get_updates_read_timeout(60)
        .get_updates_write_timeout(60)
        .get_updates_pool_timeout(30)
        .build()
    )

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler(["list", "ls"], list_cmd))
    app.add_handler(CommandHandler(["delete", "del"], delete_cmd))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, add_reminder))
    # chạy worker nền
    async def start_worker(app):
        await app.bot.set_my_commands([
            ("start", "Hướng dẫn sử dụng"),
            ("help", "Hướng dẫn sử dụng"),
            ("list", "Xem danh sách reminder"),
            ("ls", "Xem nhanh reminder"),
            ("delete", "Xoá reminder theo ID"),
            ("del", "Xoá nhanh reminder theo ID"),
        ])
        asyncio.create_task(worker(app))
        asyncio.create_task(weather_information_worker(app))
        asyncio.create_task(monthly_summary_worker(app))

    app.post_init = start_worker

    print("🚀 Bot started...", flush=True)

    app.run_polling()
