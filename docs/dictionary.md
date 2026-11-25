# Từ điển nhận diện thời gian (`dictionary.json`)

Tầng **Dictionary** nằm giữa Rule và LLM. Mục tiêu: hiểu phần lớn câu chat tự nhiên tiếng Việt mà **không gọi LLM**, nhưng thà bỏ qua (trả `None` để LLM xử lý) còn hơn đặt lịch sai.

- Dữ liệu: `dictionary.json` (sửa được, không cần sửa code cho phần lớn thay đổi).
- Code: `dictionary_parser.py`, hàm chính `parse_with_dictionary(text, now=None)`.
- Từ điển được nạp một lần và cache; **sửa `dictionary.json` xong phải khởi động lại bot** (`./install.sh` trên server).

---

## 1. Vai trò trong luồng

```
tin nhắn ─► Rule ──(không nhận / không tin cậy)──► Dictionary ──(None)──► LLM ──► Default
                                                     │
                                                     └─► cú pháp chuẩn ─► parse_message() của Rule ─► giờ nhắc
```

Dictionary **không tự quyết định giờ nhắc cuối cùng**. Nó chỉ dịch câu tự nhiên sang cú pháp chuẩn:

```
<nội dung> lúc HH:MM ngày DD/MM/YYYY [hàng ngày|hàng tuần|...]
<nội dung> lúc HH:MM ngày DD/MM âm lịch [hàng năm]
```

rồi `telegrambot.dictionary_items_via_rule()` đưa cú pháp đó cho `parse_message()` của Rule tính giờ. Nhờ vậy chỉ có một nơi tính thời gian. Nếu kết quả hai bên lệch nhau, log ghi `dictionary_rule_mismatch` (hoặc `dictionary_syntax_rule_failed` nếu Rule không parse được) và bot dùng kết quả của Rule. Theo dõi hai log này sau khi sửa từ điển.

Nội dung nhắc lưu vào DB là **nguyên văn tin gốc**, không phải phần nội dung đã cắt thời gian.

---

## 2. Kết quả trả về

`parse_with_dictionary()` trả `None` hoặc `DictionaryResult`:

| Trường | Ý nghĩa |
|---|---|
| `items` | Danh sách `(nội dung, datetime, repeat_type)`, đã sắp theo thời gian |
| `standard_syntax` | Cú pháp chuẩn của lịch đầu tiên |
| `syntaxes` | Cú pháp chuẩn của từng lịch (câu có nhiều ngày/thứ) |
| `is_lunar` | Lịch âm: `items` rỗng, chỉ có `standard_syntax` để `parse_lunar_reminder()` xử lý |
| `auto_time` | `True` nếu giờ do bot tự đặt (người dùng không ghi giờ) |

Các hàm phụ dùng ở `telegrambot.py`:

| Hàm | Dùng để |
|---|---|
| `contains_time_expression(text)` | Kiểm tra nội dung Rule trả về còn sót mốc thời gian không |
| `is_meeting_text(text)` | Câu có từ khoá họp không |
| `has_explicit_clock_time(text)` | Người dùng có ghi giờ cụ thể (8h, 14:30, 15 phút nữa) không |
| `shift_bare_hour_to_pm(text, remind_time, repeat_type)` | Áp quy tắc giờ trần 1 chữ số cho kết quả của Rule |
| `standard_syntax_for(msg, dt, rtype)` | Dựng cú pháp chuẩn |

---

## 3. Các bước xử lý

Theo `_meta.pipeline` trong file JSON:

1. **Chuẩn hoá**: NFKC, chữ thường, gộp khoảng trắng.
2. **phrases / holidays**: thay cụm cố định (cụm dài trước), vd "tết dương lịch" → "ngày 01/01".
3. **regex_rules** theo từng `stage`, đúng thứ tự:
   `weekday` → `number_words` → `relative` → `repeat` → `date` → `time`.
   - `repeat` chạy trước `date` để "3 ngày 1 lần" không bị hiểu thành "ngày 1".
   - `date` bị bỏ qua khi câu có "âm lịch"/"lịch âm".
   - Trong `time`, các rule thời lượng (`duration_h_m`, `duration_h`, `duration_h_half`) chạy **trước** `time_*`: "còn 2h", "mất 1h30", "kéo dài 2 tiếng rưỡi" được đổi thành "N tiếng" để không bị hiểu là giờ.
4. **computed_phrases**: "đầu tháng", "cuối tuần này", "ngày kia"...
5. **periods**: có giờ thì áp `hour_shift` (vd "3h chiều" → 15:00); không có giờ thì lấy `default_time` của buổi.
6. **default_time_by_keyword**: hiện để trống (`rules: []`), không ghi giờ thì mặc định 9h.
7. **Gom kết quả**: xoá các token thời gian, phần còn lại là nội dung.
8. **Giờ trần 1 chữ số**: `_bare_hour_pm()` (mục 5).

---

## 4. Các nhóm trong `dictionary.json`

| Khoá | Nội dung | Khi nào sửa |
|---|---|---|
| `number_words` | một, hai, ba... → 1, 2, 3 | Hiếm |
| `offset_words` | này / sau / tới... | Hiếm |
| `phrases` | Cụm cố định theo nhóm: `weekday`, `day_ref`, `period`, `relative_fixed`, `lunar_marker`, `repeat`... | Thêm cách nói mới, viết tắt, không dấu |
| `holidays` | Ngày lễ dương / âm | Thêm ngày lễ |
| `regex_rules` | ~40 regex, mỗi rule có `id`, `stage`, `pattern`, `replace` | Định dạng giờ/ngày mới |
| `computed_phrases` | Cụm cần tính toán (cuối tháng, ngày kia...) | Hiếm |
| `periods` | Buổi trong ngày: `words`, `default_time`, `hour_shift` | Đổi giờ mặc định của buổi |
| `default_time_by_keyword` | Giờ theo từ khoá (đang tắt) | Hiện không dùng |
| `bare_hour_pm` | Khoảng giờ được dời sang chiều: `hours`, `meeting_hours` | Đổi phạm vi giờ trần |
| `meeting_keywords` | Từ khoá cuộc họp | Thêm loại họp mới |
| `intent_keywords` | Từ khoá cho biết câu là việc cần nhắc (gửi, nộp, gọi, email, họp...) | Câu đúng là nhắc lịch nhưng bị rơi xuống LLM |
| `blockers` | `question_endings`, `question_phrases`, `past_markers`, `idioms` | Câu không phải nhắc lịch nhưng bị Dictionary bắt |
| `ambiguous` | Cụm mơ hồ, để LLM quyết | Hiếm |

### Điều kiện để Dictionary nhận câu

Dictionary trả `None` (xuống LLM) khi:

- không có mốc thời gian nào (giờ, ngày, thứ, hôm nay/mai, N phút nữa, lặp);
- không có từ khoá trong `intent_keywords`;
- dính `blockers`: câu hỏi ("mai họp không?", "mấy giờ"), chuyện đã qua, thành ngữ;
- có ≥ 2 giờ khác nhau, hoặc trộn nhiều ngày với nhiều thứ;
- câu dài > 300 ký tự hoặc > 3 dòng;
- còn sót cụm thời gian chưa hiểu được, hoặc nội dung còn lại rỗng.

### Lưu ý khi thêm từ khoá

- **Không thêm từ đơn quá chung** vào `intent_keywords`. Đã cố tình **không** thêm `báo`, `mail`, `zalo` vì gây nhận nhầm: "hôm nay mail nhiều quá", "zalo mai bị lỗi". Dùng cụm cụ thể: `gửi mail`, `check mail`, `báo cáo`, `báo giá`, `thông báo`.
- "Mai" vừa là "ngày mai" vừa là tên người. `_is_name_mai()` coi là tên khi đứng sau anh/chị/em/bạn/cô..., khi đứng trước "ơi" ("Mai ơi gửi file"), hoặc khi viết hoa "Mai" ở giữa câu ("họp với chị Mai", "gửi Mai file"). "Mai" viết hoa ở đầu câu vẫn là ngày mai.
- Regex dùng cú pháp Python `re`, nhớ escape `\\` trong JSON.

---

## 5. Quy tắc giờ

### Không ghi giờ (`_smart_default`)

| Trường hợp | Giờ |
|---|---|
| Ngày khác hôm nay | 09:00 ngày đó |
| Hôm nay, trước 9h | 09:00 hôm nay |
| Ghi rõ "hôm nay", sau 9h | 16:00; sau 16h → 20:00; sau 20h → 09:00 mai |
| Không ghi ngày, sau 9h | 09:00 mai |
| Thứ trùng hôm nay nhưng đã quá muộn | 09:00 thứ đó tuần sau |

### Giờ trần 1 chữ số (`bare_hour_pm`)

Câu chỉ có **một** giờ, ghi **1 chữ số** trong khoảng cấu hình, không kèm buổi, không chỉ ngày nào khác hôm nay, không lặp, không âm lịch. Nếu giờ sáng hôm nay đã qua mà giờ +12 chưa tới thì lấy giờ chiều hôm nay.

```json
"bare_hour_pm": { "hours": [1, 9], "meeting_hours": [1, 6] }
```

- `hours`: tin thường, "9h gọi mẹ" gửi lúc 14h → 21:00.
- `meeting_hours`: câu có từ khoá họp, "8h họp giao ban" gửi lúc 14h → 08:00 sáng mai, không đặt họp tối muộn.
- Giữ nguyên: "5h mai", "5h sáng", "05h", "10h", "5h thứ 6", "5h hàng ngày".
- Nếu Rule đã lệch giờ (cú pháp giờ đứng đầu trừ 15 phút), độ lệch được giữ khi dời giờ.

### Cuộc họp (`meeting_keywords`)

Có từ khoá họp, có giờ cụ thể, không lặp, không âm lịch → `telegrambot.py` tạo thêm nhắc trước 15 phút và trước 5 phút, bỏ qua mốc nào đã ở quá khứ. "họp mai" (không ghi giờ) chỉ tạo 1 lịch 09:00.

---

## 6. Quy trình sửa từ điển

1. Ghi câu thực tế bị sai và thời điểm gửi.
2. Thêm câu đó vào `test_dictionary_parser.py` (`CASES`, thời điểm cố định là thứ 4, 18/11/2026 10:00), với kết quả mong muốn hoặc `None` nếu muốn để LLM xử lý.
3. Sửa `dictionary.json`: thêm từ khoá, blocker, hoặc regex.
4. Chạy cả ba bộ test:
   ```bash
   python test_dictionary_parser.py
   python test_parse_routing.py
   python test_llm_flow.py
   ```
5. Commit, push, trên server `git pull && ./install.sh`.
6. Sau khi chạy thật, xem log `dictionary_rule_mismatch` / `dictionary_syntax_rule_failed`.

---

## 7. Hạn chế đã biết

- Giờ hôm nay đã qua ("chiều nay" gửi lúc 17h, "họp 2h chiều nay" gửi lúc 16h) vẫn được lưu với giờ quá khứ, nên worker gửi ngay.
- Giờ 1h–5h khi cả giờ sáng lẫn giờ chiều hôm nay đã qua → giờ sáng hôm sau ("gọi khách 3h" lúc 16:31 → 03:00).
- "còn 2h nữa" được hiểu là "2 giờ nữa kể từ bây giờ" (thời điểm tương đối), không phải thời lượng; chỉ "còn 2h" (không có "nữa") mới là thời lượng.
