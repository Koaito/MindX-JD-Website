"""Helper functions dùng chung toàn app (session token, phân trang, ngày
tháng...).

LƯU Ý QUAN TRỌNG — lý do file này tồn tại:
Trước khi tách blueprint, các hàm dưới đây (đặc biệt `_call_authed` và
`_paginate_args`) bị COPY-PASTE thủ công vào 10 file blueprint khác
nhau. Trong lúc copy, 2 blueprint (`activity_logs.py`,
`data_management.py`) bị dán nhầm 1 bản `_call_authed` CŨ, ĐƠN GIẢN HƠN
— không có logic tự refresh token khi access token hết hạn (401). Hậu
quả: trang Activity Logs và Data Management sẽ crash 500 (lỗi
CrawlerAPIError không được bắt) sau ~30 phút đăng nhập, trong khi các
trang khác (jobs/companies/contacts) vẫn tự refresh êm ru. Đây là 1 bug
ẩn, khó phát hiện vì chỉ xảy ra sau khi access token hết hạn.

Gom về đây để chỉ có DUY NHẤT 1 bản mỗi hàm — sửa 1 nơi, có hiệu lực ở
toàn bộ app.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from flask import request, session
from markupsafe import Markup, escape

import backend_auth
from backend_auth import BackendAuthError
from crawler_client import CrawlerAPIError

# ---------------------------------------------------------------------------
# Giờ Việt Nam (thêm 08/2026 — báo lỗi "giờ trên web bị lệch")
# ---------------------------------------------------------------------------
# GỐC RỄ: server chạy trên Vercel, mặc định giờ hệ thống là UTC (không có
# biến môi trường TZ nào set khác) — trong khi TOÀN BỘ `datetime.now()`
# trong app (dashboard.py tính "hôm nay", format_date() hiển thị giờ chạy
# crawl/lịch sử thao tác/lần đăng nhập cuối...) trước giờ coi giờ server
# = giờ hiển thị cho người dùng, không hề quy đổi -> mọi mốc giờ hiển thị
# ra bị LỆCH ĐÚNG 7 TIẾNG so với giờ Việt Nam thật (VD: chạy lúc 21:36 giờ
# VN thì hệ thống lưu/trả về 14:36 UTC, rồi hiển thị thẳng "14:36" luôn
# thay vì quy đổi lại 21:36). Ảnh hưởng RÕ NHẤT vào khung 00:00-07:00 giờ
# VN: lúc đó server UTC vẫn còn là NGÀY HÔM TRƯỚC, nên các phép tính dựa
# vào "hôm nay" (đếm ngược hạn nộp job, thống kê theo tháng ở dashboard...)
# bị lùi sai 1 ngày trong đúng khung giờ đó.
#
# Cách dùng: MỌI chỗ cần biết "bây giờ"/"hôm nay" theo giờ người dùng nhìn
# thấy phải gọi now_vn() (KHÔNG dùng datetime.now() trần) — xem
# blueprints/dashboard.py. format_date() bên dưới tự quy đổi sẵn cho các
# giá trị datetime lấy từ backend (created_at/started_at/last_login_at...).
VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def now_vn():
    """"Bây giờ" theo giờ Việt Nam (UTC+7) — dùng thay cho datetime.now()
    trần ở MỌI nơi cần so sánh/hiển thị theo ngày giờ người dùng nhìn thấy.
    Xem giải thích gốc rễ ở khối comment ngay phía trên."""
    return datetime.now(VN_TZ)


# ---------------------------------------------------------------------------
# Session token helpers
# ---------------------------------------------------------------------------

def _store_auth_tokens(access_token, refresh_token):
    session["access_token"] = access_token
    session["refresh_token"] = refresh_token


def _clear_auth_tokens():
    session.pop("access_token", None)
    session.pop("refresh_token", None)


def _auth_tokens_from_session():
    return session.get("access_token"), session.get("refresh_token")


def _call_authed(fn, *args, **kwargs):
    """Gọi 1 hàm crawler_client với access token trong session. Nếu backend
    trả 401 (access token hết hạn), tự refresh rồi gọi lại 1 lần."""
    access_token, refresh_token = _auth_tokens_from_session()
    try:
        return fn(access_token, *args, **kwargs)
    except CrawlerAPIError as exc:
        if exc.status_code != 401 or not refresh_token:
            raise
        try:
            pair = backend_auth.refresh(refresh_token)
        except BackendAuthError:
            _clear_auth_tokens()
            raise CrawlerAPIError(
                "Phiên đăng nhập đã hết hạn — vui lòng đăng nhập lại.",
                status_code=401,
            )
        _store_auth_tokens(pair["access_token"], pair["refresh_token"])
        return fn(pair["access_token"], *args, **kwargs)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def _paginate_args(default_per_page):
    try:
        page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    page = max(page, 1)
    return page, default_per_page


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_any_date(value):
    if not value or not isinstance(value, str):
        return None
    text = value.replace("Z", "+00:00")
    for parser in (
        lambda s: datetime.fromisoformat(s),
        lambda s: datetime.strptime(s, "%Y-%m-%d"),
    ):
        try:
            return parser(text).date()
        except ValueError:
            continue
    return None


def format_date(value, fmt="%d/%m/%Y"):
    if not value:
        return "—"
    if isinstance(value, str):
        text = value.replace("Z", "+00:00")
        parsed = None
        for parser in (
            lambda s: datetime.fromisoformat(s),
            lambda s: datetime.strptime(s, "%Y-%m-%d"),
        ):
            try:
                parsed = parser(text)
                break
            except ValueError:
                continue
        if parsed is None:
            return value
    else:
        parsed = value

    # Quy đổi sang giờ VN trước khi format (thêm 08/2026, xem giải thích ở
    # now_vn() phía trên). Backend trả về giờ dạng UTC (có hậu tố "Z" —
    # xem .replace("Z", "+00:00") ở trên): parser sẽ tạo ra datetime CÓ
    # tzinfo=UTC cho các chuỗi này -> quy đổi thẳng sang VN_TZ. Với
    # datetime/date KHÔNG có tzinfo (naive — vd chuỗi "YYYY-MM-DD" không
    # kèm giờ, hoặc value truyền vào sẵn là đối tượng date/datetime naive
    # từ nơi khác), coi như ĐÃ Ở ĐÚNG giờ cần hiển thị (không có "giờ" để
    # lệch, hoặc caller tự chịu trách nhiệm) — không tự ý cộng/trừ giờ,
    # tránh đoán sai làm lệch thêm.
    if isinstance(parsed, datetime) and parsed.tzinfo is not None:
        parsed = parsed.astimezone(VN_TZ)

    try:
        return parsed.strftime(fmt)
    except AttributeError:
        return "—"


def _jobs_by_month(jobs, date_field, months_back=6, only_past=False):
    today = now_vn().date()
    month_keys = []
    y, m = today.year, today.month
    for _ in range(months_back):
        month_keys.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    month_keys.reverse()

    counts_by_key = {key: 0 for key in month_keys}
    for job in jobs:
        d = _parse_any_date(job.get(date_field))
        if d is None:
            continue
        if only_past and d >= today:
            continue
        key = (d.year, d.month)
        if key in counts_by_key:
            counts_by_key[key] += 1

    labels = ["%02d/%d" % (m, y) for (y, m) in month_keys]
    counts = [counts_by_key[key] for key in month_keys]
    return labels, counts


# ---------------------------------------------------------------------------
# Industry badge color mapping
# ---------------------------------------------------------------------------
# Sửa 08/2026 — trước đây .ticket-industry được tô màu bằng
# `ind-{{ loop.index0 % 3 }}` (xem git blame templates/index.html cũ):
# màu chỉ phụ thuộc VỊ TRÍ của card trong danh sách (card thứ 1/4/7...
# luôn ind-0, thứ 2/5/8... luôn ind-1...), KHÔNG phụ thuộc job.industry
# thật sự là gì. Hậu quả: cùng ngành "Code" nhưng job này màu xanh, job
# kia màu cam tuỳ nó rơi vào ô nào trong lưới -> người dùng nhìn màu
# không đoán được ngành, mất hết tác dụng của việc tô màu.
#
# INDUSTRY_CLASS_MAP dưới đây gán CỐ ĐỊNH 1 class CSS cho từng giá trị
# industry (constants.INDUSTRIES — đúng 6 giá trị, khớp matching_industry
# bên Scrap JD/config.py, xem JOB_CATEGORIES). Style thật (màu chữ/nền)
# nằm ở public/css/04-job-cards.css (.ind-code, .ind-business-analysis...).
#
# industry_class() dùng làm Jinja filter (xem app.py) thay cho
# `loop.index0 % 3` ở mọi nơi render .ticket-industry (templates/
# index.html, saved_jobs.html, staff_activity_detail.html).
INDUSTRY_CLASS_MAP = {
    "Code": "ind-code",
    "Business Analysis": "ind-business-analysis",
    "Data Analysis": "ind-data-analysis",
    "Data Engineer": "ind-data-engineer",
    "Data Scientist": "ind-data-scientist",
    "UI/UX Design": "ind-ui-ux-design",
}

# Fallback cho industry lạ (không có trong 6 giá trị chuẩn — vd dữ liệu
# cũ/nhập tay lệch chính tả): tô xám trung tính thay vì crash hoặc rơi
# vào 1 trong 6 màu đã có (gây hiểu lầm là đúng ngành đó).
_INDUSTRY_CLASS_FALLBACK = "ind-other"


def industry_class(value):
    """Trả về class CSS cố định (đã kèm tiền tố "ind-...") cho 1 giá trị
    industry. Dùng trực tiếp trong template:
    `class="ticket-industry {{ job.industry|industry_class }}"`."""
    return INDUSTRY_CLASS_MAP.get(value, _INDUSTRY_CLASS_FALLBACK)


# ---------------------------------------------------------------------------
# Template filters
# ---------------------------------------------------------------------------

def to_bullets(value):
    if not value:
        return ""
    lines = [ln.strip(" \t-•*") for ln in value.splitlines()]
    lines = [ln for ln in lines if ln]
    if len(lines) <= 1:
        return Markup("<p>{}</p>").format(value)
    items = "".join(f"<li>{escape(ln)}</li>" for ln in lines)
    return Markup("<ul class=\"jd-bullets\">{}</ul>").format(Markup(items))
