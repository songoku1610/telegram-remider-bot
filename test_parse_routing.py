"""
Test end-to-end luồng add_reminder(): Rule -> Dictionary -> LLM -> Default.
Dùng DB giả và LLM giả, kiểm tra nhãn nguồn trong tin xác nhận và số lần gọi LLM.
Chạy: python test_parse_routing.py
"""
import asyncio
import io
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import telegrambot


class FakeCursor:
    def __init__(self, store):
        self.store = store

    def execute(self, sql, params=None):
        if sql.lstrip().upper().startswith("INSERT"):
            self.store.append(params)

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class FakeDb:
    def __init__(self):
        self.inserted = []

    def ping(self, **kwargs):
        pass

    def cursor(self, **kwargs):
        return FakeCursor(self.inserted)

    def commit(self):
        pass

    def rollback(self):
        pass


class FakeLLM:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    async def __call__(self, text, now):
        self.calls += 1
        return self.response


def _make_update(text):
    replies = []

    async def reply_text(msg, parse_mode=None):
        replies.append(msg)

    message = SimpleNamespace(
        text=text, forward_origin=None, api_kwargs={}, forward_from=None,
        forward_from_chat=None, forward_sender_name=None, forward_date=None,
        reply_text=reply_text,
    )
    update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=1))
    return update, replies


def run(text, llm_response=None):
    db = FakeDb()
    llm = FakeLLM(llm_response)
    telegrambot.db = db
    telegrambot.WEATHER_INFORMATION_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
    original_llm = telegrambot.parse_with_gemini
    telegrambot.parse_with_gemini = llm
    try:
        update, replies = _make_update(text)
        asyncio.run(telegrambot.add_reminder(update, None))
    finally:
        telegrambot.parse_with_gemini = original_llm
    return "\n".join(replies), llm.calls, db.inserted


def label(source):
    return telegrambot.format_parse_source(source)


ROUTING_CASES = [
    # (text, llm_response, nguồn kỳ vọng, số lần gọi LLM, số lịch được insert)

    # ----- toàn bộ ví dụ trong tin help: phải vẫn đi qua Rule -----
    # Rule không đọc được "3h chiều" (parse_time trả None, kể cả trước khi có Dictionary) → Dictionary bắt
    ("Họp với team lúc 3h chiều hàng ngày", None, "Dictionary", 0, 1),
    ("14.00 Họp giao ban", None, "Rule", 0, 1),
    ("Thứ 4, 14.00 Họp giao ban", None, "Rule", 0, 1),
    ("T4 14.00 Họp giao ban", None, "Rule", 0, 1),
    ("T4-14.00 Họp giao ban", None, "Rule", 0, 1),
    ("10h T3 Họp với đối tác", None, "Rule", 0, 1),
    ("T4, 14.00 A.XYZ họp rà soát Kế hoạch", None, "Rule", 0, 1),
    ("Làm dự toán vào 8h ngày 02/05/2027 hàng tháng", None, "Rule", 0, 1),
    ("Khám định kỳ lúc 9h ngày 15/07/2027 mỗi 6 tháng", None, "Rule", 0, 1),
    ("Uống thuốc lúc 8h hôm nay mỗi 3 ngày", None, "Rule", 0, 1),
    ("Gia hạn domain lúc 9h ngày 05/06/2027 mỗi 2 năm", None, "Rule", 0, 1),
    ("Họp lúc 9h T2, T4, T6 hàng tuần", None, "Rule", 0, 3),
    ("Họp lúc 9h T2, T4, T6", None, "Rule", 0, 3),
    ("Nộp BC lúc 17h ngày 5, 20 hàng tháng", None, "Rule", 0, 2),
    ("Nộp BC lúc 17h ngày 5, 20", None, "Rule", 0, 2),
    ("Kỷ niệm lúc 8h ngày 20/6, 25/7 hàng năm", None, "Rule", 0, 2),
    ("Kỷ niệm lúc 8h ngày 20/6, 25/7", None, "Rule", 0, 2),
    ("Giỗ ông nội lúc 8h ngày 15/3 âm lịch hàng năm", None, "Rule", 0, 1),
    ("Cúng rằm tháng 7 lúc 9h âm lịch hàng năm", None, "Rule", 0, 1),
    ("Mùng 1 tháng giêng 8h Chúc tết âm lịch", None, "Rule", 0, 1),
    ("Giỗ cụ lúc 8h ngày 10/2 âm lịch mỗi 1 năm", None, "Rule", 0, 1),
    ("14.00 Họp giao ban\nChuẩn bị số liệu ngày 20/11", None, "Rule", 0, 1),

    # ----- Rule từng bắt nhầm → giờ bị chặn, chuyển xuống Dictionary -----
    ("Họp thứ 4 lúc 9h", None, "Dictionary", 0, 1),
    ("họp tổng kết 20 tháng 12 năm 2026 lúc 14h", None, "Dictionary", 0, 1),
    ("15 phút nữa gọi lại khách", None, "Dictionary", 0, 1),
    ("2 giờ chiều mai đi khám", None, "Dictionary", 0, 1),
    ("10 người đi ăn tối mai", None, "Dictionary", 0, 1),
    ("họp mỗi thứ 2 lúc 8h", None, "Dictionary", 0, 1),
    ("Backup dữ liệu 3 ngày 1 lần lúc 23h", None, "Dictionary", 0, 1),
    ("Tập gym t2 t4 t6 lúc 18h", None, "Dictionary", 0, 3),
    ("trực ca 20/11, 25/11 và 30/11 lúc 7h", None, "Dictionary", 0, 3),
    ("Họp với chị Mai lúc 9h", None, "Rule", 0, 1),

    ("Họp giao ban lúc 9h mai", None, "Rule", 0, 1),
    ("Tập gym lúc 18h T2,T4,T6", None, "Rule", 0, 3),
    ("Giỗ ông nội lúc 8h ngày 15/3 âm lịch", None, "Rule", 0, 1),
    ("mai 9h họp", None, "Dictionary", 0, 1),
    ("Họp chiều mai 3h", None, "Dictionary", 0, 1),
    ("gọi điện cho mẹ 30p nữa", None, "Dictionary", 0, 1),
    ("Sinh nhật vợ 20/12", None, "Dictionary", 0, 1),
    ("Trung thu mua bánh", None, "Dictionary", 0, 1),
    ("học tiếng anh thứ ba và thứ năm 20h", None, "Dictionary", 0, 2),
    ("đi chơi cuối tuần này", None, "Dictionary", 0, 1),
    (
        "Thông báo: tuần này có buổi giao ban tại phòng họp lớn, mọi người chuẩn bị nhé",
        {"is_reminder": True, "reminders": [{
            "clean_message": "Giao ban", "standard_syntax": "Giao ban lúc 09:00 ngày 20/11/2026",
            "has_explicit_time": False, "is_meeting": False, "suggested_slot": "morning_9h",
            "repeat_type": "none", "is_lunar": False}], "reply_text": None},
        "LLM", 1, 1,
    ),
    (
        "Sinh nhật: Nguyễn A mùng 3 tháng 2, Trần B ngày 15 tháng 7",
        {"is_reminder": True, "reminders": [
            {"clean_message": "Sinh nhật Nguyễn A", "standard_syntax": "Sinh nhật Nguyễn A lúc 09:00 ngày 03/02/2027 hàng năm",
             "has_explicit_time": False, "is_meeting": False, "repeat_type": "yearly", "is_lunar": False},
            {"clean_message": "Sinh nhật Trần B", "standard_syntax": "Sinh nhật Trần B lúc 09:00 ngày 15/07/2027 hàng năm",
             "has_explicit_time": False, "is_meeting": False, "repeat_type": "yearly", "is_lunar": False},
        ], "reply_text": None},
        "LLM", 1, 2,
    ),
    ("viết tài liệu kiến trúc hệ thống", None, "Default", 1, 1),
    ("hôm nay trời đẹp quá", {"is_reminder": False, "reminders": [], "reply_text": "Dạ đúng rồi ạ!"}, None, 1, 0),
    (
        "Lịch họp tuần:\n- T2 9h họp giao ban\n- T4 14h họp dự án\n- T6 10h review",
        {"is_reminder": True, "reminders": [
            {"clean_message": "Họp giao ban", "standard_syntax": "Họp giao ban lúc 09:00 ngày 23/11/2026",
             "has_explicit_time": True, "is_meeting": True, "repeat_type": "none", "is_lunar": False},
            {"clean_message": "Họp dự án", "standard_syntax": "Họp dự án lúc 14:00 ngày 25/11/2026",
             "has_explicit_time": True, "is_meeting": True, "repeat_type": "none", "is_lunar": False},
            {"clean_message": "Review", "standard_syntax": "Review lúc 10:00 ngày 27/11/2026",
             "has_explicit_time": True, "is_meeting": True, "repeat_type": "none", "is_lunar": False},
        ], "reply_text": None},
        "LLM", 1, 9,  # 3 cuộc họp x (lịch chính + nhắc trước 15p + 5p)
    ),
]


def test_routing():
    failures = []
    for text, llm_response, source, llm_calls, n_insert in ROUTING_CASES:
        reply, calls, inserted = run(text, llm_response)
        problems = []
        if source and label(source) not in reply:
            problems.append(f"thiếu nhãn {source}")
        if source is None and "Nhận diện bởi" in reply:
            problems.append("không phải lịch nhưng vẫn có nhãn")
        if calls != llm_calls:
            problems.append(f"gọi LLM {calls} lần (kỳ vọng {llm_calls})")
        if len(inserted) != n_insert:
            problems.append(f"insert {len(inserted)} lịch (kỳ vọng {n_insert})")
        if problems:
            failures.append(text)
            print(f"❌ {text[:60]!r}: {', '.join(problems)}\n   reply: {reply!r}")
        else:
            print(f"✅ {text[:60]!r} -> {source or 'không tạo lịch'} (LLM={calls}, insert={len(inserted)})")
    assert not failures, f"{len(failures)} case sai"


if __name__ == "__main__":
    test_routing()
    print("\n🎉 Luồng Rule -> Dictionary -> LLM -> Default đúng")
