"""
Test phân loại intent (intents.json) và hành vi nhắc thêm theo intent.
Chạy: python test_intents.py
"""
import io
import sys
from datetime import datetime, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from dictionary_parser import (
    classify_intent, get_intent, parse_with_dictionary, shift_bare_hour_to_pm, apply_intent_period_time,
)
import telegrambot

# (intent kỳ vọng, câu) — bộ câu dùng khi xây từ điển
TUNED_CASES = [
    ('hop', 'họp giao ban 8h mai'),
    ('hop', '3h chiều meeting với khách'),
    ('hop', 'hội ý dự án 2 tiếng nữa'),
    ('hop', 'phỏng vấn ứng viên 10h thứ 5'),
    ('hop', '9h zoom với team'),
    ('hop', 'mai 2h gặp đối tác ở công ty'),
    ('hop', 'chiều nay 4h 30 lên phòng sếp'),
    ('hop', 'thứ 2 họp phụ huynh'),
    ('hop', '10h họp với khách để chốt thanh toán'),
    ('hop', 'daily scrum 9h hàng ngày'),
    ('hop', '14h review code'),
    ('hop', 'thứ 6 tổng kết quý'),
    ('hop', 'mời họp 3h chiều'),
    ('hop', 'chiều mai làm việc với sở'),
    ('hop', '8h30 đào tạo nhân viên mới'),
    ('moi_an', 'tối mai 7h mời đối tác ăn tối'),
    ('moi_an', 'trưa nay 11h30 ăn cơm với khách'),
    ('moi_an', 'thứ 7 đi đám cưới bạn'),
    ('moi_an', '6h tối liên hoan phòng'),
    ('moi_an', 'tối nay đi nhậu với anh em'),
    ('moi_an', '3h chiều cafe với chị Lan'),
    ('moi_an', 'tất niên công ty 18h ngày 20/1'),
    ('moi_an', 'mai 12h lunch với đối tác'),
    ('moi_an', 'tối thứ 6 tiệc sinh nhật bé'),
    ('moi_an', '7h tối dinner với khách Nhật'),
    ('moi_an', 'thứ 7 year end party'),
    ('moi_an', 'đặt bàn nhà hàng 7h tối'),
    ('deadline', 'thứ 6 nộp báo cáo tháng'),
    ('deadline', 'deadline dự án 30/11'),
    ('deadline', '20/12 hết hạn hợp đồng thuê nhà'),
    ('deadline', 'mai chốt số liệu quý'),
    ('deadline', 'nộp hồ sơ ngày 25'),
    ('deadline', 'hạn chót đăng ký đề tài thứ 4'),
    ('deadline', 'gửi báo cáo cho sếp trước 5h'),
    ('deadline', '15/12 gia hạn domain'),
    ('deadline', 'mai trình ký tờ trình'),
    ('deadline', 'thứ 2 hoàn thành slide thuyết trình'),
    ('deadline', 'cuối tháng quyết toán thuế'),
    ('deadline', '7 ngày nữa hết hạn trial'),
    ('deadline', 'mai làm báo cáo tuần'),
    ('deadline', 'release bản mới thứ 5'),
    ('thanh_toan', 'mùng 5 đóng tiền nhà'),
    ('thanh_toan', 'ngày 20 thanh toán thẻ tín dụng'),
    ('thanh_toan', 'mai chuyển khoản cho nhà cung cấp'),
    ('thanh_toan', 'cuối tháng trả lương'),
    ('thanh_toan', 'mai đóng học phí cho con'),
    ('thanh_toan', 'nộp tiền điện ngày 15'),
    ('thanh_toan', 'ngày 10 trả góp xe'),
    ('thanh_toan', 'thứ 2 xuất hóa đơn cho khách'),
    ('thanh_toan', 'nộp thuế môn bài 30/1'),
    ('thanh_toan', 'mai đóng bảo hiểm xe'),
    ('thanh_toan', 'ngày 25 gia hạn gói icloud'),
    ('su_kien', 'thứ 5 sinh nhật vợ'),
    ('su_kien', '15/3 âm lịch giỗ ông nội'),
    ('su_kien', '20/10 mua hoa cho mẹ'),
    ('su_kien', 'mai đi viếng đám tang'),
    ('su_kien', 'kỷ niệm ngày cưới 12/6'),
    ('su_kien', 'rằm tháng 7 cúng'),
    ('su_kien', 'thứ 7 khai trương cửa hàng'),
    ('su_kien', 'sn sếp 15/8'),
    ('su_kien', 'mai lễ tốt nghiệp của con'),
    ('suc_khoe', '8h tối uống thuốc'),
    ('suc_khoe', 'thứ 3 tái khám ở bệnh viện'),
    ('suc_khoe', 'mai tiêm phòng cho con'),
    ('suc_khoe', '6h sáng chạy bộ'),
    ('suc_khoe', 'chiều mai đi khám răng'),
    ('suc_khoe', '9h xét nghiệm máu'),
    ('suc_khoe', '5h chiều tập gym'),
    ('suc_khoe', '10h tối đi ngủ'),
    ('suc_khoe', 'nhắc tôi uống thuốc lúc 9h'),
    ('lien_lac', '9h sáng mai gọi cho khách'),
    ('lien_lac', 'mai email cho đối tác'),
    ('lien_lac', 'chiều nay nhắn zalo cho anh Nam'),
    ('lien_lac', 'thứ 2 báo giá cho khách'),
    ('lien_lac', 'mai trả lời mail khách hàng'),
    ('lien_lac', '3h gọi lại cho ngân hàng'),
    ('lien_lac', 'mai hỏi anh Hùng về hợp đồng'),
    ('lien_lac', 'thứ 4 follow up khách'),
    ('lien_lac', 'mai e email cho đối tác nhé'),
    ('cong_viec', '9h tối backup server'),
    ('cong_viec', 'thứ 7 trực ca đêm'),
    ('cong_viec', 'mai giao hàng cho khách'),
    ('cong_viec', 'tối nay ôn thi'),
    ('cong_viec', 'mai deploy bản fix'),
    ('cong_viec', 'thứ 2 đi công tác Đà Nẵng'),
    ('cong_viec', 'mai xin nghỉ phép'),
    ('cong_viec', 'chiều nay kiểm tra hệ thống'),
    ('cong_viec', '8h tối học tiếng anh'),
    ('ca_nhan', '15h đón con'),
    ('ca_nhan', 'tối nay mua sữa cho con'),
    ('ca_nhan', 'mai đổ xăng'),
    ('ca_nhan', 'thứ 7 cắt tóc'),
    ('ca_nhan', 'chủ nhật dọn nhà'),
    ('ca_nhan', 'mai trả sách thư viện'),
    ('ca_nhan', '2 tiếng nữa tắt bếp'),
    ('ca_nhan', '6h sáng ra sân bay'),
    ('ca_nhan', 'tối mai 8h xem bóng đá'),
    ('ca_nhan', '4h chiều tưới cây'),
    ('ca_nhan', 'cuối tuần về quê'),
    ('ca_nhan', 'mai lấy hàng ở bưu điện'),
    ('khac', 'nhắc tôi lúc 9h'),
    ('khac', 'mai nhớ nhé'),
    ('khac', '9h sáng mai'),
]

# Từ lóng / viết tắt (vs, ctay, bc, làm chén...)
SLANG_CASES = [
    ('moi_an', 'Hi, trưa mai tớ vs chị Hiền ctay mời ông trưa qua quán Quốc Dân làm chén nha'),
    ('moi_an', 'trưa mai ctay ông ở Quốc Dân làm chén nha'),
    ('moi_an', 'tối nay làm vài ly với ae'),
    ('moi_an', 'thứ 6 liên hoan chia tay bạn Nam'),
    ('deadline', 'nộp bc thứ 6'),
]

# Bộ câu KHÔNG dùng để chỉnh từ khoá (đo khả năng tổng quát); có câu trộn nhiều loại
BLIND_CASES = [
    ('hop', '2h chiều bàn kế hoạch marketing với phòng kinh doanh'),
    ('hop', 'thứ 5 họp hội đồng quản trị'),
    ('hop', '8h sáng mai sinh hoạt chi bộ'),
    ('hop', '10h call với team Singapore'),
    ('hop', 'mai 9h gặp khách bàn về báo giá'),
    ('hop', 'thứ 3 họp về việc thanh toán công nợ'),
    ('hop', '14h teams với đối tác'),
    ('moi_an', 'trưa mai đi ăn với sếp'),
    ('moi_an', '7h tối nhậu chia tay đồng nghiệp'),
    ('moi_an', 'thứ 7 dự tiệc cưới em họ'),
    ('moi_an', 'cafe sáng với khách 8h'),
    ('moi_an', 'tối mai liên hoan mừng sinh nhật sếp'),
    ('moi_an', '12h ăn trưa cùng đối tác'),
    ('deadline', 'thứ 6 hạn nộp tiểu luận'),
    ('deadline', '15/12 phải xong hồ sơ thầu'),
    ('deadline', 'mai gửi file thiết kế cho khách'),
    ('deadline', 'cuối tháng nộp kế hoạch năm'),
    ('deadline', 'thứ 4 duyệt hợp đồng'),
    ('deadline', '30/11 hết hạn bảo hành máy'),
    ('thanh_toan', 'mùng 10 trả tiền mạng'),
    ('thanh_toan', 'mai nạp tiền điện thoại'),
    ('thanh_toan', 'ngày 15 đóng phí chung cư'),
    ('thanh_toan', 'thứ 2 thu tiền khách hàng'),
    ('thanh_toan', 'cuối tháng tất toán khoản vay'),
    ('su_kien', 'mai đầy tháng cháu'),
    ('su_kien', '8/3 tặng quà vợ'),
    ('su_kien', 'chủ nhật đi chùa'),
    ('su_kien', 'mai lễ khai giảng của con'),
    ('suc_khoe', '9h tối nhỏ mắt'),
    ('suc_khoe', 'thứ 7 đi spa'),
    ('suc_khoe', 'mai lấy kết quả xét nghiệm'),
    ('suc_khoe', '5h chiều đi bơi'),
    ('lien_lac', 'mai báo lại cho anh Tuấn'),
    ('lien_lac', 'chiều nay phản hồi khách hàng'),
    ('lien_lac', '9h liên hệ bên vận chuyển'),
    ('lien_lac', 'mai gọi cho khách về việc báo giá'),
    ('cong_viec', 'mai cài lại máy cho kế toán'),
    ('cong_viec', 'thứ 3 kiểm kê kho'),
    ('cong_viec', 'tối nay làm bài tập'),
    ('cong_viec', '8h nhận ca'),
    ('cong_viec', 'mai khảo sát công trình'),
    ('ca_nhan', 'chiều nay đi chợ'),
    ('ca_nhan', 'mai rửa xe'),
    ('ca_nhan', '7h tối đánh cầu lông'),
    ('ca_nhan', 'thứ 7 đi du lịch Sapa'),
    ('ca_nhan', 'mai thay dầu xe máy'),
    ('ca_nhan', 'chủ nhật thăm ông bà'),
]

# Cổng "có phải yêu cầu nhắc" của Dictionary: (câu, True = là nhắc / False = không phải nhắc)
GATE_NOW = datetime(2026, 11, 25, 10, 0)
GATE_CASES = [
    ('mai gửi báo cáo cho sếp', True),
    ('chiều nay 3h họp phòng', True),
    ('thứ 6 nộp hồ sơ', True),
    ('9h sáng mai gọi cho khách', True),
    ('30 phút nữa uống thuốc', True),
    ('tối nay mua sữa cho con', True),
    ('mai đi khám răng', True),
    ('thứ 2 tuần sau đóng tiền nhà', True),
    ('15h đón con', True),
    ('ngày 30 thanh toán thẻ tín dụng', True),
    ('mai nhớ mang laptop', True),
    ('chủ nhật dọn nhà', True),
    ('tối mai 8h xem bóng đá', True),
    ('mai làm slide thuyết trình', True),
    ('sáng mai check mail khách hàng', True),
    ('thứ 5 sinh nhật vợ', True),
    ('cuối tuần đi siêu thị', True),
    ('4h chiều tưới cây', True),
    ('mai đổ xăng', True),
    ('tối nay ôn bài', True),
    ('mai chuyển khoản tiền điện', True),
    ('hàng ngày 7h tập thể dục', True),
    ('2 tiếng nữa tắt bếp', True),
    ('mai lấy hàng ở bưu điện', True),
    ('thứ 7 cắt tóc', True),
    ('mai trả sách thư viện', True),
    ('chiều mai rút tiền', True),
    ('hôm nay trời mưa to quá', False),
    ('mai được nghỉ rồi vui quá', False),
    ('hôm qua 9h mới về nhà', False),
    ('tối nay ăn gì nhỉ', False),
    ('mai họp không em', False),
    ('mai mấy giờ họp', False),
    ('sáng nay đi làm tắc đường kinh khủng', False),
    ('chiều nay mệt quá', False),
    ('tối qua xem phim hay ghê', False),
    ('thứ 6 vừa rồi đi nhậu vui', False),
    ('ok 9h nhé', False),
    ('ừ mai nói chuyện sau', False),
    ('hôm nay mail nhiều quá', False),
    ('mai là sinh nhật tôi đấy', False),
    ('cảm ơn anh, mai em gửi lại sau ạ', False),
    ('2 tiếng nữa là tan làm rồi', False),
    ('tuần sau trời lạnh', False),
    ('8h tối qua mất điện', False),
    ('anh đi họp chưa', False),
    ('hôm nay đã gửi báo cáo rồi', False),
    ('mai đi làm muộn chút nhé sếp', False),
    ('đã nộp hồ sơ hôm thứ 2', False),
    ('họp xong lúc 5h rồi', False),
    ('mai em bận không đi được', False),
]
# Hai câu mơ hồ, cố ý vẫn nhận (người dùng gửi cho bot nhắc lịch thì thường muốn được nhắc)
GATE_ACCEPTED_AMBIGUOUS = {"mai là sinh nhật tôi đấy", "mai đi làm muộn chút nhé sếp"}


def test_classify():
    failures = []
    for name, cases in (("tuned", TUNED_CASES), ("blind", BLIND_CASES), ("slang", SLANG_CASES)):
        for want, text in cases:
            got = classify_intent(text)
            if got.id != want:
                failures.append(text)
                print(f"❌ [{name}] {text!r}: kỳ vọng {want}, ra {got.id} (điểm {got.score}, {got.hits})")
    total = len(TUNED_CASES) + len(BLIND_CASES) + len(SLANG_CASES)
    print(f"Phân loại: {total - len(failures)}/{total} đúng")
    assert not failures, f"{len(failures)} câu phân loại sai"


def test_gate():
    failures = []
    for text, is_reminder in GATE_CASES:
        got = parse_with_dictionary(text, now=GATE_NOW) is not None
        want = is_reminder or text in GATE_ACCEPTED_AMBIGUOUS
        if got != want:
            failures.append(text)
            print(f"❌ cổng: {text!r}: kỳ vọng {'nhận' if want else 'None'}, ra {'nhận' if got else 'None'}")
    print(f"Cổng nhắc lịch: {len(GATE_CASES) - len(failures)}/{len(GATE_CASES)} đúng")
    assert not failures, f"{len(failures)} câu sai ở cổng"


def _labels(reminders):
    return [m.split(":", 1)[0] for m, _, _ in reminders[1:]]


def test_behaviors():
    now = datetime(2026, 11, 25, 10, 0)
    at = lambda d, h, m=0: datetime(2026, 11, d, h, m)
    hop, moi_an = get_intent("hop"), get_intent("moi_an")
    deadline, suc_khoe = get_intent("deadline"), get_intent("suc_khoe")
    b = telegrambot.build_intent_reminders

    # Họp: 15 + 5 phút; mời ăn: 45 + 30 phút
    assert _labels(b("Họp", at(25, 15), "none", hop, True, now)) == ["Nhắc trước 15 phút", "Nhắc trước 5 phút"]
    r = b("Ăn tối", at(25, 19), "none", moi_an, True, now)
    assert _labels(r) == ["Nhắc trước 45 phút", "Nhắc trước 30 phút"]
    assert [t for _, t, _ in r] == [at(25, 19), at(25, 18, 15), at(25, 18, 30)]
    # Mời ăn 20 phút nữa: 45/30 phút đã qua → chỉ còn đúng giờ
    assert _labels(b("Ăn", now + timedelta(minutes=20), "none", moi_an, True, now)) == []
    # Không ghi giờ cụ thể → không nhắc trước theo phút
    assert _labels(b("Họp", at(26, 9), "none", hop, False, now)) == []

    # Deadline: còn > 24h → nhắc trước 1 ngày (cùng giờ); còn <= 24h → chỉ đúng giờ
    r = b("Nộp báo cáo", at(27, 9), "none", deadline, False, now)
    assert _labels(r) == ["Nhắc trước 1 ngày"] and r[1][1] == at(26, 9)
    assert _labels(b("Nộp báo cáo", at(26, 9), "none", deadline, False, now)) == []
    # Deadline lặp lại → worker đã có nhắc trước 1 ngày cho lịch tháng/năm, không thêm lịch
    assert _labels(b("Nộp báo cáo", at(27, 9), "monthly", deadline, False, now)) == []

    # Sức khoẻ: không lặp, không nhắc thêm
    assert _labels(b("Uống thuốc", at(25, 20), "none", suc_khoe, True, now)) == []
    assert get_intent("suc_khoe").suggest_repeat is None
    print("✅ Hành vi nhắc thêm theo intent đúng")


def test_bare_hour_by_intent():
    now = datetime(2026, 11, 25, 14, 0)
    # Mời ăn: 7h lúc 14:00 → 19:00 hôm nay (ăn tối); họp: 7h → 7:00 sáng mai (không họp tối muộn)
    assert shift_bare_hour_to_pm("7h ăn tối với khách", datetime(2026, 11, 26, 7, 0), now=now) == datetime(2026, 11, 25, 19, 0)
    assert shift_bare_hour_to_pm("7h họp giao ban", datetime(2026, 11, 26, 7, 0), now=now) == datetime(2026, 11, 26, 7, 0)
    assert shift_bare_hour_to_pm("họp lúc 5h", datetime(2026, 11, 26, 5, 0), now=now) == datetime(2026, 11, 25, 17, 0)
    print("✅ Giờ 1 chữ số theo intent đúng")


def test_period_time():
    now = datetime(2026, 11, 27, 10, 0)
    moi_an, hop = get_intent("moi_an"), get_intent("hop")
    f = apply_intent_period_time
    # Mời ăn chỉ ghi buổi: tối 20:00 (mặc định buổi) → 18:00; trưa giữ 12:00; cả hai đều cho phép nhắc trước
    assert f("tối mai mời đối tác ăn tối", moi_an, datetime(2026, 11, 28, 20, 0), now=now) == (datetime(2026, 11, 28, 18, 0), True)
    assert f("trưa mai làm chén", moi_an, datetime(2026, 11, 28, 12, 0), now=now) == (datetime(2026, 11, 28, 12, 0), True)
    # Có giờ cụ thể → không đụng
    assert f("7h tối mai ăn tối", moi_an, datetime(2026, 11, 28, 19, 0), now=now) == (datetime(2026, 11, 28, 19, 0), False)
    # 18:00 hôm nay đã qua → giữ giờ mặc định của buổi
    late = datetime(2026, 11, 27, 18, 30)
    assert f("tối nay ăn tối", moi_an, datetime(2026, 11, 27, 20, 0), now=late) == (datetime(2026, 11, 27, 20, 0), True)
    # Intent không có period_times (họp) → giữ 20:00
    assert f("tối mai họp", hop, datetime(2026, 11, 28, 20, 0), now=now) == (datetime(2026, 11, 28, 20, 0), False)
    print("✅ Giờ theo buổi của intent (mời ăn tối 18:00) đúng")


def test_llm_intent():
    # LLM trả intent hợp lệ → dùng; intent lạ → tự phân loại; is_meeting cũ → họp
    assert telegrambot.intent_from_llm({"intent": "moi_an"}, "abc").id == "moi_an"
    assert telegrambot.intent_from_llm({"intent": "xyz"}, "mai nộp báo cáo").id == "deadline"
    assert telegrambot.intent_from_llm({"is_meeting": True}, "abc").id == "hop"
    assert telegrambot.intent_from_llm({}, "abc").id == "khac"
    print("✅ Intent từ LLM đúng")


if __name__ == "__main__":
    test_classify()
    test_gate()
    test_behaviors()
    test_bare_hour_by_intent()
    test_period_time()
    test_llm_intent()
    print("\n🎉 Intent: phân loại, cổng và hành vi đều đúng")
