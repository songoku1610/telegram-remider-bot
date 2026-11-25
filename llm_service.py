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
    "gemini-3.5-flash-lite",
    "gemini-3.8-flash",
    "gemini-flash-lite-latest",
]

# Cấu hình mặc định OpenRouter (Dự phòng xuyên nhà cung cấp)
DEFAULT_OPENROUTER_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen-2.5-72b-instruct:free",
]

DEFAULT_TIMEOUT = 15.0
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
    current_year = current_dt.year

    # Tính ngày âm lịch hiện tại
    try:
        ld, lm, ly, lleap = solar_to_lunar(current_dt.day, current_dt.month, current_dt.year)
        leap_str = " (nhuận)" if lleap else ""
        lunar_str = f"ngày {ld} tháng {lm}{leap_str} năm {ly} âm lịch"
    except Exception:
        lunar_str = "không xác định"

    instruction = f"""Bạn là trợ lý AI thông minh chuyên phân tích và chuẩn hóa tin nhắn nhắc lịch (Reminder) cho Telegram Bot tiếng Việt.

THỜI GIAN HIỆN TẠI HỆ THỐNG:
- Ngày giờ dương lịch: {dt_str} ({wd_str}) - Năm hiện tại: {current_year}
- Ngày âm lịch hiện tại: {lunar_str}

NHIỆM VỤ CỦA BẠN:
1. Phân loại tin nhắn (Intent):
   - Nếu là yêu cầu tạo nhắc lịch/hẹn giờ/ghi nhớ công việc, hoặc thông báo có chứa deadline, hạn chót, ngày hẹn, lịch họp, kế hoạch công việc, danh sách sinh nhật: "is_reminder": true
   - Nếu là lời chào hỏi đơn thuần, hỏi thăm, trò chuyện không có công việc: "is_reminder": false

2. XỬ LÝ ĐA LỊCH NHẮC (MULTI-REMINDERS / BATCH REMINDERS) - RẤT QUAN TRỌNG:
   - Nếu tin nhắn chứa NHIỀU công việc, nhiều sự kiện, hoặc danh sách nhiều người cần nhắc (ví dụ danh sách sinh nhật của nhiều nhân viên/bạn bè, lịch trình nhiều đầu việc):
     + BẠN PHẢI TÁCH THÀNH CÁC MỤC ĐỘC LẬP TRONG MẢNG "reminders".
     + Đảm bảo trích xuất ĐẦY ĐỦ TẤT CẢ các mục trong danh sách, TUYỆT ĐỐI KHÔNG BỎ SÓT bất kỳ ai hay bất kỳ công việc nào.
     + Với danh sách sinh nhật (ví dụ người dùng gửi bảng danh sách nhân viên có STT, mã nhân viên, họ tên, ngày sinh):
       * "clean_message": "Sinh nhật <Họ và tên>" (Ví dụ: "Sinh nhật Nguyễn Thị Quỳnh"). Không cần đưa số điện thoại, mã nhân viên hay chức danh vào nội dung nhắc.
       * Lấy ngày và tháng sinh (DD/MM) từ ngày sinh (bỏ qua năm sinh của người đó khi tính chu kỳ).
       * Tần suất "repeat_type": "yearly" (hàng năm).
       * Giờ nhắc: nếu không nói giờ cụ thể, mặc định 09:00 sáng.
       * Tính năm nhắc kế tiếp:
         - So sánh ngày sinh (DD/MM) với thời gian hiện tại ({dt_str}):
         - Nếu ngày DD/MM trong năm nay {current_year} chưa tới (>= ngày hiện tại): đặt mốc là DD/MM/{current_year}.
         - Nếu ngày DD/MM trong năm nay {current_year} đã trôi qua (< ngày hiện tại): đặt mốc là DD/MM/{current_year + 1}.
       * "standard_syntax": "Sinh nhật <Họ và tên> lúc 09:00 ngày <DD/MM/YYYY> hàng năm"
       * "is_meeting": false

     + Với danh sách lịch họp / nhiều cuộc họp trong tin nhắn (ví dụ lịch tuần, thông báo các cuộc họp trong ngày/tuần):
       * Tách riêng từng cuộc họp thành từng phần tử độc lập trong mảng "reminders".
       * "clean_message": Tóm tắt nội dung cuộc họp, kèm địa điểm hoặc hình thức họp nếu có (Ví dụ: "Họp giao ban tuần tại Phòng họp 1", "Họp dự án AI qua Zoom").
       * "is_meeting": true cho TẤT CẢ các mục cuộc họp này.
       * "has_explicit_time": true nếu có giờ họp cụ thể (ví dụ 8h30, 14h...). Nếu không nói giờ, mặc định 09:00 sáng.
       * "repeat_type": "none" nếu là cuộc họp cụ thể theo ngày; hoặc "weekly" nếu là lịch lặp hàng tuần (ví dụ "thứ 2 hàng tuần").
       * "standard_syntax": "<Nội dung họp> lúc <HH:MM> ngày <DD/MM/YYYY>" (hoặc "<Nội dung họp> lúc <HH:MM> T2 hàng tuần" nếu lặp).
   - Nếu tin nhắn chỉ có 1 lịch duy nhất:
     + Mảng "reminders" chỉ chứa 1 phần tử tương ứng.

3. Xử lý nội dung (clean_message):
   - Trích xuất nội dung cốt lõi của công việc cần làm hoặc cuộc họp cần nhớ.
   - Lọc bỏ các từ râu ria, xưng hô không cần thiết như: "Kính nhờ các anh", "nhớ nhắc anh/em/tao", "ê bot", "giúp tao", "nhé", "nha".
   - Nếu tin nhắn có "Deadline : DD/MM/YYYY" hoặc "Hạn chót" hoặc "Để đầu tháng 10... họp": tóm tắt hành động cần làm. Viết hoa chữ cái đầu.

4. Nhận diện cuộc họp (is_meeting):
   - "is_meeting": true chỉ khi nội dung là một cuộc họp/lịch gặp cần tham dự, ví dụ có "họp", "meeting", "lịch gặp đối tác".
   - Deadline, công việc cá nhân, sinh nhật, nhắc nộp báo cáo hoặc lời chào không phải cuộc họp thì "is_meeting": false.

5. QUY TẮC SUY LUẬN THỜI GIAN & FALLBACK 9H SÁNG / 16H CHIỀU:
   a. Người dùng có nói giờ cụ thể (ví dụ 10h, 8h30 sáng, 4 rưỡi chiều):
      - Giữ nguyên giờ đó (chuyển sang định dạng HH:MM 24h).
      - Giờ 1 chữ số (1h–9h) KHÔNG kèm buổi (sáng/chiều/tối) và KHÔNG nói ngày khác hôm nay:
        nếu giờ sáng đó hôm nay đã qua nhưng giờ chiều/tối tương ứng (+12h) chưa tới → hiểu là giờ chiều/tối hôm nay.
        Ví dụ: hiện tại 16:31, "5h anh em lên phòng anh" → 17:00 hôm nay (KHÔNG phải 05:00 sáng mai).
        Riêng CUỘC HỌP chỉ áp dụng cho 1h–6h; họp 7h/8h/9h mà giờ sáng hôm nay đã qua → sáng hôm sau
        (không đặt họp tối muộn). Ví dụ: hiện tại 14:00, "8h họp giao ban" → 08:00 sáng mai.
      - "has_explicit_time": true
   b. Người dùng KHÔNG nói giờ cụ thể ("has_explicit_time": false):
      - MẶC ĐỊNH LUÔN LÀ 09:00 SÁNG của ngày được nhắc tới (kể cả deadline, báo cáo, nộp hồ sơ, email, họp, sinh nhật, ngày mai, ngày tương lai).
        KHÔNG tự chọn 16:00 chỉ vì nội dung là deadline/báo cáo.
      - Chỉ khi người dùng nói rõ buổi (sáng/trưa/chiều/tối/đêm, "cuối ngày", "cuối giờ chiều") mới dùng giờ của buổi đó (ví dụ chiều → 16:00, tối → 20:00).
      - "Đầu tháng X/YYYY": tính là ngày 01 của tháng X/YYYY lúc 09:00 sáng.
      - Nếu là việc trong ngày hôm nay:
        + Nếu hiện tại trước 09:00: chọn 09:00 hôm nay.
        + Nếu hiện tại từ 09:00 trở đi và người dùng GHI RÕ "hôm nay"/"tối nay": chọn 16:00 hôm nay (sau 16:00 thì 20:00; sau 20:00 thì 09:00 sáng hôm sau).
        + Nếu không ghi rõ ngày nào và đã qua 09:00: chọn 09:00 sáng ngày hôm sau.
      - Nếu là ngày âm lịch (giỗ, rằm, mùng 1) mà không có giờ: mặc định chọn 09:00 sáng.

6. CHUYỂN ĐỔI NGƯỢC THÀNH CÚ PHÁP CHUẨN CỦA BOT ("standard_syntax"):
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
  "reminders": [
    {{
      "clean_message": "Nội dung việc cần làm",
      "standard_syntax": "Chuỗi cú pháp chuẩn để nạp vào bot",
      "has_explicit_time": true hoặc false,
      "is_meeting": true hoặc false,
      "suggested_slot": "morning_9h" | "afternoon_16h" | "exact" | "other",
      "repeat_type": "none" | "daily" | "weekly" | "monthly" | "yearly" | "weekday" | "weekend",
      "is_lunar": true hoặc false
    }}
  ],
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


def _normalize_llm_result(data: Dict[str, Any]) -> Dict[str, Any]:
    """Chuẩn hóa kết quả từ LLM, đảm bảo luôn có mảng 'reminders' và các trường root tương thích ngược."""
    if not isinstance(data, dict):
        return data

    if data.get("is_reminder"):
        reminders = data.get("reminders")
        if not isinstance(reminders, list) or len(reminders) == 0:
            # Fallback nếu LLM trả về flat object dạng cũ
            item = {
                "clean_message": data.get("clean_message") or "",
                "standard_syntax": data.get("standard_syntax") or "",
                "has_explicit_time": bool(data.get("has_explicit_time")),
                "is_meeting": bool(data.get("is_meeting")),
                "suggested_slot": data.get("suggested_slot", "other"),
                "repeat_type": data.get("repeat_type", "none"),
                "is_lunar": bool(data.get("is_lunar")),
            }
            data["reminders"] = [item]
        else:
            # Làm sạch từng item trong reminders
            valid_items = []
            for item in reminders:
                if isinstance(item, dict) and (item.get("standard_syntax") or item.get("clean_message")):
                    valid_items.append({
                        "clean_message": item.get("clean_message") or "",
                        "standard_syntax": item.get("standard_syntax") or "",
                        "has_explicit_time": bool(item.get("has_explicit_time")),
                        "is_meeting": bool(item.get("is_meeting")),
                        "suggested_slot": item.get("suggested_slot", "other"),
                        "repeat_type": item.get("repeat_type", "none"),
                        "is_lunar": bool(item.get("is_lunar")),
                    })
            data["reminders"] = valid_items

        # Đảm bảo root có dữ liệu của item đầu tiên (để tương thích ngược)
        if data["reminders"]:
            first = data["reminders"][0]
            for field in ["clean_message", "standard_syntax", "has_explicit_time", "is_meeting", "suggested_slot", "repeat_type", "is_lunar"]:
                if field not in data or data[field] is None:
                    data[field] = first.get(field)

    return data


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
                safe_print(f"   📥 Nội dung gửi: '{text[:150]}...' (độ dài: {len(text)} ký tự)" if len(text) > 150 else f"   📥 Nội dung gửi: '{text}'")
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

            parsed = json.loads(clean_json)
            return _normalize_llm_result(parsed)

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

        parsed = json.loads(clean_json)
        return _normalize_llm_result(parsed)

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

