# Intent: phân loại loại việc (`intents.json`)

Mỗi lịch nhắc được gắn một **intent**, tức loại việc như họp, mời ăn hay hạn chót. Intent quyết định bot **nhắc thêm** những gì ngoài lịch đúng giờ.

- Dữ liệu: `intents.json`. Sửa từ khoá, hành vi và trọng số ở đây, không cần sửa code.
- Code: `dictionary_parser.py` (`classify_intent`, `get_intent`, `load_intents`) và `telegrambot.py` (`build_intent_reminders`).
- Sửa `intents.json` xong phải **khởi động lại bot** (`./install.sh` trên server).

Intent là bước **thứ hai**, tách khỏi câu hỏi "câu có phải yêu cầu nhắc không":

| Câu hỏi | Nơi xử lý | Nếu sai thì sao |
|---|---|---|
| Có phải yêu cầu nhắc không? | Cổng của Dictionary (`intent_keywords` + `blockers` trong `dictionary.json`), không chắc thì LLM quyết định | Tạo lịch rác hoặc bỏ sót lịch |
| Loại việc gì? | `intents.json`, không khớp thì `khac` | Chỉ sai phần nhắc thêm, lịch chính vẫn đúng |

---

## 1. Danh sách intent và hành vi

| Intent | Ví dụ | Nhắc thêm (ngoài đúng giờ) | Giờ 1 chữ số dời sang chiều |
|---|---|---|---|
| 👥 `hop` Họp | họp giao ban, meeting, hội ý, phỏng vấn, gặp đối tác, lên phòng | Trước **15 và 5 phút** | 1h–6h |
| 🍽 `moi_an` Mời ăn / tiệc | mời ăn, ăn tối với khách, liên hoan, đám cưới, nhậu, cafe, làm chén, chia tay | Trước **45 và 30 phút**, kể cả khi chỉ ghi buổi trưa/tối | 1h–9h |
| ⏳ `deadline` Hạn chót | deadline, nộp báo cáo, hết hạn, chốt, trình ký, hoàn thành | Trước **1 ngày** nếu còn hơn 24 giờ | mặc định |
| 💳 `thanh_toan` Thanh toán | đóng tiền nhà, thanh toán thẻ, chuyển khoản, học phí, trả góp | Trước 1 ngày nếu còn hơn 24 giờ; gợi ý "hàng tháng" | mặc định |
| 🎉 `su_kien` Sự kiện | sinh nhật, giỗ, kỷ niệm ngày cưới, khai trương, đám tang | Trước 1 ngày nếu còn hơn 24 giờ; gợi ý "hàng năm" | mặc định |
| 💊 `suc_khoe` Sức khoẻ | uống thuốc, tái khám, tiêm phòng, tập gym | Không, **không lặp** | mặc định |
| 📞 `lien_lac` Liên lạc | gọi, email, nhắn zalo, báo giá, phản hồi | Không | mặc định |
| 💼 `cong_viec` Công việc | backup, deploy, trực ca, giao hàng, công tác, ôn thi | Không | mặc định |
| 🏠 `ca_nhan` Cá nhân | đón con, đi chợ, đổ xăng, cắt tóc, về quê | Không | mặc định |
| 📌 `khac` Khác | Không khớp từ khoá nào | Không | mặc định |

**Điều kiện nhắc thêm:**

- **Nhắc trước theo phút** (họp, mời ăn):
  - chỉ khi người dùng **ghi giờ cụ thể**. Giờ bot tự đặt (9h) không phải giờ hẹn thật;
  - không áp dụng cho âm lịch. Với Rule/Dictionary còn phải **không lặp**;
  - mốc đã qua thì bỏ: "họp 10 phút nữa" chỉ còn nhắc trước 5 phút.
- **Giờ theo buổi của mời ăn** (`period_times`, `alerts_on_period`): câu mời ăn chỉ ghi buổi, không ghi giờ:
  - "trưa" → 12:00, "tối" → **18:00**. Các loại việc khác vẫn dùng giờ mặc định 20:00 cho buổi tối;
  - vẫn nhắc trước 45 và 30 phút. Ví dụ "trưa mai ctay ông ở quán làm chén nha" → 12:00, nhắc lúc 11:15 và 11:30;
  - nếu 18:00 hôm nay đã qua ("tối nay ăn tối" gửi lúc 18:30) thì giữ giờ mặc định của buổi (20:00).
- **Nhắc trước theo ngày** (hạn chót, thanh toán, sự kiện):
  - chỉ khi lịch **không lặp** và còn **hơn 24 giờ** nữa mới tới. Ví dụ hạn chót 9h ngày mai mà gửi lúc 10h hôm nay thì còn 23 giờ, nên không nhắc trước;
  - không cần ghi giờ cụ thể;
  - lịch lặp hàng tháng/năm đã có nhắc trước 1 ngày của worker.
- **Gợi ý lặp** chỉ là một dòng `💡` trong tin xác nhận, bot không tự đặt lặp.

Mỗi lịch nhắc thêm là một bản ghi riêng ("Nhắc trước 45 phút: …", "Nhắc trước 1 ngày: …"), có cùng `intent` với lịch chính. Bản ghi này không mang thông tin âm lịch.

---

## 2. Intent được xác định ở đâu

| Nguồn nhận diện | Cách lấy intent |
|---|---|
| Rule, Dictionary, Default | `classify_intent(tin gốc)` |
| LLM | Trường `intent` trong JSON trả về. Prompt đọc danh sách và câu ví dụ từ `intents.json` (`intent_catalog()`), nên Dictionary và LLM dùng chung một danh sách. Intent không thuộc danh sách thì tự phân loại; `is_meeting=true` kiểu cũ thì là `hop` |

Kết quả lưu ở cột `reminders.intent`. `migrate()` tự thêm cột này khi khởi động. Lịch cũ có `intent = NULL`.

Hiển thị cho người dùng:
- tin xác nhận: `🗂 Loại: ⏳ Hạn chót` và `🔔 Nhắc thêm: trước 1 ngày và đúng giờ`;
- lệnh `ls`: `ID: 12 · ⏳ Hạn chót`. Intent `khac` thì không hiện.

---

## 3. Cách tính điểm

Mọi tham số nằm trong `_meta.scoring` của `intents.json`.

1. **Chuẩn hoá:** NFKC, chữ thường, gộp khoảng trắng. **Không bỏ dấu**, vì bỏ dấu sẽ gây trùng: "hop" có thể là họp, hợp hay hộp.
   - **Mở rộng viết tắt** (`abbreviations`) trước khi dò từ khoá: "vs" → với, "ctay" → chia tay, "bc" → báo cáo, "hđ" → hợp đồng, "ae" → anh em... Chỉ dùng để phân loại, không đổi nội dung lưu.
2. **Ghép từ khoá:** xét theo ranh giới từ. **Cụm dài nhất trong cả câu chiếm chỗ trước**, cụm ngắn nằm trong cụm đã khớp bị bỏ qua.
   - "nộp tiền điện" chỉ tính cho thanh toán, không tính chữ "nộp" cho deadline;
   - "đi đám cưới" lấy cụm "đám cưới" (mời ăn), không lấy "đi đám".
3. **Điểm của mỗi từ khoá:** `trọng số × (1 + 0.5 × (số chữ − 1))`, mỗi từ khoá chỉ tính một lần.
   - từ khoá `strong` có trọng số 3, `weak` có trọng số 1;
   - ví dụ "uống thuốc" (mạnh, 2 chữ) được 4,5 điểm.
4. **Từ khoá khớp sớm nhất trong câu được +1 điểm** (`first_match_bonus`), vì đó thường là động từ chính. Ví dụ "hoàn thành slide thuyết trình" ra deadline, không ra họp.
5. **Phần sau từ chỉ mục đích** ("để", "về việc", "bàn về", "liên quan"...): mỗi intent chỉ tính một từ khoá điểm cao nhất, nhân 0,5. Ví dụ "họp về việc thanh toán công nợ" ra họp.
6. **`exclude` của intent:** câu khớp cụm loại trừ thì intent đó bị loại.
   - "liên hoan mừng sinh nhật" không tính sự kiện, nên ra mời ăn;
   - "gọi món" không tính liên lạc;
   - "nộp tiền" không tính deadline.
7. Intent điểm cao nhất thắng. **Bằng điểm thì xét `priority`**: họp 90 > mời ăn 85 > thanh toán 75 > deadline 70 > sự kiện 65 > sức khoẻ 60 > liên lạc 50 > công việc 40 > cá nhân 30. Không đạt `min_score` thì ra `khac`.

Có thể xem vì sao một câu ra intent nào:

```python
from dictionary_parser import classify_intent
r = classify_intent("tối mai liên hoan mừng sinh nhật sếp")
print(r.id, r.score, r.hits)   # moi_an 5.5 ['liên hoan']
```

---

## 4. Cấu trúc một intent

```json
{
  "id": "moi_an",
  "label": "Mời ăn / tiệc",
  "emoji": "🍽",
  "priority": 85,
  "behavior": {
    "alerts_before_minutes": [45, 30],
    "alert_before_days": null,
    "bare_hour_pm": [1, 9],
    "suggest_repeat": null,
    "period_times": { "trưa": "12:00", "tối": "18:00" },
    "alerts_on_period": true
  },
  "keywords": { "strong": ["mời ăn", "ăn tối", "liên hoan", "làm chén"], "weak": ["mời", "nhà hàng", "chia tay"] },
  "exclude": ["ăn kiêng", "uống thuốc"],
  "examples": ["tối mai 7h mời đối tác ăn tối"]
}
```

| Trường | Ý nghĩa |
|---|---|
| `alerts_before_minutes` | Danh sách phút nhắc trước |
| `alert_before_days` | `{"days": 1, "only_if_lead_hours_over": 24}` hoặc `null` |
| `bare_hour_pm` | Khoảng giờ 1 chữ số được hiểu là giờ chiều; `null` thì dùng `dictionary.json → bare_hour_pm.hours` |
| `suggest_repeat` | `monthly` / `yearly` / `weekly` / `daily` hoặc `null` |
| `period_times` | Giờ riêng khi chỉ ghi buổi: `{"trưa": "12:00", "tối": "18:00"}`. Chỉ thay khi giờ đang là giờ mặc định của buổi và giờ mới còn ở tương lai |
| `alerts_on_period` | `true`: vẫn nhắc trước theo phút khi chỉ ghi buổi có trong `period_times` |
| `examples` | Câu ví dụ, được đưa vào prompt LLM |

---

## 5. Lưu ý khi thêm từ khoá

- **Mạnh hay yếu:** từ gần như chỉ mang một nghĩa thì để `strong` ("thanh toán", "uống thuốc", "liên hoan"). Từ chung chung, đa nghĩa thì để `weak` ("mời", "tiền", "đón", "gửi").
- **Ưu tiên cụm từ:** dùng "gửi mail", "gửi hàng", "gửi báo cáo" thay cho từ "gửi" đứng một mình.
- **Một từ khoá chỉ thuộc một intent.** Bộ nạp bỏ qua lần xuất hiện thứ hai, nên trước khi thêm hãy tìm xem từ đó đã có ở intent khác chưa.
- **Cổng "có phải yêu cầu nhắc":** cụm từ khoá mạnh từ 2 chữ trở lên tự động được dùng để mở cổng. Từ đơn thì không, vì thường là danh từ. Muốn một từ đơn mở cổng thì thêm vào `dictionary.json → intent_keywords`.
- **Biến thể không dấu:** chỉ thêm cho cụm từ hai chữ trở lên ("thanh toan", "uong thuoc"), không thêm cho từ đơn.
- **Thêm intent mới:** chỉ cần thêm một mục vào `intents`, kèm `behavior`. Code và prompt LLM tự đọc danh sách. Nhớ thêm câu vào `test_intents.py`.

---

## 6. Quy trình sửa

1. Ghi câu bị phân loại sai, kèm intent đúng.
2. Thêm vào `test_intents.py`: `TUNED_CASES` nếu dùng để chỉnh từ khoá, `BLIND_CASES` nếu để kiểm tra độc lập.
3. Sửa `intents.json`: thêm từ khoá, đổi `strong`/`weak`, thêm `exclude` hoặc chỉnh `priority`.
4. Chạy `python test_intents.py`, rồi chạy cả `test_dictionary_parser.py`, `test_parse_routing.py`, `test_llm_flow.py`.
5. Commit, push, rồi trên server chạy `git pull && ./install.sh`. Dockerfile đã có `COPY intents.json .`.
6. Theo dõi log `reminder_created ... intent=...`. Nhiều lịch rơi vào `khac` là dấu hiệu cần bổ sung từ khoá.

Kết quả hiện tại: 155/155 câu phân loại đúng (gồm 5 câu từ lóng / viết tắt), 51/51 câu ở cổng đúng. Trong đó, 47 câu kiểm tra độc lập đạt 43/47 ở lần chạy đầu, trước khi chỉnh từ khoá; con số này sát hơn với độ chính xác trên câu thật.
