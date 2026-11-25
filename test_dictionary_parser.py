"""
Test bước 2 (Dictionary) với thời điểm cố định NOW = 18/11/2026 10:00 (Thứ 4).
Chạy: python test_dictionary_parser.py
"""
import io
import sys
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from dictionary_parser import parse_with_dictionary

NOW = datetime(2026, 11, 18, 10, 0)  # Thứ 4

# Kỳ vọng:
#   None                                   -> không nhận, để rơi xuống LLM
#   [(message, "dd/mm/YYYY HH:MM", repeat)] -> lịch dương lịch
#   ("LUNAR", standard_syntax)              -> chuyển cho parse_lunar_reminder
CASES = [
    # ---------- giờ + ngày tương đối ----------
    ("Họp chiều mai 3h", [("Họp", "19/11/2026 15:00", "none")]),
    ("mai 9h họp", [("Họp", "19/11/2026 09:00", "none")]),
    ("8h kém 15 sáng mai đi khám", [("Đi khám", "19/11/2026 07:45", "none")]),
    ("Đi đón con lúc 4 rưỡi chiều nay", [("Đi đón con", "18/11/2026 16:30", "none")]),
    ("họp 14.30 thứ 5", [("Họp", "19/11/2026 14:30", "none")]),
    ("9pm gọi cho sếp", [("Gọi cho sếp", "18/11/2026 21:00", "none")]),
    ("Ăn trưa với team 12h trưa mai", [("Ăn trưa với team", "19/11/2026 12:00", "none")]),
    ("đá bóng 1h trưa thứ 7", [("Đá bóng", "21/11/2026 13:00", "none")]),
    ("xem phim 11h đêm nay", [("Xem phim", "18/11/2026 23:00", "none")]),
    ("Ngủ sớm 10 giờ tối", [("Ngủ sớm", "18/11/2026 22:00", "none")]),
    ("Họp 8 giờ 30 sáng thứ hai tuần sau", [("Họp", "23/11/2026 08:30", "none")]),
    ("Đi khám 7h30 sáng 25/11", [("Đi khám", "25/11/2026 07:30", "none")]),
    ("check mail 5h sáng", [("Check mail", "19/11/2026 05:00", "none")]),
    ("họp 9g30 sáng mai", [("Họp", "19/11/2026 09:30", "none")]),
    ("Gọi khách lúc 15h15", [("Gọi khách", "18/11/2026 15:15", "none")]),
    ("đón vợ 5h chiều", [("Đón vợ", "18/11/2026 17:00", "none")]),
    ("ba giờ chiều mai họp", [("Họp", "19/11/2026 15:00", "none")]),
    ("họp lúc 7:30 am mai", [("Họp", "19/11/2026 07:30", "none")]),
    ("hom nay 8h toi goi me", None),  # 'toi' không dấu = tối/tới/tôi → không đoán, để LLM
    ("di kham ngay mai 9h", [("Di kham", "19/11/2026 09:00", "none")]),

    # ---------- N phút / giờ nữa ----------
    ("gọi điện cho mẹ 30p nữa", [("Gọi điện cho mẹ", "18/11/2026 10:30", "none")]),
    ("1 tiếng rưỡi nữa tắt bếp", [("Tắt bếp", "18/11/2026 11:30", "none")]),
    ("hai tiếng nữa đón con", [("Đón con", "18/11/2026 12:00", "none")]),
    ("nửa tiếng nữa họp", [("Họp", "18/11/2026 10:30", "none")]),
    ("15 phút nữa gọi lại khách", [("Gọi lại khách", "18/11/2026 10:15", "none")]),
    ("tắt máy giặt mười lăm phút nữa", [("Tắt máy giặt", "18/11/2026 10:15", "none")]),
    ("1 tiếng 15 phút nữa lấy bánh", [("Lấy bánh", "18/11/2026 11:15", "none")]),
    ("rút sạc 2h nữa", [("Rút sạc", "18/11/2026 12:00", "none")]),
    ("in 10 minutes call John", [("Call John", "18/11/2026 10:10", "none")]),

    # ---------- ngày cụ thể ----------
    ("Sinh nhật vợ 20/12", [("Sinh nhật vợ", "20/12/2026 09:00", "none")]),
    ("Nộp thuế ngày 05/01/2027", [("Nộp thuế", "05/01/2027 09:00", "none")]),
    ("Gia hạn hộ chiếu 2027-03-15", [("Gia hạn hộ chiếu", "15/03/2027 09:00", "none")]),
    ("đóng học phí 10/11", [("Đóng học phí", "10/11/2027 09:00", "none")]),
    ("Gửi hồ sơ ngày 5 tháng 12", [("Gửi hồ sơ", "05/12/2026 09:00", "none")]),
    ("họp tổng kết 20 tháng 12 năm 2026 lúc 14h", [("Họp tổng kết", "20/12/2026 14:00", "none")]),
    ("trả tiền nhà mùng 5", [("Trả tiền nhà", "05/12/2026 09:00", "none")]),
    ("nộp báo cáo ngày 25", [("Nộp báo cáo", "25/11/2026 09:00", "none")]),
    ("họp ngày 5 tháng sau 9h", [("Họp", "05/12/2026 09:00", "none")]),
    ("khám định kỳ 20-11-26 lúc 8h", [("Khám định kỳ", "20/11/2026 08:00", "none")]),
    ("thi chứng chỉ 12.12.2026 7h", [("Thi chứng chỉ", "12/12/2026 07:00", "none")]),

    # ---------- ngày tính toán ----------
    ("giao hàng 3 ngày nữa", [("Giao hàng", "21/11/2026 09:00", "none")]),
    ("gia hạn domain 2 tuần nữa", [("Gia hạn domain", "02/12/2026 09:00", "none")]),
    ("kiểm tra xe 1 tháng nữa", [("Kiểm tra xe", "18/12/2026 09:00", "none")]),
    ("Đi chơi cuối tuần này", [("Đi chơi", "21/11/2026 09:00", "none")]),
    ("Đi chơi cuối tuần", [("Đi chơi", "21/11/2026 09:00", "none")]),
    ("dọn kho cuối tuần sau", [("Dọn kho", "28/11/2026 09:00", "none")]),
    ("họp đầu tuần sau", [("Họp", "23/11/2026 09:00", "none")]),
    ("deadline dự án đầu tháng sau", [("Deadline dự án", "01/12/2026 09:00", "none")]),
    ("Thanh toán thẻ tín dụng cuối tháng", [("Thanh toán thẻ tín dụng", "30/11/2026 09:00", "none")]),
    ("đóng bảo hiểm cuối tháng 2/2027", [("Đóng bảo hiểm", "28/02/2027 09:00", "none")]),
    ("tổng kết cuối năm", [("Tổng kết", "31/12/2026 09:00", "none")]),
    ("đi du lịch ngày kia 6h sáng", [("Đi du lịch", "20/11/2026 06:00", "none")]),
    ("sửa xe ngày mốt", [("Sửa xe", "20/11/2026 09:00", "none")]),
    ("họp lớp giờ này ngày mai", [("Họp lớp", "19/11/2026 10:00", "none")]),
    ("nộp bài thứ 6 tuần sau nữa", [("Nộp bài", "04/12/2026 09:00", "none")]),
    ("lên kế hoạch đầu tháng 1", [("Lên kế hoạch", "01/01/2027 09:00", "none")]),
    ("Nộp báo cáo thứ sáu tuần sau", [("Nộp báo cáo", "27/11/2026 09:00", "none")]),

    # ---------- ngày lễ ----------
    ("mua quà noel", [("Mua quà", "25/12/2026 09:00", "none")]),
    ("tặng hoa 8/3", [("Tặng hoa", "08/03/2027 09:00", "none")]),
    ("gọi cô giáo ngày nhà giáo", [("Gọi cô giáo", "20/11/2026 09:00", "none")]),
    ("đặt vé tết dương lịch 8h", [("Đặt vé", "01/01/2027 08:00", "none")]),

    # ---------- thứ trong tuần ----------
    ("họp t6", [("Họp", "20/11/2026 09:00", "none")]),
    ("Họp thứ 4 lúc 9h", [("Họp", "25/11/2026 09:00", "none")]),
    ("Họp thứ 4 lúc 15h", [("Họp", "18/11/2026 15:00", "none")]),
    ("chủ nhật đi chợ 7h", [("Đi chợ", "22/11/2026 07:00", "none")]),
    ("cn này dọn nhà", [("Dọn nhà", "22/11/2026 09:00", "none")]),
    ("thứ 6 tới liên hoan 18h", [("Liên hoan", "20/11/2026 18:00", "none")]),
    ("chiều thứ 6 đi đá bóng", [("Đi đá bóng", "20/11/2026 16:00", "none")]),
    ("thu 3 tuan sau 10h gap doi tac", [("Gap doi tac", "24/11/2026 10:00", "none")]),
    ("Tập gym t2 t4 t6 lúc 18h", [
        ("Tập gym", "18/11/2026 18:00", "none"),
        ("Tập gym", "20/11/2026 18:00", "none"),
        ("Tập gym", "23/11/2026 18:00", "none"),
    ]),
    ("học tiếng anh thứ ba và thứ năm 20h", [
        ("Học tiếng anh", "19/11/2026 20:00", "none"),
        ("Học tiếng anh", "24/11/2026 20:00", "none"),
    ]),

    # ---------- lặp ----------
    ("họp mỗi thứ 2 lúc 8h", [("Họp", "23/11/2026 08:00", "weekly")]),
    ("uống thuốc mỗi ngày 8h tối", [("Uống thuốc", "18/11/2026 20:00", "daily")]),
    ("tập thể dục hằng ngày 6h sáng", [("Tập thể dục", "19/11/2026 06:00", "daily")]),
    ("Đóng tiền điện mùng 5 hàng tháng", [("Đóng tiền điện", "05/12/2026 09:00", "monthly")]),
    ("tưới cây cách ngày 7h", [("Tưới cây", "19/11/2026 07:00", "every_2d")]),
    ("Họp quý hàng quý ngày 1/1/2027", [("Họp quý", "01/01/2027 09:00", "every_3m")]),
    ("Backup dữ liệu 3 ngày 1 lần lúc 23h", [("Backup dữ liệu", "18/11/2026 23:00", "every_3d")]),
    ("chấm công ngày thường 8h", [("Chấm công", "19/11/2026 08:00", "weekday")]),
    ("sinh nhật mẹ 15/6 hàng năm", [("Sinh nhật mẹ", "15/06/2027 09:00", "yearly")]),
    ("thay lọc nước cứ 2 tháng 1 lần ngày 1/12", [("Thay lọc nước", "01/12/2026 09:00", "every_2m")]),
    ("đi chợ mỗi cuối tuần 8h", [("Đi chợ", "19/11/2026 08:00", "weekend")]),

    # ---------- âm lịch (chuyển cho parse_lunar_reminder) ----------
    ("Trung thu mua bánh", ("LUNAR", "Mua bánh lúc 09:00 ngày 15/08 âm lịch")),
    ("Giỗ ông 15/3 âl", ("LUNAR", "Giỗ ông lúc 09:00 ngày 15/03 âm lịch")),
    ("Cúng rằm tháng 10 âm lịch 7h", ("LUNAR", "Cúng lúc 07:00 ngày 15/10 âm lịch")),
    ("Giỗ bà ngày 8 tháng 3 âm lịch hàng năm", ("LUNAR", "Giỗ bà lúc 09:00 ngày 08/03 âm lịch hàng năm")),
    ("tết về quê", ("LUNAR", "Về quê lúc 09:00 ngày 01/01 âm lịch")),
    ("cúng ông công ông táo 9h", ("LUNAR", "Cúng lúc 09:00 ngày 23/12 âm lịch")),
    ("giỗ cụ 10/2 am lich 8h sáng", ("LUNAR", "Giỗ cụ lúc 08:00 ngày 10/02 âm lịch")),

    # ---------- giữ nguyên nội dung ----------
    ("Gặp anh Tuấn tại Vincom lúc 3h chiều mai", [("Gặp anh Tuấn tại Vincom", "19/11/2026 15:00", "none")]),
    ("nhắc tôi gọi bảo hiểm 9h sáng mai nhé", [("Gọi bảo hiểm", "19/11/2026 09:00", "none")]),
    ("Mua 3g data ngày kia", [("Mua 3g data", "20/11/2026 09:00", "none")]),
    ("Nộp sáng kiến lúc 9h ngày 25/11", [("Nộp sáng kiến", "25/11/2026 09:00", "none")]),
    ("Họp một ngày đẹp trời lúc 9h mai", [("Họp một ngày đẹp trời", "19/11/2026 09:00", "none")]),
    ("Họp với chị Mai 9h sáng thứ 2", [("Họp với chị Mai", "23/11/2026 09:00", "none")]),
    ("mai họp 9h với chị Mai", [("Họp với chị Mai", "19/11/2026 09:00", "none")]),
    ("thứ 6 ngày 20/11 họp 9h", [("Họp", "20/11/2026 09:00", "none")]),
    ("Nâng cấp RAM server 22h", [("Nâng cấp RAM server", "18/11/2026 22:00", "none")]),
    ("Đọc sách 2 chương lúc 21h", [("Đọc sách 2 chương", "18/11/2026 21:00", "none")]),

    # ---------- không nhận -> LLM ----------
    ("hôm nay trời đẹp quá", None),
    ("Chào buổi sáng", None),
    ("mai mấy giờ họp?", None),
    ("9h", None),
    ("ngày mai", None),
    ("Họp lúc 9h và 14h ngày mai", None),
    ("ok cảm ơn", None),
    ("Chị Mai ơi", None),
    ("họp tuần sau", None),
    ("deadline 31/11", None),
    ("họp 24h", None),
    ("Lịch họp tuần:\n- T2 9h họp giao ban\n- T4 14h họp dự án\n- T6 10h review", None),
    ("x" * 301 + " lúc 9h", None),
    ("Sinh nhật: Nguyễn A mùng 3 tháng 2, Trần B ngày 15 tháng 7", None),  # mỗi ngày 1 người → LLM tách

    # ---------- tán gẫu / câu hỏi / quá khứ: không được tự tạo lịch ----------
    ("ok 9h nhé", None),
    ("cuối tuần này đi đâu chơi nhỉ", None),
    ("Giáng sinh vui vẻ", None),
    ("Trung thu năm nay sớm thế", None),
    ("tết này về quê không", None),
    ("2 năm nữa mới xong dự án này", None),
    ("nhà số 12/3 ngõ 45", None),
    ("chiều nay họp xong chưa", None),
    ("mai mốt rảnh thì gặp", None),
    ("hồi sáng mai có ghé", None),
    ("thứ 2 vừa rồi họp rất lâu", None),
    ("Tỷ lệ 3/4 đã hoàn thành", None),
    ("phiên bản 2.10 đã release", None),
    ("Hôm nay là ngày 18/11", None),
    ("sáng mai đẹp trời ghê", None),
    ("mai được nghỉ rồi", None),
    ("thứ 6 vui vẻ nhé mọi người", None),
    ("khi nào họp vậy", None),
    ("mấy giờ đi ăn", None),
    ("7 ngày nữa là hết hạn trial", [("Là hết hạn trial", "25/11/2026 09:00", "none")]),  # có 'hết hạn' → coi là nhắc
    ("Nộp hồ sơ hôm nay", [("Nộp hồ sơ", "18/11/2026 16:00", "none")]),

    # ----- tin thật: email/nhắn tin + "mai" không ghi giờ → 9h sáng -----
    ("Mai e email cho net nhé", [("E email cho net", "19/11/2026 09:00", "none")]),
    ("Ngày mai Đào tuấn email cho NET về việc off",
     [("Đào tuấn email cho NET về việc off", "19/11/2026 09:00", "none")]),
    ("mai nhắn zalo cho khách", [("Nhắn zalo cho khách", "19/11/2026 09:00", "none")]),
    ("thứ 6 trả lời mail đối tác", [("Trả lời mail đối tác", "20/11/2026 09:00", "none")]),
    ("chốt hợp đồng ngày 25", [("Chốt hợp đồng", "25/11/2026 09:00", "none")]),
    # thứ trùng hôm nay (Thứ 4, 10h) không ghi giờ → vẫn trong hôm nay
    ("họp thứ 4", [("Họp", "18/11/2026 16:00", "none")]),
    # "Mai ơi" là gọi tên, không phải ngày mai
    ("Mai ơi họp nhé", None),
    ("Mai ơi mai họp nhé", [("Mai ơi họp", "19/11/2026 09:00", "none")]),
    # ----- buổi + "nay" và khoảng thời gian (duration) không bị hiểu là giờ nhắc -----
    ("vậy chiều nay khoảng 4h 30 anh em mình hội ý tiếp vụ này, cố găng rút ngắn thời gian còn 2h là đẹp",
     [("Vậy anh em mình hội ý tiếp vụ này, cố găng rút ngắn thời gian còn 2 tiếng là đẹp", "18/11/2026 16:30", "none")]),
    ("sáng nay 10h30 họp, dự kiến kéo dài 2 tiếng", [("Họp, dự kiến kéo dài 2 tiếng", "18/11/2026 10:30", "none")]),
    ("tối nay 8h ôn thi, mất khoảng 1h30", [("Ôn thi, mất 1 tiếng 30 phút", "18/11/2026 20:00", "none")]),
    ("chiều nay 3h họp tối đa 1h", [("Họp tối đa 1 tiếng", "18/11/2026 15:00", "none")]),
    ("trưa nay 12h ăn cơm với khách", [("Ăn cơm với khách", "18/11/2026 12:00", "none")]),
    # "còn 2h nữa" vẫn là thời gian tương đối
    ("còn 2h nữa họp", [("Còn họp", "18/11/2026 12:00", "none")]),

    # ----- giờ trần 1 chữ số, 5h sáng đã qua (NOW 10:00) → 17h hôm nay, không phải 5h sáng mai -----
    ("5h anh em lên phòng anh tiếp vụ này nhé",
     [("Anh em lên phòng anh tiếp vụ này", "18/11/2026 17:00", "none")]),
    ("họp lúc 5h30", [("Họp", "18/11/2026 17:30", "none")]),
    ("họp lúc 5h hôm nay", [("Họp", "18/11/2026 17:00", "none")]),
    # cuộc họp chỉ dời 1–6h; họp 7/8/9h đã qua giờ sáng → sáng hôm sau, không họp tối muộn
    ("họp lúc 9h", [("Họp", "19/11/2026 09:00", "none")]),
    ("8h họp giao ban", [("Họp giao ban", "19/11/2026 08:00", "none")]),
    ("họp lúc 6h", [("Họp", "18/11/2026 18:00", "none")]),
    # không phải họp → vẫn dời tới 9h tối
    ("9h gọi điện cho mẹ", [("Gọi điện cho mẹ", "18/11/2026 21:00", "none")]),
    # không áp dụng: có ngày khác hôm nay, có buổi, giờ 2 chữ số, lặp lại
    ("họp lúc 5h mai", [("Họp", "19/11/2026 05:00", "none")]),
    ("họp 5h sáng mai", [("Họp", "19/11/2026 05:00", "none")]),
    ("họp lúc 05h", [("Họp", "19/11/2026 05:00", "none")]),
    ("họp 5h thứ 6", [("Họp", "20/11/2026 05:00", "none")]),

    # từ khoá quá chung không còn kích hoạt
    ("hôm nay mail nhiều quá", None),
    ("zalo mai bị lỗi", None),
    ("mai email được không", None),

    # ---------- lỗi tìm thấy ở vòng soát độ phủ ----------
    ("uống thuốc huyết áp 7h sáng và 7h tối hàng ngày", None),  # 2 liều → LLM tách
    ("Mua vé tàu tết trước 15/12", None),  # 'tết' là định ngữ, mốc thật là 15/12 → LLM
    ("khoảng 3 giờ chiều mai gửi báo giá cho khách", [("Gửi báo giá cho khách", "19/11/2026 15:00", "none")]),
    ("giao ban mỗi sáng thứ 2 lúc 8h30", [("Giao ban", "23/11/2026 08:30", "weekly")]),
    ("họp mỗi tối thứ 5 lúc 8h", [("Họp", "19/11/2026 20:00", "weekly")]),
    ("tập yoga 18h các ngày trong tuần", [("Tập yoga", "18/11/2026 18:00", "weekday")]),
    ("đổi mật khẩu mỗi 3 tháng ngày 1/12", [("Đổi mật khẩu", "01/12/2026 09:00", "every_3m")]),
    ("Nộp hồ sơ ngày 18/11", [("Nộp hồ sơ", "18/11/2026 16:00", "none")]),
    ("họp dự án thứ 2, review code thứ 4 lúc 9h", None),
    ("trực ca 20/11, 25/11 và 30/11 lúc 7h", [
        ("Trực ca", "20/11/2026 07:00", "none"),
        ("Trực ca", "25/11/2026 07:00", "none"),
        ("Trực ca", "30/11/2026 07:00", "none"),
    ]),
]


def _check(text, expected):
    res = parse_with_dictionary(text, now=NOW)
    if expected is None:
        if res is None:
            return None
        return f"kỳ vọng None, nhận {res}"
    if res is None:
        return "kỳ vọng nhận được, nhận None"
    if isinstance(expected, tuple) and expected[0] == "LUNAR":
        if not res.is_lunar:
            return f"kỳ vọng âm lịch, nhận {res.items}"
        if res.standard_syntax != expected[1]:
            return f"standard_syntax {res.standard_syntax!r} != {expected[1]!r}"
        return None
    if res.is_lunar:
        return f"kỳ vọng dương lịch, nhận âm lịch {res.standard_syntax!r}"
    got = [(m, dt.strftime("%d/%m/%Y %H:%M"), r) for m, dt, r in res.items]
    if got != expected:
        return f"{got} != {expected}"
    return None


def test_dictionary_cases():
    failures = []
    for text, expected in CASES:
        err = _check(text, expected)
        label = text if len(text) < 60 else text[:57] + "..."
        if err:
            failures.append((label, err))
            print(f"❌ {label!r}: {err}")
        else:
            print(f"✅ {label!r}")
    print(f"\n{len(CASES) - len(failures)}/{len(CASES)} case đạt")
    assert not failures, f"{len(failures)} case sai"


def test_auto_time_flag():
    assert parse_with_dictionary("Sinh nhật vợ 20/12", now=NOW).auto_time is True
    assert parse_with_dictionary("mai 9h họp", now=NOW).auto_time is False


def test_lunar_syntax_compatible_with_rule_parser():
    """standard_syntax âm lịch phải được parse_lunar_reminder() chấp nhận."""
    import telegrambot
    for text, expected in CASES:
        if isinstance(expected, tuple) and expected[0] == "LUNAR":
            res = parse_with_dictionary(text, now=NOW)
            parsed = telegrambot.parse_lunar_reminder(res.standard_syntax)
            assert parsed is not None, f"parse_lunar_reminder không đọc được {res.standard_syntax!r}"
            print(f"✅ âm lịch {res.standard_syntax!r} -> {parsed[1]:%d/%m/%Y %H:%M}")


if __name__ == "__main__":
    test_dictionary_cases()
    test_auto_time_flag()
    test_lunar_syntax_compatible_with_rule_parser()
    print("\n🎉 Tất cả test dictionary đều qua")
