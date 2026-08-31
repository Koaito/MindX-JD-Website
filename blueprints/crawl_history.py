"""Route/context cho tab "Lịch sử" ở trang "Vận hành dữ liệu" (08/2026,
xem lịch sử trao đổi "tách 2 bảng lịch sử ra tab riêng"). Trước đây 2
bảng lịch sử ("Lịch sử crawl" / "Lịch sử bảo trì") nằm CUỐI tab "Crawl
dữ liệu" / "Bảo trì dữ liệu" tương ứng (Khu C, xem
_crawl_tab.html/_maintenance_tab.html) — giờ dồn về 1 tab RIÊNG (kế bên
"Bảo trì dữ liệu") để tra cứu lịch sử không phải cuộn qua Khu A/B (form
kích hoạt + log live) của tab kích hoạt. VẪN GIỮ 2 BẢNG TÁCH BIỆT, chú
thích rõ bảng nào của crawl / bảng nào của bảo trì — schema khác nhau
(crawl_runs theo nguồn/ngành, maintenance_runs theo job_type), không
gộp được mà cũng không nên gộp (dễ nhầm lẫn).

CHỈ ĐỌC — không có route/form trigger nào ở đây, giống tab "status"
(crawl_status.py) — import Ở ĐẦU crawl.py được, KHÔNG cần import trễ
cuối file như crawl_maintenance.py (file đó có route thật, phải tránh
import vòng).

2 bảng phân trang ĐỘC LẬP NHAU (khác biệt CHỦ Ý so với per_page=30 dùng
chung toàn app trước đây, xem helpers.py::_paginate_args): mỗi bảng có
tên query-param riêng — "page" cho lịch sử crawl, "m_page" cho lịch sử
bảo trì — để lật trang bảng này KHÔNG làm bảng kia nhảy về trang 1.
per_page cố định 6 (yêu cầu riêng của tab này, không đụng tới per_page
30 các nơi khác đang dùng)."""

import math

from flask import request

import backend_auth
import crawler_client as db_data
from backend_auth import BackendAuthError
from crawler_client import CrawlerAPIError
from helpers import _auth_tokens_from_session, _call_authed

# Yêu cầu riêng của tab này (khác 30 mặc định ở _paginate_args) — mỗi
# bảng chỉ hiện 6 dòng/trang cho gọn, vì đây là trang TRA CỨU lịch sử,
# không phải nơi thao tác chính.
_HISTORY_PER_PAGE = 6


def _page_arg(param_name):
    """Đọc số trang từ ĐÚNG query-param được truyền vào — khác
    helpers.py::_paginate_args (luôn đọc cứng "page") vì tab này có 2
    bảng, mỗi bảng 1 tên param riêng (xem docstring đầu file)."""
    try:
        page = int(request.args.get(param_name, 1))
    except (TypeError, ValueError):
        page = 1
    return max(page, 1)


def _history_tab_context() -> dict:
    """Build TOÀN BỘ context cho tab='history' — gọi từ
    blueprints/crawl.py::index() khi tab=history, mirror cách
    _maintenance_tab_context() (crawl_maintenance.py) tách hàm riêng để
    index() không phải biết chi tiết bên trong."""

    # access_token lấy 1 lần, dùng chung cho cả 2 bảng (2 lời gọi API
    # độc lập bên dưới, không cần song song hoá bằng _pool — trang tra
    # cứu lịch sử không cần nhanh bằng trang kích hoạt).
    access_token, _refresh_token = _auth_tokens_from_session()

    # Dropdown "người bấm" — DÙNG CHUNG cho cả 2 bộ lọc (chỉ admin bấm
    # được cả crawl lẫn bảo trì, xem _SOURCE_LABELS/db_data ở 2 tab kia)
    # — chỉ gọi list_users() 1 LẦN thay vì 2 lần lặp lại như trước đây
    # (mỗi tab tự gọi riêng vì độc lập nhau, tab này gộp lại được vì
    # cùng hiện trên 1 trang).
    try:
        all_users = backend_auth.list_users(access_token)
        admin_members = [u for u in all_users if u.get("role") == "admin"]
    except BackendAuthError as exc:
        admin_members = []
        _flash_once(str(exc))

    # ---------------- Bảng 1: Lịch sử crawl (crawl_runs) ----------------
    # Import trễ (KHÔNG để đầu file) — lấy _SOURCE_LABELS đã khai ở
    # blueprints/crawl.py, tránh định nghĩa lại 1 bản riêng ở đây rồi lệch
    # nhau khi có nguồn mới. An toàn import trễ vì hàm này chỉ chạy lúc
    # request thật tới (module crawl.py lúc đó đã load xong).
    from blueprints.crawl import _SOURCE_LABELS

    f_source = request.args.get("source", "")
    f_status = request.args.get("status", "")
    f_triggered_by = request.args.get("triggered_by", "")
    page = _page_arg("page")

    try:
        sources = db_data.get_sources()
    except CrawlerAPIError as exc:
        sources = {}
        _flash_once(str(exc))

    category_labels = {
        f"{src}:{cat}": label
        for src, cats in sources.items() for cat, label in cats.items()
    }

    try:
        offset = (page - 1) * _HISTORY_PER_PAGE
        result = _call_authed(
            db_data.list_crawl_runs, source=f_source, status=f_status,
            triggered_by=f_triggered_by, limit=_HISTORY_PER_PAGE, offset=offset,
        )
        crawl_runs = result["items"]
        crawl_total = result["total"]
        crawl_total_pages = max(1, math.ceil(crawl_total / _HISTORY_PER_PAGE))
        page = min(page, crawl_total_pages)
    except CrawlerAPIError as exc:
        _flash_once(str(exc))
        crawl_runs, crawl_total, crawl_total_pages, page = [], 0, 1, 1

    # ------------- Bảng 2: Lịch sử bảo trì (maintenance_runs) -------------
    f_job_type = request.args.get("m_job_type", "")
    f_m_status = request.args.get("m_status", "")
    f_m_triggered_by = request.args.get("m_triggered_by", "")
    m_page = _page_arg("m_page")

    try:
        m_offset = (m_page - 1) * _HISTORY_PER_PAGE
        m_result = _call_authed(
            db_data.list_maintenance_runs, job_type=f_job_type, status=f_m_status,
            triggered_by=f_m_triggered_by, limit=_HISTORY_PER_PAGE, offset=m_offset,
        )
        maint_runs = m_result["items"]
        maint_total = m_result["total"]
        maint_total_pages = max(1, math.ceil(maint_total / _HISTORY_PER_PAGE))
        m_page = min(m_page, maint_total_pages)
    except CrawlerAPIError as exc:
        _flash_once(str(exc))
        maint_runs, maint_total, maint_total_pages, m_page = [], 0, 1, 1

    # ---------------- pagination_filters — GIỮ trạng thái bảng KIA ----------------
    # Bấm "trang sau" ở bảng crawl chỉ nên đổi "page", KHÔNG được làm
    # bảng bảo trì nhảy về trang 1 — nên link phân trang của bảng này
    # phải mang theo CẢ bộ lọc + trang HIỆN TẠI của bảng kia (và ngược
    # lại). "page"/"m_page" của chính bảng đang phân trang KHÔNG nằm
    # trong dict này (url_for truyền riêng page=page-1/page+1 ở template).
    crawl_filters = {"source": f_source, "status": f_status, "triggered_by": f_triggered_by}
    maint_filters = {"m_job_type": f_job_type, "m_status": f_m_status, "m_triggered_by": f_m_triggered_by}

    pagination_filters_crawl = {
        k: v for k, v in {**crawl_filters, **maint_filters, "m_page": m_page}.items() if v
    }
    pagination_filters_maint = {
        k: v for k, v in {**maint_filters, **crawl_filters, "page": page}.items() if v
    }

    return {
        "history_per_page": _HISTORY_PER_PAGE,
        "admin_members": admin_members,
        # ---- Bảng 1: Crawl ----
        "source_labels": _SOURCE_LABELS,
        "category_labels": category_labels,
        "crawl_runs": crawl_runs, "crawl_total_runs": crawl_total,
        "crawl_page": page, "crawl_total_pages": crawl_total_pages,
        "crawl_status_labels": db_data.CRAWL_STATUS_LABELS,
        "crawl_stat_labels": db_data.CRAWL_STAT_LABELS,
        "crawl_filters": {"source": f_source, "status": f_status, "triggered_by": f_triggered_by},
        "pagination_filters_crawl": pagination_filters_crawl,
        # ---- Bảng 2: Bảo trì ----
        "maintenance_jobs": db_data.MAINTENANCE_JOBS,
        "job_labels": db_data.MAINTENANCE_JOB_LABELS,
        "maint_stat_labels": db_data.MAINTENANCE_STAT_LABELS,
        "maint_runs": maint_runs, "maint_total_runs": maint_total,
        "maint_page": m_page, "maint_total_pages": maint_total_pages,
        "maint_status_labels": db_data.MAINTENANCE_STATUS_LABELS,
        "maint_filters": {"job_type": f_job_type, "status": f_m_status, "triggered_by": f_m_triggered_by},
        "pagination_filters_maint": pagination_filters_maint,
    }


def _flash_once(message):
    """flash() lỗi — tách hàm nhỏ chỉ để 2 khối try/except ở trên gọi 1
    dòng thay vì import flask.flash lặp lại nhiều chỗ, KHÔNG có logic gì
    đặc biệt khác flash() thường."""
    from flask import flash
    flash(message, "error")
