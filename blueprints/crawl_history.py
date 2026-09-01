"""Context cho tab "Lịch sử vận hành" ở trang "Vận hành dữ liệu" (mục
sidebar thứ 4, thêm 08/2026, xem lịch sử trao đổi "tách 2 bảng log
crawl/bảo trì sang mục thứ 4 riêng, không gộp"). Gộp 2 bảng lịch sử
ĐỘC LẬP (crawl + bảo trì, TRƯỚC ĐÂY là Khu C của tab 'crawl'/
'maintenance') xếp DỌC trên cùng 1 trang, mỗi bảng phân trang RIÊNG.

TÁCH FILE RIÊNG (khác gộp thẳng vào crawl.py, cùng lý do
crawl_maintenance.py đã tách) để crawl.py không phình to quá. KHÔNG có
route/form trigger nào ở đây (chỉ 1 hàm build context, CHỈ ĐỌC — giống
crawl_status.py hơn crawl_maintenance.py) nên KHÔNG cần dùng chung
`crawl_bp`. NHƯNG khác crawl_status.py ở chỗ: _history_tab_context()
CẦN _source_active_state()/_SOURCE_LABELS từ blueprints.crawl (poll
"đang chạy" theo từng nguồn, tái dùng nguyên logsong song hoá đã có ở
index()) — import NGƯỢC này vẫn phải làm TRỄ (bên trong hàm, không ở
đầu file) vì blueprints/crawl.py import module này ở TRONG index() khi
tab='history' (không phải ở đầu file), cùng nguyên tắc với
crawl_maintenance.py: nếu để 2 file import lẫn nhau ở ĐẦU file, module
nào load trước sẽ thấy module kia CHƯA tồn tại -> ImportError.

Nguồn dữ liệu: bảng crawl_runs + maintenance_runs (Postgres, xem
sql/migration_add_crawl_runs.sql, sql/migration_add_maintenance_runs.sql
phía backend)."""

import math

from flask import flash, request

import backend_auth
import crawler_client as db_data
from backend_auth import BackendAuthError
from crawler_client import CrawlerAPIError
from helpers import _auth_tokens_from_session, _io_pool as _pool, _paginate_args_named, _store_auth_tokens


def _history_tab_context() -> dict:
    """Build context cho tab 'history' (mục sidebar thứ 4 "Lịch sử vận
    hành", thêm 08/2026):
      - Widget "Đang chạy" TĨNH (không JS polling — khác 2 tab
        crawl/maintenance) cho CẢ crawl LẪN bảo trì cùng lúc (chốt
        08/2026: khác quyết định trước đó "mỗi widget chỉ hiện job của
        tab đang xem" ở _crawl_tab.html/_maintenance_tab.html — tab
        này CỐ Ý gộp cả 2 loại vì đây là nơi duy nhất xem được toàn
        cảnh). ĐÃ CHỐT: bảng/widget đứng yên nếu 1 lượt vừa xong ngay
        lúc đang xem tab này — người dùng tự tải lại trang để thấy,
        khớp hành vi tab 'status' (tab đó cũng thuần đọc, không poll).
      - Lịch sử crawl (list_crawl_runs) — TRƯỚC ĐÂY nằm ở Khu C của tab
        'crawl' (blueprints/crawl.py::index()).
      - Lịch sử bảo trì (list_maintenance_runs) — TRƯỚC ĐÂY nằm ở Khu C
        của tab 'maintenance', xem
        blueprints/crawl_maintenance.py::_maintenance_history_context_raw().

    per_page=6 CHO CẢ 2 BẢNG (khác 30 trước đây) — theo đúng yêu cầu
    "giống phân trang bên web đang dùng, mỗi trang 6 log" khi chuyển
    sang trang riêng dễ nhìn hơn, không còn phải cuộn qua Khu A/B trước
    mới tới bảng lịch sử như lúc còn nằm chung tab.

    2 bảng dùng 2 TÊN QUERY PARAM khác nhau cho số trang
    (crawl_page/maint_page, qua _paginate_args_named) — nếu dùng chung
    "page", bấm "Trang sau" ở bảng này sẽ vô tình đổi luôn trang bảng
    kia (2 form GET riêng cùng ghi vào 1 param, cái sau đè cái trước
    trên URL).

    REFRESH TOKEN — GỌI 1 LẦN CHO CẢ ĐỢT, KHÔNG ĐỂ TỪNG LỆNH TỰ REFRESH
    RIÊNG: backend_auth.refresh() XOAY VÒNG refresh_token (mỗi lần gọi
    vô hiệu hoá refresh_token cũ, trả cặp mới) — xem docstring
    backend_auth.refresh(). Trang này cần gọi backend NHIỀU lần (bảng
    lịch sử crawl, list_users, bảng lịch sử bảo trì, poll đang chạy
    crawl theo từng nguồn, poll đang chạy bảo trì). Nếu để mỗi lệnh tự
    refresh độc lập bằng refresh_token ĐỌC TỪ SESSION LÚC ĐẦU (không
    cập nhật biến cục bộ sau lần refresh đầu tiên), lệnh thứ 2 trở đi
    sẽ refresh bằng refresh_token ĐÃ BỊ XOAY (vô hiệu) → backend coi là
    reuse token cũ → thu hồi session → đúng chuỗi lỗi "đang chạy job
    thì bị kick" đã từng điều tra (xem lịch sử trao đổi "hay bị kick
    khỏi acc khi chạy vài script bên vận hành dữ liệu"). Giải pháp: gộp
    TOÀN BỘ lệnh gọi vào 1 "wave" (_run_wave() bên dưới), kiểm tra 401
    GỘP trên toàn bộ, refresh ĐÚNG 1 LẦN nếu có, rồi gọi lại TOÀN BỘ
    với token mới — đúng pattern
    blueprints/crawl.py::index()::_run_sources() đã dùng cho vòng poll
    per-source. Vòng poll per-source (N nguồn) VẪN chạy song song qua
    _pool bên trong wave (đủ nhẹ, không đáng lo dính lại lỗi refresh-
    nhiều-lần vì cả N future đều dùng CHUNG 1 token truyền vào — refresh
    chỉ xảy ra ở OUTER wave, không ở trong worker thread)."""
    # Import trễ (blueprints.crawl_history import ngược crawl.py, xem
    # docstring đầu file) — cần _source_active_state()/_SOURCE_LABELS
    # để poll "đang chạy" theo từng nguồn, tái dùng nguyên logic song
    # song hoá index() đã có, không viết lại.
    from blueprints.crawl import _SOURCE_LABELS, _source_active_state
    # Import trễ tương tự cho phía bảo trì (cùng lý do
    # crawl_maintenance.py phải import ngược crawl_bp — dù ở đây không
    # cần crawl_bp, 2 hàm dưới đây cũng chỉ tồn tại sau khi
    # crawl_maintenance module đã load xong, và crawl_maintenance.py
    # LẠI import blueprints.crawl ở đầu file nó -> vẫn nên trễ để tránh
    # phụ thuộc thứ tự import mong manh giữa 3 file).
    from blueprints.crawl_maintenance import (
        _active_maintenance_runs_raw, _maintenance_history_context_raw,
    )

    f_source = request.args.get("source", "")
    f_status = request.args.get("status", "")
    f_triggered_by = request.args.get("triggered_by", "")
    crawl_page, crawl_per_page = _paginate_args_named("crawl_page", 6)
    crawl_offset = (crawl_page - 1) * crawl_per_page

    maint_page, maint_per_page = _paginate_args_named("maint_page", 6)
    m_job_type = request.args.get("m_job_type", "")
    m_status = request.args.get("m_status", "")
    m_triggered_by = request.args.get("m_triggered_by", "")
    maint_offset = (maint_page - 1) * maint_per_page

    try:
        sources = db_data.get_sources()
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        sources = {}
    category_labels = {
        f"{src}:{cat}": label
        for src, cats in sources.items() for cat, label in cats.items()
    }

    def _run_wave(token):
        """1 wave = TOÀN BỘ lệnh gọi backend cần cho tab này, cùng 1
        token. Vòng poll per-source (N nguồn) chạy song song qua _pool
        bên trong wave này — an toàn vì refresh chỉ xảy ra ở NGOÀI wave
        (xem nơi gọi _run_wave() bên dưới), worker thread chỉ đọc
        token truyền tay, không tự refresh gì cả (giống hệt cách
        blueprints/crawl.py::index() dùng _source_active_state())."""
        crawl_runs_result = db_data.list_crawl_runs(
            token, source=f_source, status=f_status, triggered_by=f_triggered_by,
            limit=crawl_per_page, offset=crawl_offset,
        )
        all_users = backend_auth.list_users(token)
        maint_runs_result = db_data.list_maintenance_runs(
            token, job_type=m_job_type, status=m_status, triggered_by=m_triggered_by,
            limit=maint_per_page, offset=maint_offset,
        )
        source_futures = {src: _pool.submit(_source_active_state, src, token) for src in sources}
        source_results = {src: source_futures[src].result() for src in sources}
        active_maint_runs = _active_maintenance_runs_raw(token)
        return crawl_runs_result, all_users, maint_runs_result, source_results, active_maint_runs

    access_token, refresh_token = _auth_tokens_from_session()
    wave_error = None
    result = None
    try:
        result = _run_wave(access_token)
    except (CrawlerAPIError, BackendAuthError) as exc:
        status_code = getattr(exc, "status_code", None)
        if status_code == 401 and refresh_token:
            try:
                pair = backend_auth.refresh(refresh_token)
            except BackendAuthError:
                pair = None
            if pair:
                _store_auth_tokens(pair["access_token"], pair["refresh_token"])
                try:
                    result = _run_wave(pair["access_token"])
                except (CrawlerAPIError, BackendAuthError) as exc2:
                    wave_error = exc2
            else:
                wave_error = exc
        else:
            wave_error = exc

    if wave_error:
        flash(str(wave_error), "error")
        crawl_runs_result = all_users = maint_runs_result = None
        source_results = {}
        active_maint_runs = {}
    else:
        crawl_runs_result, all_users, maint_runs_result, source_results, active_maint_runs = result

    if wave_error:
        crawl_runs, crawl_total_runs, crawl_total_pages, crawl_page = [], 0, 1, 1
    else:
        crawl_runs = crawl_runs_result["items"]
        crawl_total_runs = crawl_runs_result["total"]
        crawl_total_pages = max(1, math.ceil(crawl_total_runs / crawl_per_page))
        crawl_page = min(crawl_page, crawl_total_pages)

    crawl_admin_members = [] if wave_error else [u for u in all_users if u.get("role") == "admin"]

    # Widget "Đang chạy" (crawl) — TĨNH, không polling (xem docstring
    # hàm này). active_batches CẦN cho card có batch_id (hiện checklist
    # N category) — mirror y hệt cách index() dựng active_runs/
    # active_batches từ source_results, chỉ khác không refresh lại ở
    # đây (refresh đã xử lý xong ở wave trên).
    active_runs = {}
    active_batches = {}
    for source in sources:
        _src, run, batch, error = source_results.get(source, (source, None, None, None))
        if error:
            flash(str(error), "error")
        if run:
            active_runs[source] = run
            if batch:
                active_batches[source] = batch

    # _maintenance_history_context_raw() KHÔNG tự gọi backend nữa (nhận
    # thẳng maint_runs_result đã fetch ở _run_wave() trên) — chỉ build
    # phần context còn lại (label, filters...) từ dữ liệu có sẵn.
    maint_ctx = _maintenance_history_context_raw(
        maint_runs_result, all_users if not wave_error else [],
        maint_page, maint_per_page,
        job_type=m_job_type, status=m_status, triggered_by=m_triggered_by,
        had_error=bool(wave_error),
    )

    return {
        "source_labels": _SOURCE_LABELS,
        "category_labels": category_labels,
        "status_labels": db_data.CRAWL_STATUS_LABELS,
        "stat_labels": db_data.CRAWL_STAT_LABELS,
        "active_runs": active_runs, "active_batches": active_batches,
        "active_maintenance_runs": active_maint_runs,
        "job_labels": db_data.MAINTENANCE_JOB_LABELS,
        "crawl_runs": crawl_runs, "crawl_total_runs": crawl_total_runs,
        "crawl_page": crawl_page, "crawl_total_pages": crawl_total_pages,
        "crawl_per_page": crawl_per_page,
        "crawl_admin_members": crawl_admin_members,
        "crawl_filters": {"source": f_source, "status": f_status, "triggered_by": f_triggered_by},
        "crawl_pagination_filters": {k: v for k, v in
                                      {"source": f_source, "status": f_status,
                                       "triggered_by": f_triggered_by}.items() if v},
        # maint_* — trực tiếp từ _maintenance_history_context_raw(), đã đúng
        # tên field cần cho _history_tab.html (xem template).
        "maint_jobs": maint_ctx["maintenance_jobs"],
        "maint_job_labels": maint_ctx["job_labels"],
        "maint_runs": maint_ctx["runs"], "maint_total_runs": maint_ctx["total_runs"],
        "maint_page": maint_ctx["page"], "maint_total_pages": maint_ctx["total_pages"],
        "maint_per_page": maint_ctx["per_page"],
        "maint_status_labels": maint_ctx["status_labels"],
        "maint_admin_members": maint_ctx["admin_members"],
        "maint_filters": maint_ctx["filters"],
        "maint_pagination_filters": maint_ctx["pagination_filters"],
    }
