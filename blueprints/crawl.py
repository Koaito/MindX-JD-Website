"""Crawl blueprint — trang "Vận hành dữ liệu" (08/2026, đổi tên từ
"Crawl dữ liệu" — xem lịch sử trao đổi "1 mục, 2 tab như
data_management.py"). CHỈ admin thấy và dùng được (khớp yêu cầu gốc,
chặt hơn @staff_required cho ss_team đang dùng ở hầu hết trang quản trị
khác) — xem utils/decorators.py::admin_required.

TAB "crawl" (mặc định) — nội dung y hệt trang cũ, dời sang
_crawl_tab.html, KHÔNG đổi logic.
TAB "status" — "Tình trạng dữ liệu" (08/2026): bảng company đang thiếu
field gì/tỉ lệ bao nhiêu, cho admin xem mà KHÔNG cần vào thẳng database
— context build ở blueprints/crawl_status.py (file riêng, CHỈ ĐỌC,
không có route/form trigger nào nên import Ở ĐẦU file này, không như
"maintenance" bên dưới).
TAB "maintenance" — 5 job bảo trì dữ liệu (backfill_company_profiles,
enrich_profile_from_website, enrich_web_info, get_fb_linkedin,
check_expired_jobs), route trigger/status/logs khai ở
blueprints/crawl_maintenance.py (file riêng, CÙNG blueprint object
`crawl_bp` này — import ở CUỐI file để tự đăng ký route, xem dòng
import cuối file).

URL giữ nguyên `/crawl` (không đổi thành `/van-hanh-du-lieu` hay tương
tự) — CHỦ Ý để không phải sửa mọi `url_for('crawl.index')` đang rải rác
(base.html, breadcrumb...) chỉ vì đổi tên hiển thị.

Nguồn dữ liệu: bảng crawl_runs (Postgres, xem
sql/migration_add_crawl_runs.sql phía backend) — thay cho _RUNS (RAM)
cũ, sống bền qua restart server."""

import math

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

import backend_auth
import crawler_client as db_data
from backend_auth import BackendAuthError

# Tab "status" (Tình trạng dữ liệu) CHỈ ĐỌC, không có route riêng nào
# đăng ký vào crawl_bp -> import thẳng ở đầu file được (khác
# blueprints.crawl_maintenance phải import trễ ở cuối file vì file đó
# cần import ngược crawl_bp, xem docstring cuối file này).
from blueprints.crawl_status import _status_tab_context
from crawler_client import CrawlerAPIError
from helpers import _auth_tokens_from_session, _call_authed, _paginate_args_named, _store_auth_tokens, _io_pool as _pool
from utils.decorators import admin_required

crawl_bp = Blueprint("crawl", __name__)

# Nhãn hiển thị cho từng nguồn — KHÔNG lấy từ get_sources() (dict đó chỉ
# có category, không có nhãn nguồn) — giữ khớp tay với các nguồn đã đăng
# ký ở crawl_runner.py phía backend.
#
# 08/2026 — THÊM "careerviet": adapters/careerviet.py phía backend đã
# crawl được từ trước (chạy qua CLI) và giờ đã đăng ký đủ ở cả
# api/crawl_runner.py, api/routers/crawl.py, api/routers/meta.py (GET
# /sources) — xem lịch sử trao đổi. Trang /crawl (index() bên dưới) tự
# lặp qua get_sources() để render card (xem crawl.html, KHÔNG hardcode
# tên nguồn nào ở template) nên chỉ cần thêm đúng 1 dòng nhãn ở đây là
# đủ để card CareerViet xuất hiện.
_SOURCE_LABELS = {"topcv": "TopCV", "vietnamworks": "VietnamWorks", "careerviet": "CareerViet"}

# _pool bên dưới ĐÃ dùng chung 1 ThreadPoolExecutor toàn app (_io_pool ở
# helpers.py, import đổi tên thành _pool ở đầu file) — KHÔNG còn tự tạo
# pool riêng ở đây nữa (SỬA 08/2026, xem lịch sử trao đổi "rà codebase —
# độ linh hoạt/mở rộng"). Trước đây tự tính tay max_workers=6 — vừa phải
# sửa tay 4->6 khi thêm 2 stage mới (list_crawl_runs/list_users, xem
# lịch sử trao đổi "làm cái crawl") — giờ dùng chung pool app-wide,
# không cần rà lại số này mỗi khi thêm nguồn crawl hay thêm lệnh gọi độc
# lập mới ở route nào đó nữa. Xem docstring _io_pool (helpers.py) để
# biết lý do gộp.


def _active_run_for_source(source):
    """Trả dict crawl_run đang 'running' hoặc 'queued' cho 1 nguồn (ưu
    tiên 'running' vì khả năng cao hơn 'queued' đứng lâu), hoặc None nếu
    nguồn đó rảnh. Tối đa 2 lần gọi GET /crawl (KHÔNG gộp được 1 lần vì
    backend chỉ nhận 1 giá trị status/lần gọi, xem
    api/routers/crawl.py::list_crawl_runs) — chấp nhận được vì chỉ chạy
    lúc load trang, cho đúng 2 nguồn (4 lệnh gọi tối đa, không phải vòng
    lặp không giới hạn)."""
    for status in ("running", "queued"):
        result = _call_authed(db_data.list_crawl_runs, source=source, status=status, limit=1)
        if result["items"]:
            return result["items"][0]
    return None


def _source_active_state(source, access_token):
    """Gói TRỌN 2 bước tuần tự cần cho 1 nguồn (lấy run đang chạy, rồi
    NẾU có batch_id thì lấy thêm tiến độ batch) thành 1 hàm — dùng để
    chạy SONG SONG NHIỀU NGUỒN CÙNG LÚC ở index() bên dưới (thêm
    08/2026, xem lịch sử trao đổi "/crawl chậm 4.69s vì gọi tuần tự
    từng nguồn"). 2 bước bên trong 1 nguồn VẪN tuần tự (batch phụ thuộc
    run.batch_id, không tránh được) — chỉ số NGUỒN (hiện 3: TopCV/
    VietnamWorks/CareerViet, xem _SOURCE_LABELS) mới chạy song song với
    nhau.

    access_token: PHẢI lấy sẵn ở main thread (flask.session) TRƯỚC khi
    submit hàm này vào ThreadPoolExecutor — hàm này chạy trên worker
    thread, KHÔNG có Flask request/session context, nên KHÔNG được gọi
    _call_authed()/_auth_tokens_from_session() (đọc session sẽ raise
    "Working outside of request context", và nếu cố refresh token bên
    trong nữa thì càng không an toàn — nhiều thread ghi session cùng
    lúc). Do đó hàm này gọi thẳng db_data.list_crawl_runs()/
    get_crawl_batch_status() với access_token truyền tay, KHÔNG qua
    _call_authed() — nếu access_token đã hết hạn (401), lỗi đó được trả
    về nguyên vẹn cho index() xử lý, index() tự quyết định refresh rồi
    submit lại 1 lượt (xem index() bên dưới), KHÔNG refresh ở đây.

    Trả (source, run, batch, error) thay vì raise/flash trực tiếp —
    nơi gọi (index()) tự flash() lại trên main thread sau khi lấy
    .result()."""
    try:
        run = None
        for status in ("running", "queued"):
            result = db_data.list_crawl_runs(access_token, source=source, status=status, limit=1)
            if result["items"]:
                run = result["items"][0]
                break
    except CrawlerAPIError as exc:
        return source, None, None, exc

    if not run or not run.get("batch_id"):
        return source, run, None, None

    # 08/2026 — nếu run đang chạy của nguồn này thuộc 1 batch (batch_id
    # khác None, xem docstring crawler_client/crawl.py::_normalize_crawl_run),
    # lấy thêm tiến độ TỔNG của batch (checklist đủ N category) để Khu B
    # hiện card "2/6 category xong" thay vì card 1-category cũ. Lỗi ở
    # đây KHÔNG chặn render trang (card vẫn hiện, chỉ thiếu checklist).
    try:
        batch = db_data.get_crawl_batch_status(access_token, run["batch_id"])
    except CrawlerAPIError as exc:
        return source, run, None, exc
    return source, run, batch, None


@crawl_bp.route("/crawl")
@admin_required
def index():
    """Trang chính — 4 mục (?tab=crawl mặc định | ?tab=status |
    ?tab=maintenance | ?tab=history).

    Tab 'crawl': Khu A (kích hoạt), Khu B (đang chạy, tối đa 2 —
    1/nguồn). TỪ 08/2026: Khu C (lịch sử) đã CHUYỂN sang tab 'history'
    riêng (mục sidebar thứ 4 "Lịch sử vận hành") — xem lịch sử trao đổi
    "tách 2 bảng log crawl/bảo trì sang mục thứ 4 riêng, không gộp".

    Tab 'status': bảng company đang thiếu field gì/tỉ lệ bao nhiêu, xem
    docstring _status_tab_context() (blueprints/crawl_status.py).

    Tab 'maintenance': build context riêng ở
    _maintenance_tab_context() (blueprints/crawl_maintenance.py) rồi
    merge vào đây — tách hàm để file này không phình to, KHÔNG tính lại
    context tab đang KHÔNG hiển thị (đỡ gọi API thừa lúc chỉ xem 1 tab).
    TỪ 08/2026: chỉ còn Khu A/B, Khu C cũng đã chuyển sang tab 'history'.

    Tab 'history' (thêm 08/2026): 2 bảng lịch sử (crawl + bảo trì) xếp
    DỌC trên CÙNG 1 trang, mỗi bảng phân trang RIÊNG 6 dòng/trang (2
    query param khác tên: crawl_page/maint_page — xem
    helpers.py::_paginate_args_named và _history_tab_context() bên
    dưới). CỐ Ý không gộp chung 1 bảng — 2 domain khác nhau (crawl nguồn
    ngoài / bảo trì dữ liệu nội bộ), gộp sẽ khó filter/đọc hơn tách."""
    tab = request.args.get("tab", "crawl")
    if tab not in ("crawl", "status", "maintenance", "history"):
        tab = "crawl"

    if tab == "status":
        return render_template("crawl.html", tab=tab, **_status_tab_context())

    if tab == "maintenance":
        # Import trễ (KHÔNG để đầu file) để tránh import vòng: file đó
        # `from blueprints.crawl import crawl_bp`, import ở đầu file
        # này sẽ chạy TRƯỚC KHI crawl_bp được định nghĩa (dòng 21) ->
        # ImportError. Import trễ bên trong hàm chỉ chạy lúc request
        # thật tới, lúc đó module đã load xong hoàn toàn.
        from blueprints.crawl_maintenance import _maintenance_tab_context
        return render_template("crawl.html", tab=tab, **_maintenance_tab_context())

    if tab == "history":
        return render_template("crawl.html", tab=tab, **_history_tab_context())

    # access_token lấy 1 LẦN ở đây (main thread, Flask session context)
    # cho CẢ 2 nhóm việc độc lập bên dưới (per-source poll / list_users)
    # — cùng lý do _source_active_state() không tự gọi
    # _auth_tokens_from_session() (worker thread không có request context).
    access_token, refresh_token = _auth_tokens_from_session()

    f_source = request.args.get("source", "")

    # get_sources() bắn đi NGAY (không phụ thuộc access_token) — độc lập
    # hoàn toàn với các việc bên dưới, nên KHÔNG cần nằm trong
    # _run_wave() (không cần resubmit lại nếu access_token phải refresh
    # — get_sources() không nhận token, refresh không ảnh hưởng gì tới nó).
    sources_future = _pool.submit(db_data.get_sources)

    # Song song hoá vòng lặp per-source (thêm 08/2026, xem lịch sử trao
    # đổi "/crawl chậm 4.69s — cùng nguyên nhân round-trip tuần tự như
    # /companies") — trước đây for source in sources: gọi
    # _active_run_for_source() (+ batch status nếu có) TUẦN TỰ từng
    # nguồn, tổng thời gian = tổng round-trip mọi nguồn. Giờ bắn cả
    # N nguồn cùng lúc qua _pool, tổng thời gian ≈ nguồn CHẬM NHẤT.
    #
    # Nếu access_token hết hạn (401) ở BẤT KỲ nguồn nào, refresh 1 LẦN
    # trên main thread rồi submit lại toàn bộ — refresh token là ghi
    # session, chỉ an toàn làm ở main thread.
    def _run_sources(token):
        futures = {source: _pool.submit(_source_active_state, source, token) for source in sources}
        return {source: futures[source].result() for source in sources}

    try:
        sources = sources_future.result()
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        sources = {}

    active_runs = {}
    active_batches = {}
    source_results = _run_sources(access_token)
    had_401 = any(
        isinstance(error, CrawlerAPIError) and error.status_code == 401
        for _s, _r, _b, error in source_results.values()
    )
    if had_401 and refresh_token:
        try:
            pair = backend_auth.refresh(refresh_token)
        except BackendAuthError:
            pair = None
        if pair:
            _store_auth_tokens(pair["access_token"], pair["refresh_token"])
            source_results = _run_sources(pair["access_token"])

    for source in sources:
        _src, run, batch, error = source_results[source]
        if error:
            flash(str(error), "error")
        if run:
            active_runs[source] = run
            if batch:
                active_batches[source] = batch

    # Nhãn category phẳng "source:category" -> label — dùng CẢ server
    # render (JS Khu B tự thêm dòng khi crawl xong, xem crawl.html
    # script) lẫn tab "history" (bảng lịch sử, xem _history_tab_context())
    # để không phải định nghĩa nhãn 2 lần lệch nhau giữa Jinja và JS.
    category_labels = {
        f"{src}:{cat}": label
        for src, cats in sources.items() for cat, label in cats.items()
    }

    return render_template(
        "crawl.html",
        tab=tab,
        sources=sources, source_labels=_SOURCE_LABELS,
        active_runs=active_runs, active_batches=active_batches, category_labels=category_labels,
        # status_labels/stat_labels: KHÔNG còn dùng để render Khu C ở
        # đây (đã chuyển sang tab "history") nhưng JS Khu B
        # (buildHistoryRow(), xem _crawl_tab.html) vẫn cần 2 biến này để
        # hiện kết quả crawl NGAY TẠI CHỖ khi 1 lượt vừa chạy xong —
        # thiếu 2 biến này JS sẽ lỗi (undefined) lúc build dòng, dù
        # dòng đó cuối cùng không chèn được vào đâu (không còn
        # #crawl-history-tbody trong DOM tab này) vì buildHistoryRow()
        # bị gọi TRƯỚC bước kiểm tra !tbody.
        status_labels=db_data.CRAWL_STATUS_LABELS, stat_labels=db_data.CRAWL_STAT_LABELS,
        filters={"source": f_source},
    )


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
        'crawl' (xem index() phía trên).
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
    với token mới — đúng pattern index()::_run_sources() đã dùng cho
    vòng poll per-source. Vòng poll per-source (N nguồn) VẪN chạy song
    song qua _pool bên trong wave (đủ nhẹ, không đáng lo dính lại lỗi
    refresh-nhiều-lần vì cả N future đều dùng CHUNG 1 token truyền vào
    — refresh chỉ xảy ra ở OUTER wave, không ở trong worker thread)."""
    f_source = request.args.get("source", "")
    f_status = request.args.get("status", "")
    f_triggered_by = request.args.get("triggered_by", "")
    crawl_page, crawl_per_page = _paginate_args_named("crawl_page", 6)
    crawl_offset = (crawl_page - 1) * crawl_per_page

    # Import trễ (blueprints.crawl_maintenance import ngược crawl_bp) —
    # cùng lý do tab 'maintenance' ở index() phía trên.
    from blueprints.crawl_maintenance import (
        _active_maintenance_runs_raw, _maintenance_history_context_raw,
    )

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
        index() dùng _source_active_state() ở trên)."""
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


@crawl_bp.route("/crawl/trigger", methods=["POST"])
@admin_required
def trigger():
    source = request.form.get("source", "").strip()
    category = request.form.get("category", "").strip()
    pages_raw = request.form.get("pages", "").strip()
    max_jobs_raw = request.form.get("max_jobs", "").strip()

    pages = int(pages_raw) if pages_raw.isdigit() else None
    max_jobs = int(max_jobs_raw) if max_jobs_raw.isdigit() else None

    try:
        result = _call_authed(
            db_data.trigger_crawl, source=source, category=category,
            pages=pages, max_jobs=max_jobs,
        )
        flash(
            f"Đã bắt đầu crawl {_SOURCE_LABELS.get(source, source)} "
            f"(run_id={result['run_id'][:8]}...). Theo dõi tiến độ ở khu 'Đang chạy' bên dưới.",
            "success",
        )
    except CrawlerAPIError as exc:
        if exc.status_code == 409:
            # Message backend đã sẵn tiếng Việt, dễ hiểu (xem
            # db.ActiveCrawlExistsError phía backend) — hiện thẳng,
            # không viết lại.
            flash(str(exc), "error")
        else:
            flash(str(exc), "error")

    return redirect(url_for("crawl.index"))


@crawl_bp.route("/crawl/batch/trigger", methods=["POST"])
@admin_required
def trigger_batch():
    """08/2026 — "crawl nhiều category liên tục". Khu A (crawl.html) đã
    đổi dropdown 1 category thành checkbox nhiều category cho MỌI lượt
    bấm (kể cả tick đúng 1 ô) — form của Khu A LUÔN post về đây, KHÔNG
    còn post về trigger() ở trên nữa (trigger() vẫn giữ nguyên, không
    xoá — có thể cần lại sau, xem docstring
    crawler_client/crawl.py::trigger_crawl_batch())."""
    source = request.form.get("source", "").strip()
    categories = [c.strip() for c in request.form.getlist("categories") if c.strip()]
    pages_raw = request.form.get("pages", "").strip()
    max_jobs_raw = request.form.get("max_jobs", "").strip()

    pages = int(pages_raw) if pages_raw.isdigit() else None
    max_jobs = int(max_jobs_raw) if max_jobs_raw.isdigit() else None

    if not categories:
        # Phòng hờ trường hợp JS validate bị tắt/lỗi (form.html đã chặn
        # submit khi chưa tick gì ở phía JS, xem crawl.html) — backend
        # Flask vẫn phải tự chặn lại vì request có thể tới đây trực
        # tiếp (curl, JS bị chặn...), CrawlBatchRequest phía FastAPI
        # backend cũng sẽ 422 nếu categories rỗng nhưng flash message
        # tiếng Việt rõ ràng hơn để redirect thẳng ở đây.
        flash("Chưa tick ngành nào — chọn ít nhất 1 ngành trước khi bấm.", "error")
        return redirect(url_for("crawl.index"))

    try:
        result = _call_authed(
            db_data.trigger_crawl_batch, source=source, categories=categories,
            pages=pages, max_jobs=max_jobs,
        )
        flash(
            f"Đã bắt đầu crawl {len(categories)} ngành liên tục cho "
            f"{_SOURCE_LABELS.get(source, source)} (batch_id={result['batch_id'][:8]}...). "
            f"Theo dõi tiến độ ở khu 'Đang chạy' bên dưới.",
            "success",
        )
    except CrawlerAPIError as exc:
        # Cùng cách xử lý lỗi (409 nguồn đang bận, hay lỗi khác) như
        # trigger() ở trên — message backend đã tiếng Việt sẵn.
        flash(str(exc), "error")

    return redirect(url_for("crawl.index"))


@crawl_bp.route("/crawl/<string:run_id>/status.json")
@admin_required
def status_json(run_id):
    """JSON polling — JS ở crawl.html gọi định kỳ tới khi status
    'done'/'error'. @admin_required tự trả JSON lỗi (không redirect
    HTML) khi bị chặn quyền, xem docstring decorator."""
    try:
        run = _call_authed(db_data.get_crawl_status, run_id)
    except CrawlerAPIError as exc:
        return jsonify({"error": str(exc)}), (exc.status_code or 500)
    if run is None:
        return jsonify({"error": "Không tìm thấy lượt crawl này."}), 404
    return jsonify(run)


@crawl_bp.route("/crawl/<string:run_id>/logs.json")
@admin_required
def logs_json(run_id):
    """JSON polling khu "Xem log live" — JS ở crawl.html gọi định kỳ
    (song song với status.json) kèm ?after_id=N để chỉ lấy dòng log MỚI
    (xem docstring crawler_client/crawl.py::get_crawl_logs). Cùng cách
    xử lý lỗi như status_json() ở trên (@admin_required tự trả JSON,
    không redirect HTML)."""
    after_id = request.args.get("after_id", "0")
    after_id = int(after_id) if after_id.isdigit() else 0
    try:
        result = _call_authed(db_data.get_crawl_logs, run_id, after_id=after_id)
    except CrawlerAPIError as exc:
        return jsonify({"error": str(exc)}), (exc.status_code or 500)
    return jsonify(result)


@crawl_bp.route("/crawl/batch/<string:batch_id>/status.json")
@admin_required
def batch_status_json(batch_id):
    """JSON polling cho card batch ở Khu B — JS ở crawl.html gọi định
    kỳ (khác hẳn status.json ở trên vốn poll 1 run đơn lẻ) tới khi
    batch.status 'done'/'error'. Trả kèm "checklist" đủ N category để
    JS cập nhật badge từng dòng, xem docstring
    crawler_client/crawl.py::_normalize_crawl_batch()."""
    try:
        batch = _call_authed(db_data.get_crawl_batch_status, batch_id)
    except CrawlerAPIError as exc:
        return jsonify({"error": str(exc)}), (exc.status_code or 500)
    if batch is None:
        return jsonify({"error": "Không tìm thấy batch này."}), 404
    return jsonify(batch)


@crawl_bp.route("/crawl/latest-log-run")
@admin_required
def latest_log_run():
    """JSON — khung "Log live" (LUÔN HIỆN cố định trên trang, 08/2026,
    xem lịch sử trao đổi) gọi lúc tải trang để biết run_id GẦN NHẤT
    (bất kể status) mà nó nên hiện log. Trả {"run_id": null, ...} (không
    phải 404) nếu chưa từng crawl lần nào — đây là trạng thái hợp lệ,
    JS tự hiện "Chưa có lượt crawl nào." thay vì coi là lỗi."""
    try:
        run = _call_authed(db_data.get_crawl_latest_log_run)
    except CrawlerAPIError as exc:
        return jsonify({"error": str(exc)}), (exc.status_code or 500)
    return jsonify(run or {"run_id": None})


# CUỐI FILE (CHỦ Ý, KHÔNG di lên đầu) — import để tự đăng ký các route
# /crawl/maintenance/* vào ĐÚNG crawl_bp object này (xem docstring đầu
# blueprints/crawl_maintenance.py để biết vì sao tách file nhưng dùng
# chung 1 blueprint — giữ endpoint namespace 'crawl.*' để không phải
# sửa logic active-highlight ở base.html). PHẢI đặt ở CUỐI, sau khi
# crawl_bp đã được gán (dòng 21) — crawl_maintenance.py làm
# `from blueprints.crawl import crawl_bp`, đặt import này ở ĐẦU file sẽ
# vỡ vì crawl_bp chưa tồn tại lúc đó.
from blueprints import crawl_maintenance  # noqa: F401
