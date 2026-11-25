"""
Bước 2 của luồng nhận diện thời gian: ánh xạ từ điển (dictionary.json).

Luồng trong add_reminder():
    1. Rule        - parse_message / parse_multi_reminder / parse_lunar_reminder
    2. Dictionary  - parse_with_dictionary() (module này)
    3. LLM         - parse_with_gemini()
    4. Default     - get_default_remind_time()

parse_with_dictionary() chuẩn hoá câu theo dictionary.json rồi tính thẳng datetime.
Trả về DictionaryResult hoặc None (để rơi xuống LLM).
"""
from __future__ import annotations

import calendar
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable, Optional

from dateutil.relativedelta import relativedelta

from lunarcalendar import lunar_to_solar, solar_to_lunar

DICTIONARY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dictionary.json")

MAX_TEXT_LENGTH = 300
MAX_LINES = 3

# Từ đứng trước "mai" khiến "mai" là tên người / danh từ, không phải "ngày mai"
_MAI_NAME_PREFIXES = {
    "chị", "anh", "em", "cô", "chú", "bác", "bà", "ông", "bạn", "cháu", "con", "mẹ", "bố",
    "dì", "cậu", "mợ", "thím", "sếp", "bé", "hoa", "cành", "cây", "chậu", "vàng", "tên", "nhà",
}

# Ký tự đánh dấu vị trí token đã bị gỡ khỏi nội dung
_MARK = "\x00"


@dataclass
class DictionaryResult:
    items: list = field(default_factory=list)   # [(message, datetime, repeat_type)] cho dương lịch
    standard_syntax: str = ""                    # cú pháp chuẩn của item đầu (âm lịch: cả câu)
    is_lunar: bool = False                       # True: telegrambot gọi parse_lunar_reminder(standard_syntax)
    auto_time: bool = False                      # True: không có giờ cụ thể, từ điển tự chọn giờ
    syntaxes: list = field(default_factory=list)  # cú pháp chuẩn từng item dương lịch → Rule parse


# =========================================================
# LOAD + COMPILE
# =========================================================
def _phrase_regex(phrases):
    ordered = sorted(set(phrases), key=len, reverse=True)
    return re.compile(r"(?<!\w)(" + "|".join(re.escape(p) for p in ordered) + r")(?!\w)")


class _Dictionary:
    def __init__(self, path: str):
        with open(path, encoding="utf-8") as f:
            self.data = json.load(f)
        d = self.data

        self.number_words = d["number_words"]
        self.offset_words = d["offset_words"]

        # Bước 2: phrases + holidays → text thay thế hoặc compute
        self.phrase_map: dict[str, object] = {}
        for group in d["phrases"].values():
            for entry in group["entries"]:
                for src in entry["from"]:
                    self.phrase_map[src] = entry["to"]
        hol = d["holidays"]
        for entry in hol["solar"] + hol["lunar"]:
            for src in entry["from"]:
                self.phrase_map[src] = entry["to"]
        for entry in hol.get("lunar_computed", []):
            for src in entry["from"]:
                self.phrase_map[src] = entry["compute"]
        self.phrase_re = _phrase_regex(self.phrase_map)

        # Regex rules theo stage, giữ nguyên thứ tự trong file
        self.stages: dict[str, list] = {}
        for rule in d["regex_rules"]:
            self.stages.setdefault(rule["stage"], []).append(
                (re.compile(rule["pattern"]), rule.get("replace"), rule.get("compute"))
            )

        # Bước 8: computed phrases
        self.computed_map = {}
        for entry in d["computed_phrases"]:
            for src in entry["from"]:
                self.computed_map[src] = entry["compute"]
        self.computed_re = _phrase_regex(self.computed_map)

        # Buổi trong ngày
        self.period_map = {}
        for p in d["periods"]:
            for w in p["words"]:
                self.period_map[w] = p
        self.period_re = _phrase_regex(self.period_map)

        # Giờ mặc định theo từ khoá
        self.keyword_rules = [
            (_phrase_regex(r["keywords"]), r["time"]) for r in d["default_time_by_keyword"]["rules"]
        ]
        self.intent_re = _phrase_regex(d.get("intent_keywords", []) or ["nhắc"])
        self.meeting_re = _phrase_regex(d.get("meeting_keywords", {}).get("keywords", []) or ["họp"])
        self.bare_hour_pm = tuple(d.get("bare_hour_pm", {}).get("hours", [1, 9]))
        self.bare_hour_pm_meeting = tuple(d.get("bare_hour_pm", {}).get("meeting_hours", [1, 6]))

        blockers = d.get("blockers", {})
        endings = blockers.get("question_endings", [])
        self.question_end_re = (
            re.compile(r"(?<!\w)(?:" + "|".join(re.escape(w) for w in sorted(endings, key=len, reverse=True)) + r")[\s.!…~]*$")
            if endings else None
        )
        block_phrases = blockers.get("question_phrases", []) + blockers.get("past_markers", []) + blockers.get("idioms", [])
        self.block_re = _phrase_regex(block_phrases) if block_phrases else None


_DICT: Optional[_Dictionary] = None


def load_dictionary(path: str = DICTIONARY_PATH, force: bool = False) -> _Dictionary:
    global _DICT
    if _DICT is None or force:
        _DICT = _Dictionary(path)
    return _DICT


# =========================================================
# BUFFER: giữ song song bản gốc (giữ hoa/thường) và bản chữ thường
# =========================================================
class _Buf:
    def __init__(self, text: str):
        t = unicodedata.normalize("NFKC", text)
        t = re.sub(r"[ \t\u00a0]+", " ", t)
        t = "\n".join(line.strip() for line in t.splitlines() if line.strip())
        self.orig = t
        self.low = t.lower()
        if len(self.low) != len(self.orig):   # hiếm: lower() đổi độ dài → bỏ giữ hoa/thường
            self.orig = self.low

    def sub(self, pattern: re.Pattern, repl: Callable[[re.Match], Optional[str]]):
        out_low, out_orig, pos = [], [], 0
        for m in pattern.finditer(self.low):
            rep = repl(m)
            if rep is None or rep == m.group(0):
                continue
            out_low.append(self.low[pos:m.start()])
            out_orig.append(self.orig[pos:m.start()])
            out_low.append(rep)
            out_orig.append(rep)
            pos = m.end()
        if pos:
            out_low.append(self.low[pos:])
            out_orig.append(self.orig[pos:])
            self.low = "".join(out_low)
            self.orig = "".join(out_orig)


# =========================================================
# COMPUTE
# =========================================================
def _fmt_date(d: date) -> str:
    return f"ngày {d.day:02d}/{d.month:02d}/{d.year}"


def _safe_date(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _grp(m: re.Match, idx) -> Optional[str]:
    if idx is None:
        return None
    try:
        return m.group(idx)
    except IndexError:
        return None


def _weekday_index(text: str) -> Optional[int]:
    text = text.strip()
    if text == "chủ nhật":
        return 6
    mm = re.fullmatch(r"thứ ([2-7])", text)
    return int(mm.group(1)) - 2 if mm else None


class _Computer:
    def __init__(self, dct: _Dictionary, now: datetime):
        self.d = dct
        self.now = now
        self.today = now.date()

    def run(self, spec: dict, m: Optional[re.Match]) -> Optional[str]:
        fn = getattr(self, "_c_" + spec["type"], None)
        if fn is None:
            return None
        try:
            return fn(spec, m)
        except (ValueError, KeyError, TypeError, OverflowError):
            return None

    # ---- số ----
    def _c_number_word(self, s, m):
        n = self.d.number_words[_grp(m, s["group"])]
        return s.get("output", "{n}").format(n=n)

    # ---- tương đối ----
    def _c_relative_minutes(self, s, m):
        h = int(_grp(m, s.get("hours_group")) or 0)
        mi = int(_grp(m, s.get("minutes_group")) or 0)
        total = h * 60 + mi + (30 if s.get("half") else 0)
        return f"{total} phút nữa" if total > 0 else None

    def _c_relative_days(self, s, m):
        n = s["days"] if "days" in s else int(_grp(m, s["days_group"]))
        return _fmt_date(self.today + timedelta(days=n))

    def _c_relative_weeks(self, s, m):
        return _fmt_date(self.today + timedelta(weeks=int(_grp(m, s["group"]))))

    def _c_relative_months(self, s, m):
        return _fmt_date(self.today + relativedelta(months=int(_grp(m, s["group"]))))

    def _c_relative_years(self, s, m):
        return _fmt_date(self.today + relativedelta(years=int(_grp(m, s["group"]))))

    def _c_relative_en(self, s, m):
        n = int(_grp(m, s["number_group"]))
        unit = _grp(m, s["unit_group"])
        if unit.startswith("min"):
            return f"{n} phút nữa"
        if unit.startswith("h"):
            return f"{n} giờ nữa"
        if unit.startswith("day"):
            return _fmt_date(self.today + timedelta(days=n))
        if unit.startswith("week"):
            return _fmt_date(self.today + timedelta(weeks=n))
        return None

    # ---- ngày ----
    def _infer_year(self, day: int, month: int) -> Optional[date]:
        for y in (self.today.year, self.today.year + 1, self.today.year + 2, self.today.year + 3, self.today.year + 4):
            d = _safe_date(y, month, day)
            if d and d >= self.today:
                return d
        return None

    def _c_infer_year(self, s, m):
        d = self._infer_year(int(_grp(m, s["day_group"])), int(_grp(m, s["month_group"])))
        return _fmt_date(d) if d else None

    def _c_next_day_of_month(self, s, m):
        day = int(_grp(m, s["day_group"]))
        if not 1 <= day <= 31:
            return None
        base = self.today.replace(day=1)
        for k in range(0, 13):
            first = base + relativedelta(months=k)
            d = _safe_date(first.year, first.month, day)
            if d and d >= self.today:
                return _fmt_date(d)
        return None

    def _c_day_of_month(self, s, m):
        day = int(_grp(m, s["day_group"]))
        offset = self.d.offset_words[_grp(m, s["offset_group"]).strip()]
        first = self.today.replace(day=1) + relativedelta(months=offset)
        d = _safe_date(first.year, first.month, day)
        return _fmt_date(d) if d else None

    def _month_day(self, year: int, month: int, day) -> Optional[date]:
        if day == "last":
            day = calendar.monthrange(year, month)[1]
        return _safe_date(year, month, int(day))

    def _c_month_day(self, s, m):
        day = s["day"]
        month_s = _grp(m, s.get("month_group")) if m is not None else None
        if month_s:
            month = int(month_s)
            year_s = _grp(m, s.get("year_group"))
            if year_s:
                d = self._month_day(int(year_s), month, day)
            else:
                d = self._month_day(self.today.year, month, day)
                if d and d < self.today:
                    d = self._month_day(self.today.year + 1, month, day)
            return _fmt_date(d) if d else None

        first = self.today.replace(day=1) + relativedelta(months=s.get("month_offset", 0))
        d = self._month_day(first.year, first.month, day)
        if d and s.get("roll_forward") and d < self.today:
            first = first + relativedelta(months=1)
            d = self._month_day(first.year, first.month, day)
        return _fmt_date(d) if d else None

    def _c_week_day(self, s, m):
        if "weekday_group" in s:
            wd = _weekday_index(_grp(m, s["weekday_group"]))
        else:
            wd = s["weekday"]
        if wd is None:
            return None
        monday = self.today - timedelta(days=self.today.weekday())
        d = monday + timedelta(days=7 * s.get("week_offset", 0) + wd)
        if s.get("roll_forward") and d < self.today:
            d += timedelta(days=7)
        return _fmt_date(d)

    def _c_year_day(self, s, m):
        y = self.today.year + s.get("year_offset", 0)
        d = _safe_date(y, s["month"], s["day"])
        if d and s.get("roll_forward") and d < self.today:
            d = _safe_date(y + 1, s["month"], s["day"])
        return _fmt_date(d) if d else None

    # ---- giờ ----
    def _c_time_minus(self, s, m):
        h = int(_grp(m, s["hour_group"]))
        mi = int(_grp(m, s["minute_group"]))
        total = h * 60 - mi
        if total < 0 or mi >= 60:
            return None
        return f"{total // 60:02d}:{total % 60:02d}"

    def _c_ampm(self, s, m):
        h = int(_grp(m, s["hour_group"]))
        mi = int(_grp(m, s["minute_group"]) or 0)
        marker = _grp(m, s["marker_group"]).replace(".", "")
        if marker == "am":
            h = 0 if h == 12 else h
        elif h < 12:
            h += 12
        return f"{h:02d}:{mi:02d}"

    def _c_same_time(self, s, m):
        return f"{self.now:%H:%M} " + _fmt_date(self.today + timedelta(days=s["days"]))

    def _c_lunar_new_year_eve(self, s, m):
        ld, lm, ly, _ = solar_to_lunar(self.today.day, self.today.month, self.today.year)
        sd, sm, sy = lunar_to_solar(30, 12, ly)
        last = 29
        if sd:
            back = solar_to_lunar(sd, sm, sy)
            if back[0] == 30 and back[1] == 12:
                last = 30
        return f"ngày {last}/12 âm lịch"


# =========================================================
# TOKEN EXTRACTION
# =========================================================
_REL_RE = re.compile(r"(?<!\w)(\d{1,4}) (phút|giờ) nữa(?!\w)")
_TIME_RE = re.compile(r"(?<![\w:/.])([01]?\d|2[0-3]):([0-5]\d)(?![\w:/])")
_DATE_RE = re.compile(r"(?<!\w)ngày (\d{1,2})/(\d{1,2})/(\d{4})(?![\w/])")
_WEEKDAY_RE = re.compile(r"(?<!\w)(thứ [2-7]|chủ nhật)(?: (tuần này|tuần sau))?(?!\w)")
_DAYREF_RE = re.compile(r"(?<!\w)(hôm nay|mai)(?!\w)")
_REPEAT_RE = re.compile(
    r"(?<!\w)(?:repeat\s+)?(hàng ngày|daily|hàng tuần|weekly|hàng tháng|monthly|hàng năm|yearly|"
    r"ngày thường|weekday|weekend|mỗi (\d{1,3}) (ngày|tuần|tháng|năm))(?!\w)"
)
_LUNAR_RE = re.compile(r"(?<!\w)(?:âm\s*lịch|lịch\s*âm)(?!\w)")
_LUNAR_DATE_RES = [
    re.compile(r"(?<!\w)(?:(?:ngày|mùng|mồng|mung|mong)\s+)?(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*\d{4})?(?![\d/])"),
    re.compile(r"(?<!\w)(?:(?:ngày|mùng|mồng|mung|mong)\s+)?(\d{1,2})\s+tháng\s+(\d{1,2})(?!\d)"),
]
_RESIDUAL_TIME_RE = re.compile(r"(?<![\w:])(?:[01]?\d|2[0-3])\s*(?:h|giờ|gio)(?:\s*[0-5]?\d)?(?![a-zà-ỹ])|(?<![\w:/])(?:[01]?\d|2[0-3]):[0-5]\d(?!\d)")
_LIST_GAP_RE = re.compile(r"[\s,;&/+-]*(?:(?:và|va|hoặc|hoac|với|voi|and)[\s,;&/+-]*)?")
_GAP_RE = re.compile(r"[\s,]*(?:(?:lúc|luc|vào|vao|ngày|hôm|buổi|at|khoảng|tầm|-)[\s,]*)*")

_REPEAT_CODE = {
    "hàng ngày": "daily", "daily": "daily",
    "hàng tuần": "weekly", "weekly": "weekly",
    "hàng tháng": "monthly", "monthly": "monthly",
    "hàng năm": "yearly", "yearly": "yearly",
    "ngày thường": "weekday", "weekday": "weekday",
    "weekend": "weekend",
}
_UNIT_CODE = {"ngày": "d", "tuần": "w", "tháng": "m", "năm": "y"}
_REPEAT_VI = {
    "daily": "hàng ngày", "weekly": "hàng tuần", "monthly": "hàng tháng", "yearly": "hàng năm",
    "weekday": "ngày thường", "weekend": "cuối tuần",
}
_UNIT_VI = {"d": "ngày", "w": "tuần", "m": "tháng", "y": "năm"}


def _repeat_words(code: str) -> str:
    if code in _REPEAT_VI:
        return _REPEAT_VI[code]
    mm = re.fullmatch(r"every_(\d+)([dwmy])", code)
    return f"mỗi {mm.group(1)} {_UNIT_VI[mm.group(2)]}" if mm else ""


def _overlaps(spans, s, e):
    return any(not (e <= a or s >= b) for a, b in spans)


def _is_name_mai(buf: _Buf, start: int) -> bool:
    before = buf.low[:start].rstrip()
    prev = before.split()[-1] if before.split() else ""
    if prev in _MAI_NAME_PREFIXES:
        return True
    # "Mai ơi ..." → gọi tên người
    if re.match(r"\s*ơi(?!\w)", buf.low[start + 3:]):
        return True
    # Viết hoa "Mai" giữa câu → nhiều khả năng là tên riêng
    if buf.orig[start:start + 1] == "M" and start > 0 and buf.orig[start - 1] not in "\n":
        return True
    return False


def _clean_message(text: str) -> str:
    s = text
    connectors = (r"(?:vào khoảng|vào lúc|vao luc|tầm khoảng|khoảng|khoang|tầm|tam|lúc|luc|vào|vao|at|@|"
                  r"ngày|ngay|hôm|buổi|trước|truoc|before|on|và|va|,|-)")
    for _ in range(3):
        s = re.sub(r"(?i)(?:(?<=\s)|^)" + connectors + r"\s*(?=" + _MARK + ")", "", s)
        s = re.sub(r"(?i)(?<=" + _MARK + r")\s*" + connectors + r"(?=\s*(?:" + _MARK + r"|$))", "", s)
    s = s.replace(_MARK, " ")
    lines = []
    for line in s.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip(" ,.;:-–")
        if line:
            lines.append(line)
    s = "\n".join(lines)
    s = re.sub(
        r"(?i)^(?:ê bot|bot ơi|hey bot|remind me to|remind me|nhắc nhở|nhắc|nhớ)(?:\s+(?:tôi|tao|anh|em|mình|giúp|giùm|là))*\s+",
        "", s,
    )
    s = re.sub(r"(?i)\s+(?:nhé|nhe|nha|nhá|nhen|giúp|giùm|với|nhé bot|nha bot)$", "", s)
    s = s.strip(" ,.;:-–")
    return s[:1].upper() + s[1:] if s else s


# =========================================================
# MAIN
# =========================================================
@dataclass
class _Analysis:
    buf: _Buf
    low: str
    original_low: str
    spans: list
    is_lunar: bool
    lunar_date: Optional[tuple]
    rels: list
    times: list
    dates: list
    weekdays: list
    dayrefs: list
    repeats: list
    period: Optional[dict]

    def has_time_expression(self) -> bool:
        return bool(self.rels or self.times or self.dates or self.weekdays
                    or self.dayrefs or self.repeats or self.lunar_date)


def _analyze(text: str, now: datetime, dct: _Dictionary) -> _Analysis:
    """Chạy pipeline chuẩn hoá (bước 1-9) và tách token thời gian."""
    comp = _Computer(dct, now)
    buf = _Buf(text)
    original_low = buf.low

    # ---------- 2. phrases (2 lượt để cụm mới sinh ra cũng được chuẩn hoá) ----------
    def _phrase(m):
        val = dct.phrase_map.get(m.group(1))
        if isinstance(val, dict):
            return comp.run(val, None)
        return val

    buf.sub(dct.phrase_re, _phrase)
    buf.sub(dct.phrase_re, _phrase)

    is_lunar = bool(_LUNAR_RE.search(buf.low))

    def _run_stage(name):
        for pattern, replace, compute in dct.stages.get(name, []):
            if replace is not None:
                buf.sub(pattern, lambda m, r=replace: m.expand(r))
            else:
                buf.sub(pattern, lambda m, c=compute: comp.run(c, m))

    # ---------- 3-7. regex stages ----------
    _run_stage("weekday")
    _run_stage("number_words")
    _run_stage("relative")
    _run_stage("repeat")
    if not is_lunar:
        _run_stage("date")
    _run_stage("time")

    # ---------- 9. computed phrases ----------
    buf.sub(dct.computed_re, lambda m: comp.run(dct.computed_map[m.group(1)], None))

    # ---------- token extraction ----------
    low = buf.low
    spans: list[tuple[int, int]] = []

    def _collect(pattern, guard=None):
        found = []
        for m in pattern.finditer(low):
            if _overlaps(spans, m.start(), m.end()):
                continue
            if guard and not guard(m):
                continue
            spans.append((m.start(), m.end()))
            found.append(m)
        return found

    lunar_date = None
    lunar_date_count = 0
    if is_lunar:
        _collect(_LUNAR_RE)
        for lre in _LUNAR_DATE_RES:
            ms = _collect(lre)
            lunar_date_count += len(ms)
            if ms and lunar_date is None:
                lunar_date = (int(ms[0].group(1)), int(ms[0].group(2)))
        # 'vé tàu tết trước 15/12': có >= 2 ngày trong câu âm lịch → không biết ngày nào là mốc → để LLM
        if lunar_date_count > 1:
            lunar_date = None

    rels = _collect(_REL_RE)
    times = _collect(_TIME_RE)
    dates = _collect(_DATE_RE)
    weekdays = _collect(_WEEKDAY_RE)
    dayrefs = _collect(_DAYREF_RE, guard=lambda m: m.group(1) != "mai" or not _is_name_mai(buf, m.start()))
    repeats = _collect(_REPEAT_RE)

    hard_spans = list(spans)

    # Buổi trong ngày: chỉ tính khi đứng sát một token thời gian khác
    period = None
    for m in dct.period_re.finditer(low):
        if _overlaps(spans, m.start(), m.end()):
            continue
        near = False
        for a, b in hard_spans:
            gap = low[m.end():a] if m.end() <= a else low[b:m.start()]
            if _GAP_RE.fullmatch(gap):
                near = True
                break
        if near:
            spans.append((m.start(), m.end()))
            if period is None:
                period = dct.period_map[m.group(1)]

    return _Analysis(buf, low, original_low, spans, is_lunar, lunar_date,
                     rels, times, dates, weekdays, dayrefs, repeats, period)


def contains_time_expression(text: str, now: Optional[datetime] = None) -> bool:
    """True nếu câu còn chứa mốc thời gian (giờ, ngày, thứ, hôm nay/mai, N phút nữa, lặp).
    Dùng để kiểm tra nội dung mà Rule trả về: còn sót mốc thời gian nghĩa là Rule đã bỏ qua nó."""
    if not text or not text.strip():
        return False
    now = (now or datetime.now()).replace(second=0, microsecond=0)
    return _analyze(text, now, load_dictionary()).has_time_expression()


def is_meeting_text(text: str) -> bool:
    """True nếu câu có từ khoá cuộc họp (meeting_keywords trong dictionary.json)."""
    if not text:
        return False
    return bool(load_dictionary().meeting_re.search(unicodedata.normalize("NFKC", text).lower()))


def has_explicit_clock_time(text: str, now: Optional[datetime] = None) -> bool:
    """True nếu người dùng ghi giờ cụ thể (8h, 14:30, 4 rưỡi, 15 phút nữa...), không tính buổi/ngày."""
    if not text or not text.strip():
        return False
    now = (now or datetime.now()).replace(second=0, microsecond=0)
    a = _analyze(text, now, load_dictionary())
    return bool(a.times or a.rels)


def _bare_hour_pm(a: _Analysis, dct: _Dictionary, remind_time: datetime, repeat_type, now: datetime,
                  text: str = "") -> datetime:
    """Giờ trần 1 chữ số không kèm buổi ('5h', '5h30'): nếu giờ sáng hôm nay đã qua mà giờ chiều (+12)
    chưa tới → nhắc giờ chiều hôm nay. Không áp dụng khi có buổi, có ngày/thứ khác hôm nay, lặp, âm lịch.
    Câu là cuộc họp → chỉ dời với khoảng giờ hẹp hơn (meeting_hours, mặc định 1–6h): họp 7h/8h/9h
    gửi lúc chiều vẫn là sáng hôm sau, không đặt họp tối muộn."""
    if (repeat_type or "none") != "none" or a.is_lunar or a.period:
        return remind_time
    if a.rels or a.dates or a.weekdays or a.repeats:
        return remind_time
    if any(m.group(1) != "hôm nay" for m in a.dayrefs):
        return remind_time
    tokens = {(m.group(1), m.group(2)) for m in a.times}
    if len(tokens) != 1:
        return remind_time
    h_str, mi_str = tokens.pop()
    is_meeting = bool(text) and bool(dct.meeting_re.search(unicodedata.normalize("NFKC", text).lower()))
    lo, hi = dct.bare_hour_pm_meeting if is_meeting else dct.bare_hour_pm
    if len(h_str) != 1 or not lo <= int(h_str) <= hi:
        return remind_time  # '05h', '10h', '11h' giữ nguyên
    today = now.date()
    if remind_time.date() not in (today, today + timedelta(days=1)):
        return remind_time
    am = datetime(today.year, today.month, today.day, int(h_str), int(mi_str))
    pm = am + timedelta(hours=12)
    # Lệch so với giờ đã ghi (vd Rule cú pháp giờ-trước tự trừ 15 phút) → giữ nguyên độ lệch
    offset = datetime.combine(today, remind_time.time()) - am
    if abs(offset) > timedelta(minutes=30):
        return remind_time  # đã được hiểu là giờ khác (vd đã +12) → không đụng
    if am <= now < pm:
        return pm + offset
    return remind_time


def shift_bare_hour_to_pm(text: str, remind_time: datetime, repeat_type="none",
                          now: Optional[datetime] = None) -> datetime:
    """Dùng cho kết quả của Rule: áp cùng quy tắc giờ trần buổi chiều như Dictionary."""
    if not text or not remind_time:
        return remind_time
    now = (now or datetime.now()).replace(second=0, microsecond=0)
    dct = load_dictionary()
    return _bare_hour_pm(_analyze(text, now, dct), dct, remind_time, repeat_type, now, text)


def parse_with_dictionary(text: str, now: Optional[datetime] = None,
                          dictionary: Optional[_Dictionary] = None) -> Optional[DictionaryResult]:
    """Chuẩn hoá câu bằng từ điển. Trả None nếu không chắc chắn (để rơi xuống LLM)."""
    if not text or not text.strip():
        return None
    if len(text) > MAX_TEXT_LENGTH or len([l for l in text.splitlines() if l.strip()]) > MAX_LINES:
        return None
    if text.strip().endswith("?"):
        return None

    dct = dictionary or load_dictionary()
    now = (now or datetime.now()).replace(second=0, microsecond=0)

    # Câu hỏi / câu kể quá khứ / thành ngữ → không phải yêu cầu nhắc lịch chắc chắn → để LLM
    probe = unicodedata.normalize("NFKC", text).lower().strip()
    if dct.question_end_re and dct.question_end_re.search(probe):
        return None
    if dct.block_re and dct.block_re.search(probe):
        return None
    # Phải có từ chỉ ý định (nhắc, họp, nộp, gọi, đi, mua...) — kể cả khi có giờ rõ ràng ("ok 9h nhé")
    if not dct.intent_re.search(probe):
        return None

    analysis = _analyze(text, now, dct)
    a = analysis
    buf, low, original_low, spans = a.buf, a.low, a.original_low, a.spans
    is_lunar, lunar_date, period = a.is_lunar, a.lunar_date, a.period
    rels, times, dates, weekdays, dayrefs, repeats = a.rels, a.times, a.dates, a.weekdays, a.dayrefs, a.repeats

    # ---------- an toàn ----------
    # >= 2 mốc giờ (kể cả cùng số như '7h sáng và 7h tối') → nhiều lịch khác giờ, để LLM tách
    if len(times) > 1:
        return None
    distinct_times = [(int(m.group(1)), int(m.group(2))) for m in times]
    # Nhiều ngày / nhiều thứ chỉ được tách khi đứng liền nhau thành 1 danh sách
    # ("t2, t4, t6", "20/11 và 25/11"). Nằm rải rác → mỗi ngày có thể ứng với 1 nội dung khác → để LLM.
    for group in (dates, weekdays):
        if len(group) >= 2:
            ordered = sorted(group, key=lambda m: m.start())
            for prev, nxt in zip(ordered, ordered[1:]):
                if not _LIST_GAP_RE.fullmatch(low[prev.end():nxt.start()]):
                    return None
    if len({m.group(0) for m in dayrefs}) > 1:
        return None

    strong_anchor = bool(rels or times or dates or (is_lunar and lunar_date))
    weak_anchor = bool(weekdays or dayrefs or repeats)
    if not strong_anchor and not weak_anchor:
        return None
    keyword_time = None
    for kw_re, kw_time in dct.keyword_rules:
        if kw_re.search(original_low):
            keyword_time = kw_time
            break

    # ---------- nội dung ----------
    chars = list(buf.orig)
    for a, b in spans:
        for i in range(a, b):
            chars[i] = ""
        chars[a] = _MARK
    message = _clean_message("".join(chars))
    if not message or not re.search(r"\w", message):
        return None
    # Nội dung còn sót cụm giống giờ (vd '8h toi' không dấu) → không chắc, để LLM xử lý
    if _RESIDUAL_TIME_RE.search(message.lower()):
        return None

    # ---------- lặp ----------
    repeat_type = "none"
    if repeats:
        r = repeats[0]
        if r.group(2):
            n = int(r.group(2))
            if n < 1:
                return None
            repeat_type = f"every_{n}{_UNIT_CODE[r.group(3)]}"
        else:
            repeat_type = _REPEAT_CODE[r.group(1)]

    # ---------- giờ ----------
    auto_time = False
    if distinct_times:
        hour, minute = distinct_times[0]
        shift = (period or {}).get("hour_shift") if period else None
        if shift:
            lo, hi = shift["add12_when_hour_in"]
            if lo <= hour <= hi:
                hour += 12
    elif period:
        hour, minute = map(int, period["default_time"].split(":"))
        auto_time = True
    elif keyword_time:
        hour, minute = map(int, keyword_time.split(":"))
        auto_time = True
    else:
        hour = minute = None
        auto_time = True

    # ---------- âm lịch ----------
    if is_lunar:
        if not lunar_date:
            return None
        h, mi = (hour, minute) if hour is not None else (9, 0)
        rep = _repeat_words(repeat_type)
        std = f"{message} lúc {h:02d}:{mi:02d} ngày {lunar_date[0]:02d}/{lunar_date[1]:02d} âm lịch"
        if rep:
            std += f" {rep}"
        return DictionaryResult(items=[], standard_syntax=std, is_lunar=True, auto_time=auto_time)

    # ---------- dương lịch ----------
    if rels:
        r = rels[0]
        n = int(r.group(1))
        delta = timedelta(minutes=n) if r.group(2) == "phút" else timedelta(hours=n)
        dt = now + delta
        return _result([(message, dt, repeat_type)], auto_time=False)

    def _at(d: date, h: int, mi: int) -> datetime:
        return datetime(d.year, d.month, d.day, h, mi)

    def _smart_default(d: date, explicit_today: bool) -> datetime:
        """Không ghi giờ → 09:00 sáng. Hôm nay đã qua 9h → 09:00 sáng mai,
        trừ khi người dùng ghi rõ hôm nay (vẫn nhắc trong ngày: 16:00, sau 16h thì 20:00)."""
        if d != now.date() or now.hour < 9:
            return _at(d, 9, 0)
        if explicit_today:
            if now.hour < 16:
                return _at(d, 16, 0)
            if now.hour < 20:
                return _at(d, 20, 0)
        return _at(d + timedelta(days=1), 9, 0)

    def _build(d: date, roll_days: int, explicit_today=False) -> datetime:
        if hour is None:
            return _smart_default(d, explicit_today)
        dt = _at(d, hour, minute)
        if roll_days and dt <= now:
            dt += timedelta(days=roll_days)
        return dt

    items = []
    if dates:
        if len(dates) >= 2 and weekdays:
            return None
        for m in dates:
            d = _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            if not d:
                return None
            items.append((message, _build(d, 0, explicit_today=(d == now.date())), repeat_type))
    elif dayrefs:
        ref = dayrefs[0].group(1)
        d = now.date() + timedelta(days=1 if ref == "mai" else 0)
        items.append((message, _build(d, 0, explicit_today=(ref == "hôm nay")), repeat_type))
    elif weekdays:
        monday = now.date() - timedelta(days=now.date().weekday())
        seen = set()
        for m in weekdays:
            key = m.group(0)
            if key in seen:
                continue
            seen.add(key)
            wd = _weekday_index(m.group(1))
            ref = m.group(2)
            if ref == "tuần này":
                d = monday + timedelta(days=wd)
                items.append((message, _build(d, 0, explicit_today=(d == now.date())), repeat_type))
            elif ref == "tuần sau":
                items.append((message, _build(monday + timedelta(days=7 + wd), 0), repeat_type))
            else:
                d = monday + timedelta(days=wd)
                if d < now.date():
                    d += timedelta(days=7)
                # Thứ trùng hôm nay mà không ghi giờ → hiểu là hôm nay; nếu đã quá muộn trong ngày
                # thì sang cùng thứ tuần sau (không được nhảy sang một ngày khác thứ)
                dt = _build(d, 7, explicit_today=(d == now.date()))
                if dt.date() != d and dt.weekday() != wd:
                    dt = _at(d + timedelta(days=7), 9, 0)
                items.append((message, dt, repeat_type))
    else:
        items.append((message, _build(now.date(), 1), repeat_type))

    if len(items) == 1:
        m, dt, r = items[0]
        items = [(m, _bare_hour_pm(analysis, dct, dt, r, now, text), r)]
    items.sort(key=lambda x: x[1])
    return _result(items, auto_time=auto_time)


def standard_syntax_for(msg: str, dt: datetime, rtype) -> str:
    """Cú pháp chuẩn của bot cho 1 lịch dương: '<msg> lúc HH:MM ngày DD/MM/YYYY [lặp]'.
    Đây là hợp đồng giữa Dictionary và Rule: Rule (parse_message) là nơi DUY NHẤT tính datetime."""
    std = f"{msg} lúc {dt:%H:%M} ngày {dt:%d/%m/%Y}"
    rep = _repeat_words(rtype) if rtype else ""
    if rep:
        std += f" {rep}"
    return std


def _result(items, auto_time: bool) -> DictionaryResult:
    syntaxes = [standard_syntax_for(m, dt, r) for m, dt, r in items]
    return DictionaryResult(items=items, standard_syntax=syntaxes[0], is_lunar=False,
                            auto_time=auto_time, syntaxes=syntaxes)
