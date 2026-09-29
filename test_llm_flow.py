import sys
import io
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from telegrambot import parse_message, parse_lunar_reminder, LUNAR_KEYWORDS_RE
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
    print("✅ Prompt generation inject ngữ cảnh thời gian thành công!")


if __name__ == "__main__":
    test_syntax_compatibility()
    test_system_prompt()
