import os
import json
import logging
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List
import httpx
from lunarcalendar import solar_to_lunar

logger = logging.getLogger(__name__)

# Cấu hình mặc định Google Gemini
DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"
DEFAULT_GEMINI_FALLBACKS = [
    "gemini-3.6-flash",
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
]

# Cấu hình mặc định OpenRouter (Dự phòng xuyên nhà cung cấp)
DEFAULT_OPENROUTER_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen-2.5-72b-instruct:free",
]

DEFAULT_TIMEOUT = 8.0
DEFAULT_MORNING_HOUR = "09:00"
DEFAULT_AFTERNOON_HOUR = "16:00"

WEEKDAY_VI = {
    0: "Thứ Hai",
    1: "Thứ Ba",
    2: "Thứ Tư",
    3: "Thứ Năm",
    4: "Thứ Sáu",
    5: "Thứ Bảy",
    6: "Chủ Nhật",
}


def safe_print(msg: str):
    """In log an toàn, tự động fallback nếu console không hỗ trợ emoji/unicode charmap."""
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        try:
            print(msg.encode("ascii", errors="replace").decode("ascii"), flush=True)
        except Exception:
            pass


def _get_gemini_api_key() -> Optional[str]:
    """Lấy API Key từ GEMINI_API_KEY hoặc GOOGLE_API_KEY."""
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def _get_openrouter_api_key() -> Optional[str]:
    """Lấy API Key OpenRouter từ OPENROUTER_API_KEY."""
    return os.getenv("OPENROUTER_API_KEY")


def _get_gemini_candidate_models() -> List[str]:
    """Trả về danh sách model Gemini kèm fallback."""
    primary = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip()
    custom_fallbacks = os.getenv("GEMINI_FALLBACK_MODELS", "").strip()

    models = [primary]
    if custom_fallbacks:
        fb_list = [m.strip() for m in custom_fallbacks.split(",") if m.strip()]
    else:
        fb_list = DEFAULT_GEMINI_FALLBACKS

    for fb in fb_list:
        if fb not in models:
            models.append(fb)
    return models


def _get_openrouter_candidate_models() -> List[str]:
    """Trả về danh sách model OpenRouter kèm fallback."""
    custom_models = os.getenv("OPENROUTER_MODELS", "").strip()
    if custom_models:
        return [m.strip() for m in custom_models.split(",") if m.strip()]
    return DEFAULT_OPENROUTER_MODELS


def _get_timeout() -> float:
    try:
        return float(os.getenv("GEMINI_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT)))
    except ValueError:
        return DEFAULT_TIMEOUT


def build_system_instruction(current_dt: datetime) -> str:
    """Tạo prompt hệ thống kèm ngữ cảnh thời gian hiện tại."""
    wd_str = WEEKDAY_VI.get(current_dt.weekday(), "")
    dt_str = current_dt.strftime("%Y-%m-%d %H:%M:%S")
    
    # Tính ngày âm lịch hiện tại
    try:
        ld, lm, ly, lleap = solar_to_lunar(current_dt.day, current_dt.month, current_dt.year)
        leap_str = " (nhuận)" if lleap else ""
        lunar_str = f"ngày {ld} tháng {lm}{leap_str} năm {ly} âm lịch"
    except Exception:
        lunar_str = "không xác định"

    instruction = f"""Bạn là trợ lý AI thông minh chuyên phân tích và chuẩn hóa tin nhắn nhắc lịch (Reminder) cho Telegram Bot tiếng Việt.

THỜI GIAN HIỆN TẠI HỆ THỐNG:
- Ngày giờ dương lịch: {dt_str} ({wd_str})
- Ngày âm lịch hiện tại: {lunar_str}

NHIỆM VỤ CỦA BẠN:
1. Phân loại tin nhắn (Intent):
   - Nếu là yêu cầu tạo nhắc lịch/hẹn giờ/ghi nhớ công việc, hoặc thông báo có chứa deadline, hạn chót, ngày hẹn, lịch họp, kế hoạch công việc: "is_reminder": true
   - Nếu là lời chào hỏi đơn thuần, hỏi thăm, trò chuyện không có công việc: "is_reminder": false

2. Xử lý nội dung (clean_message):
   - Trích xuất nội dung cốt lõi của công việc cần làm hoặc cuộc họp cần nhớ.
   - Lọc bỏ các từ râu ria, xưng hô không cần thiết như: "Kính nhờ các anh", "nhớ nhắc anh/em/tao", "ê bot", "giúp tao", "nhé", "nha".
   - Nếu tin nhắn có "Deadline : DD/MM/YYYY" hoặc "Hạn chót" hoặc "Để đầu tháng 10... họp": tóm tắt hành động cần làm. Viết hoa chữ cái đầu.

3. QUY TẮC SUY LUẬN THỜI GIAN & FALLBACK 9H SÁNG / 16H CHIỀU:
   a. Người dùng có nói giờ cụ thể (ví dụ 10h, 8h30 sáng, 4 rưỡi chiều):
      - Giữ nguyên giờ đó (chuyển sang định dạng HH:MM 24h).
      - "has_explicit_time": true
   b. Người dùng KHÔNG nói giờ cụ thể ("has_explicit_time": false):
      - Nếu là DEADLINE / HẠN CHÓT / BÁO CÁO / NỘP HỒ SƠ / BUỔI CHIỀU / CUỐI NGÀY:
        Mặc định chọn 16:00 chiều (hạn kết thúc ngày làm việc).
      - Nếu là CUỘC HỌP / KẾ HOẠCH ĐẦU NGÀY / ĐẦU THÁNG / NGÀY MAI / NGÀY TƯƠNG LAI CHUNG CHUNG:
        Mặc định chọn 09:00 sáng.
      - "Đầu tháng X/YYYY": tính là ngày 01 của tháng X/YYYY lúc 09:00 sáng.
      - Nếu là việc trong ngày hôm nay:
        + Nếu hiện tại trước 09:00: chọn 09:00 hôm nay.
        + Nếu hiện tại từ 09:00 đến trước 16:00: chọn 16:00 hôm nay.
        + Nếu hiện tại từ 16:00 trở đi: nếu có chữ "tối nay" chọn 20:00; nếu không thì chuyển sang 09:00 sáng ngày hôm sau.
      - Nếu là ngày âm lịch (giỗ, rằm, mùng 1) mà không có giờ: mặc định chọn 09:00 sáng.

4. CHUYỂN ĐỔI NGƯỢC THÀNH CÚ PHÁP CHUẨN CỦA BOT ("standard_syntax"):
   Bot hỗ trợ các cú pháp chuẩn sau:
   - Dương lịch 1 lần: "<Nội dung> lúc <HH:MM> ngày <DD/MM/YYYY>"
   - Dương lịch lặp lại:
     + Hàng ngày: "<Nội dung> lúc <HH:MM> hàng ngày"
     + Ngày thường (T2-T6): "<Nội dung> lúc <HH:MM> ngày thường"
     + Cuối tuần (T7-CN): "<Nội dung> lúc <HH:MM> cuối tuần"
     + Hàng tuần vào thứ cụ thể: "<Nội dung> lúc <HH:MM> T2 hàng tuần" (hoặc T3, T4, T5, T6, T7, CN)
     + Hàng tháng: "<Nội dung> lúc <HH:MM> ngày <DD/MM/YYYY> hàng tháng"
     + Hàng năm: "<Nội dung> lúc <HH:MM> ngày <DD/MM/YYYY> hàng năm"
     + Tuỳ ý: "<Nội dung> lúc <HH:MM> ngày <DD/MM/YYYY> mỗi <N> ngày/tuần/tháng/năm"
   - Âm lịch: "<Nội dung> lúc <HH:MM> ngày <DD/MM> âm lịch [hàng năm / hàng tháng nếu lặp]"

YÊU CẦU ĐỊNH DẠNG ĐẦU RA:
Bắt buộc trả về đúng định dạng JSON thuần tuý (JSON object), không thêm markdown block ```json hay bất kỳ chữ nào khác ngoài JSON:
{{
  "is_reminder": true hoặc false,
  "clean_message": "Nội dung việc cần làm",
  "standard_syntax": "Chuỗi cú pháp chuẩn để nạp vào bot",
  "has_explicit_time": true hoặc false,
  "suggested_slot": "morning_9h" | "afternoon_16h" | "exact" | "other",
  "repeat_type": "none" | "daily" | "weekly" | "monthly" | "yearly" | "weekday" | "weekend",
  "is_lunar": true hoặc false,
  "reply_text": "Câu trả lời thân thiện nếu is_reminder là false, ngược lại để null"
}}
"""
    return instruction


def _clean_json_response(raw_text: str) -> str:
    """Loại bỏ markdown codeblock nếu LLM vô tình bọc vào."""
    raw_text = raw_text.strip()
    if raw_text.startswith("```json"):
        raw_text = raw_text[7:]
    elif raw_text.startswith("```"):
        raw_text = raw_text[3:]
    if raw_text.endswith("```"):
        raw_text = raw_text[:-3]
    return raw_text.strip()


async def _call_gemini_api(client: httpx.AsyncClient, model: str, api_key: str, text: str, system_prompt: str, timeout_sec: float) -> Optional[Dict[str, Any]]:
    """Gọi Google Gemini API (v1beta)."""
    model_path = model if model.startswith("models/") else f"models/{model}"
    url = f"https://generativelanguage.googleapis.com/v1beta/{model_path}:generateContent?key={api_key}"

    payload = {
        "system_instruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": text}]
            }
        ],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.1,
        }
    }
    headers = {"Content-Type": "application/json"}

    for attempt in range(2):
        try:
            if attempt == 0:
                safe_print(f"🤖 [GEMINI REQUEST] Model: {model}")
                safe_print(f"   📥 Nội dung gửi: '{text}'")
            else:
                safe_print(f"🔄 [GEMINI RETRY] Thử lại model {model} (lần 2)...")

            response = await client.post(url, json=payload, headers=headers)

            if response.status_code in [503, 429]:
                if attempt == 0:
                    safe_print(f"⚠️ [GEMINI 503/429] Model {model} quá tải ({response.status_code}), đợi 1.5s rồi thử lại...")
                    await asyncio.sleep(1.5)
                    continue
                else:
                    safe_print(f"⚠️ [GEMINI FAIL] Model {model} vẫn quá tải sau retry.")
                    return None

            if response.status_code != 200:
                safe_print(f"❌ [GEMINI ERROR] Model {model} lỗi HTTP {response.status_code}: {response.text}")
                return None

            data = response.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return None

            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts:
                return None

            clean_json = _clean_json_response(parts[0].get("text", ""))
            safe_print(f"✅ [GEMINI RESPONSE] Model: {model}")
            safe_print(f"   📤 Phản hồi: {clean_json}")

            return json.loads(clean_json)

        except httpx.TimeoutException:
            safe_print(f"⏱️ [GEMINI TIMEOUT] Model {model} quá thời gian chờ sau {timeout_sec}s.")
            return None
        except Exception as exc:
            safe_print(f"❌ [GEMINI EXCEPTION] Model {model}: {exc}")
            return None

    return None


async def _call_openrouter_api(client: httpx.AsyncClient, model: str, api_key: str, text: str, system_prompt: str, timeout_sec: float) -> Optional[Dict[str, Any]]:
    """Gọi OpenRouter API (Dự phòng xuyên nhà cung cấp với Llama / Qwen)."""
    url = "https://openrouter.ai/api/v1/chat/completions"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/songoku1610/telegram-remider-bot",
        "X-Title": "Telegram Reminder Bot",
    }

    try:
        safe_print(f"🌐 [OPENROUTER REQUEST] Model: {model}")
        safe_print(f"   📥 Nội dung gửi: '{text}'")

        response = await client.post(url, json=payload, headers=headers)

        if response.status_code != 200:
            safe_print(f"❌ [OPENROUTER ERROR] Model {model} lỗi HTTP {response.status_code}: {response.text}")
            return None

        data = response.json()
        choices = data.get("choices", [])
        if not choices:
            return None

        raw_content = choices[0].get("message", {}).get("content", "")
        clean_json = _clean_json_response(raw_content)

        safe_print(f"✅ [OPENROUTER RESPONSE] Model: {model}")
        safe_print(f"   📤 Phản hồi: {clean_json}")

        return json.loads(clean_json)

    except httpx.TimeoutException:
        safe_print(f"⏱️ [OPENROUTER TIMEOUT] Model {model} quá thời gian chờ sau {timeout_sec}s.")
        return None
    except Exception as exc:
        safe_print(f"❌ [OPENROUTER EXCEPTION] Model {model}: {exc}")
        return None


async def parse_with_gemini(text: str, current_dt: datetime) -> Optional[Dict[str, Any]]:
    """
    Gửi tin nhắn tự nhiên tới LLM để phân tích và chuẩn hoá cú pháp.
    Luồng đa tầng:
    1. Thử lần lượt các model của Google Gemini (ưu tiên gemini-3.6-flash).
    2. Nếu toàn bộ Gemini lỗi/quá tải -> Tự động chuyển sang OpenRouter (Llama 3.3, Qwen 2.5).
    """
    gemini_key = _get_gemini_api_key()
    openrouter_key = _get_openrouter_api_key()

    if not gemini_key and not openrouter_key:
        logger.warning("Chưa cấu hình GEMINI_API_KEY hoặc OPENROUTER_API_KEY. Bỏ qua phân tích LLM.")
        return None

    timeout_sec = _get_timeout()
    system_prompt = build_system_instruction(current_dt)

    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        # Tầng 1: Thử các model Google Gemini
        if gemini_key:
            gemini_models = _get_gemini_candidate_models()
            for model in gemini_models:
                result = await _call_gemini_api(client, model, gemini_key, text, system_prompt, timeout_sec)
                if result:
                    return result

        # Tầng 2: Fallback sang OpenRouter (Llama 3.3 70B / Qwen 2.5 72B free) nếu Gemini sập
        if openrouter_key:
            safe_print("🛡️ [MULTI-PROVIDER FALLBACK] Toàn bộ cụm Google Gemini lỗi, kích hoạt dự phòng OpenRouter...")
            openrouter_models = _get_openrouter_candidate_models()
            for model in openrouter_models:
                result = await _call_openrouter_api(client, model, openrouter_key, text, system_prompt, timeout_sec)
                if result:
                    return result

    return None

