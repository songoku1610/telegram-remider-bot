import sys
import io
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import telegrambot
from telegrambot import (
    parse_message,
    parse_lunar_reminder,
    LUNAR_KEYWORDS_RE,
    format_reminder_listing,
    build_llm_meeting_reminders,
)
from llm_service import build_system_instruction

def test_syntax_compatibility():
    print("=== TEST CÚ PHÁP ĐƯỢC CHUẨN HOÁ BỞI LLM ===")
    
    test_cases = [
        # (Standard syntax được LLM sinh ra, Kỳ vọng parse được)
        ("Đi gặp đối tác lúc 10:00 ngày 29/09/2026", True, False),
        ("Nộp báo cáo tài chính lúc 16:00 ngày 02/10/2026", True, False),
        ("Uống thuốc dị ứng lúc 09:00 ngày 29/09/2026", True, False),
        ("Tập thể dục lúc 06:30 hàng ngày", True, False),
        ("Họp ban quản trị lúc 09:00 T2 hàng tuần", True, False),
        ("Cúng rằm lúc 09:00 ngày 15/08 âm lịch", True, True),
        ("Giỗ ông nội lúc 08:30 ngày 15/03 âm lịch hàng năm", True, True),
    ]

    for std_text, expected_success, is_lunar_expected in test_cases:
        is_lunar = bool(LUNAR_KEYWORDS_RE.search(std_text))
        assert is_lunar == is_lunar_expected, f"Lỗi nhận diện âm lịch cho: {std_text}"

        if is_lunar:
            res = parse_lunar_reminder(std_text)
            print(f"✅ Âm lịch: '{std_text}' -> Parsed: {bool(res)} ({res[0] if res else 'FAIL'})")
            assert res is not None, f"Parse thất bại: {std_text}"
        else:
            res = parse_message(std_text)
            print(f"✅ Dương lịch: '{std_text}' -> Parsed: {bool(res)} ({res[0] if res else 'FAIL'})")
            assert res is not None, f"Parse thất bại: {std_text}"

    print("\n🎉 Toàn bộ cú pháp LLM chuẩn hóa đều tương thích 100% với Parser hiện tại!\n")


def test_system_prompt():
    print("=== TEST PROMPT GENERATION ===")
    tz = ZoneInfo("Asia/Ho_Chi_Minh")
    now = datetime(2026, 9, 28, 11, 45, 0, tzinfo=tz)
    prompt = build_system_instruction(now)
    assert "2026-09-28 11:45:00" in prompt
    assert "Thứ Hai" in prompt
    assert "âm lịch" in prompt
    assert '"is_meeting"' in prompt
    print("✅ Prompt generation inject ngữ cảnh thời gian thành công!")


def test_reminder_listing_groups_matching_content_and_repeat_type():
    reminders = [
        {"id": 563, "message": "go around and stretch", "repeat_type": "weekly", "remind_at": datetime(2026, 10, 1, 10, 0)},
        {"id": 567, "message": " GO around and stretch ", "repeat_type": "weekly", "remind_at": datetime(2026, 10, 1, 15, 0)},
        {"id": 598, "message": "go around and stretch", "repeat_type": "daily", "remind_at": datetime(2026, 10, 1, 11, 46)},
    ]

    listing = format_reminder_listing(reminders, "📅 Lịch tháng 10/2026")

    assert listing.count("📌") == 2
    assert "🔁 hàng tuần" in listing
    assert "🔁 hàng ngày" in listing
    assert "01-10-2026 10:00 — ID: 563" in listing
    assert "01-10-2026 15:00 — ID: 567" in listing
    assert "01-10-2026 11:46" in listing


def test_llm_meeting_creates_main_and_pre_reminders():
    meeting_time = datetime(2026, 10, 20, 10, 0)

    reminders = build_llm_meeting_reminders("Họp dự án", meeting_time, "weekly")

    assert reminders == [
        ("Họp dự án", datetime(2026, 10, 20, 10, 0), "weekly"),
        ("Nhắc trước 15 phút: Họp dự án", datetime(2026, 10, 20, 9, 45), "weekly"),
        ("Nhắc trước 5 phút: Họp dự án", datetime(2026, 10, 20, 9, 55), "weekly"),
    ]


def test_migration_uses_metadata_check_before_adding_columns():
    class FakeCursor:
        def __init__(self):
            self.columns = {"is_lunar", "lunar_day"}
            self.column_exists = False
            self.closed = False

        def execute(self, sql, params=None):
            if "information_schema.columns" in sql:
                self.column_exists = params[0] in self.columns
            elif "ALTER TABLE reminders ADD COLUMN" in sql:
                self.columns.add(sql.split("ADD COLUMN ", 1)[1].split()[0])

        def fetchone(self):
            return (1,) if self.column_exists else None

        def close(self):
            self.closed = True

    class FakeDb:
        def __init__(self):
            self.cursor_instance = FakeCursor()
            self.committed = False
            self.rolled_back = False

        def cursor(self):
            return self.cursor_instance

        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

    previous_db = telegrambot.db
    fake_db = FakeDb()
    telegrambot.db = fake_db
    try:
        telegrambot.migrate()
    finally:
        telegrambot.db = previous_db

    assert fake_db.committed is True
    assert fake_db.rolled_back is False
    assert fake_db.cursor_instance.closed is True
    assert fake_db.cursor_instance.columns == {
        "is_lunar", "lunar_day", "lunar_month", "lunar_year", "lunar_leap"
    }


if __name__ == "__main__":
    test_syntax_compatibility()
    test_system_prompt()
    test_reminder_listing_groups_matching_content_and_repeat_type()
    test_llm_meeting_creates_main_and_pre_reminders()
    test_migration_uses_metadata_check_before_adding_columns()
