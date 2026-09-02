"""Crawl blueprint — trang "Vận hành dữ liệu" (08/2026, đổi tên từ
"Crawl dữ liệu" — xem lịch sử trao đổi "1 mục, 2 tab như
data_management.py").

QUYỀN XEM (SỬA LẠI 09/2026, xem lịch sử trao đổi "khôi phục ss_team xem
được"): ss_team XEM được cả trang (mọi route GET/polling dùng
@staff_required) — khớp đúng mức backend thật sự yêu cầu
(Depends(require_role("ss_team")) cho GET /crawl, GET /crawl/{run_id},
... xem api/routers/crawl.py phía scrap-jd-api). CHỈ 2 route BẤM CHẠY
(trigger()/trigger_batch() bên dưới) mới @admin_required — khớp POST
/crawl chỉ Depends(require_admin) phía backend. Bản trước đó từng khoá
@admin_required trên MỌI route (kể cả index()) — chặt hơn backend cần,
khiến ss_team thấy mục "Vận hành dữ liệu" ở sidebar nhưng bấm vào bị
chặn/redirect. Template (_crawl_tab.html/_maintenance_tab.html) tự ẩn
form/nút bấm kích hoạt nếu current_user không phải admin — ss_team xem
được tiến độ/lịch sử nhưng không thấy nút bấm chạy job.

TAB "crawl" (mặc định) — Khu A (kích hoạt) + Khu B (đang chạy), context
build ngay trong index() bên dưới.
TAB "status" — "Tình trạng dữ liệu" (08/2026): bảng company đang thiếu
field gì/tỉ lệ bao nhiêu, cho admin xem mà KHÔNG cần vào thẳng database
— context build ở blueprints/crawl_status.py (file riêng, CHỈ ĐỌC,
không có route/form trigger nào nên import Ở ĐẦU file này, không như
"maintenance"/"history" bên dưới).
TAB "maintenance" — 5 job bảo trì dữ liệu (backfill_company_profiles,
enrich_profile_from_website, enrich_web_info, get_fb_linkedin,
check_expired_jobs), route trigger/status/logs khai ở
blueprints/crawl_maintenance.py (file riêng, CÙNG blueprint object
`crawl_bp` này — import ở CUỐI file để tự đăng ký route, xem dòng
import cuối file).
TAB "history" (thêm 08/2026) — mục sidebar thứ 4 "Lịch sử vận hành":
2 bảng lịch sử (crawl + bảo trì) xếp DỌC, mỗi bảng phân trang riêng 6
dòng/trang, cùng widget "Đang chạy" tĩnh cho cả 2 loại. Context build ở
blueprints/crawl_history.py (file riêng, CHỈ ĐỌC như "status" —
KHÔNG dùng chung crawl_bp vì không có route/form nào — nhưng vẫn phải
import TRỄ trong index() vì file đó cần import ngược
_source_active_state/_SOURCE_LABELS từ đây, xem docstring đầu file đó).

URL giữ nguyên `/crawl` (không đổi thành `/van-hanh-du-lieu` hay tương
tự) — CHỦ Ý để không phải sửa mọi `url_for('crawl.index')` đang rải rác
(base.html, breadcrumb...) chỉ vì đổi tên hiển thị.

Nguồn dữ liệu: bảng crawl_runs (Postgres, xem
sql/migration_add_crawl_runs.sql phía backend) — thay cho _RUNS (RAM)
cũ, sống bền qua restart server."""

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
from helpers import _auth_tokens_from_session, _call_authed, _store_auth_tokens, _io_pool as _pool
from utils.decorators import admin_required, staff_required

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


def _all_active_crawl_runs_raw(token) -> dict:
    """Trả {source: run} cho MỌI nguồn đang có 1 lượt 'queued'/'running'
    — CHỈ 2 lần gọi GET /crawl TỔNG CỘNG (không lặp per-source như
    _source_active_state(), vốn cần chạy song song ở tab 'crawl' vì còn
    phải lấy thêm batch status). Mirror
    crawl_maintenance.py::_active_maintenance_runs_raw() — dùng để hiện
    dữ liệu crawl ở WIDGET của TAB KHÁC (maintenance/status), nơi chỉ
    cần biết "đang chạy gì" chứ không cần checklist batch chi tiết.

    Nhận token truyền tay (không tự gọi _auth_tokens_from_session()) —
    nơi gọi tự lấy token 1 lần rồi có thể dùng lại cho nhiều lệnh gọi
    khác trong cùng request, cùng lý do _active_maintenance_runs_raw()."""
    active = {}
    for status in ("queued", "running"):
        result = db_data.list_crawl_runs(token, source="", status=status, limit=10)
        for run in result["items"]:
            active[run["source"]] = run
    return active


def _crawl_tab_context() -> dict:
    """Build TOÀN BỘ context cho tab='crawl' (Khu A kích hoạt + Khu B
    đang chạy) — tách hàm riêng (09/2026, xem lịch sử trao đổi "load
    chậm mỗi lần chuyển phân trang log — 76 request logs.json chạy nền
    dù đang đứng ở tab khác") theo ĐÚNG pattern 3 hàm context kia
    (_status_tab_context/_maintenance_tab_context/_history_tab_context)
    để index() có thể build ĐÚNG 1 TAB cần thiết mỗi request thay vì
    LUÔN build cả 4 (xem docstring index() để biết lý do đổi + đánh đổi
    đã bàn với người dùng: tab đang mở lúc load trang vẫn nhanh như cũ,
    3 tab còn lại chỉ tốn thêm đúng 1 round-trip nhẹ ở LẦN ĐẦU người
    dùng bấm sang, không phải mỗi lần — xem script cuối crawl.html).

    Logic bên trong GIỮ NGUYÊN 100% so với bản cũ nằm thẳng trong
    index() — chỉ di chuyển, không đổi hành vi."""
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

    # WIDGET CHÉO (KHÔI PHỤC 09/2026, xem lịch sử trao đổi "đồng bộ
    # widget đang chạy") — tab 'crawl' tự thêm dữ liệu MAINTENANCE đang
    # chạy (loại nó KHÔNG tự có) để widget nổi hiện được CẢ 2 loại job
    # nền, không chỉ crawl. Import trễ (không ở đầu file) vì
    # blueprints.crawl_maintenance import ngược crawl_bp từ file này —
    # đặt ở đầu file sẽ vỡ vòng lặp lúc app khởi động (xem docstring
    # cuối file). Lỗi ở đây KHÔNG chặn render tab (mất mỗi phần hiện
    # chéo, tab vẫn hoạt động bình thường).
    try:
        from blueprints.crawl_maintenance import _active_maintenance_runs_raw
        cross_active_runs = _active_maintenance_runs_raw(access_token)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        cross_active_runs = {}

    return {
        "sources": sources, "source_labels": _SOURCE_LABELS,
        "active_runs": active_runs, "active_batches": active_batches, "category_labels": category_labels,
        # cross_active_runs/cross_labels: dữ liệu MAINTENANCE đang chạy
        # (job_type -> run) + nhãn hiển thị — widget nổi
        # (_crawl_tab.html) dùng để hiện thêm 1 khối "Bảo trì" bên dưới
        # khối "Crawl" chính, xem docstring khối widget trong template.
        "cross_active_runs": cross_active_runs, "cross_labels": db_data.MAINTENANCE_JOB_LABELS,
        "cross_status_labels": db_data.MAINTENANCE_STATUS_LABELS,
        # status_labels/stat_labels: KHÔNG còn dùng để render Khu C ở
        # đây (đã chuyển sang tab "history") nhưng JS Khu B
        # (buildHistoryRow(), xem _crawl_tab.html) vẫn cần 2 biến này để
        # hiện kết quả crawl NGAY TẠI CHỖ khi 1 lượt vừa chạy xong —
        # thiếu 2 biến này JS sẽ lỗi (undefined) lúc build dòng, dù
        # dòng đó cuối cùng không chèn được vào đâu (không còn
        # #crawl-history-tbody trong DOM tab này) vì buildHistoryRow()
        # bị gọi TRƯỚC bước kiểm tra !tbody.
        "status_labels": db_data.CRAWL_STATUS_LABELS, "stat_labels": db_data.CRAWL_STAT_LABELS,
        "filters": {"source": f_source},
    }


# tab name -> tên file partial tương ứng (SỬA 09/2026, xem docstring
# index() bên dưới) — DUY NHẤT 1 nơi liệt kê mapping 4 tab, index()
# (cả nhánh full-page lẫn nhánh AJAX) tra cứu qua đây, không lặp lại
# danh sách 4 tab ở nhiều chỗ.
_TAB_TEMPLATES = {
    "crawl": "_crawl_tab.html",
    "status": "_status_tab.html",
    "maintenance": "_maintenance_tab.html",
    "history": "_history_tab.html",
}


def _build_tab_context(tab: str) -> dict:
    """Tra đúng 1 hàm build context ứng với `tab` — KHÔNG còn gọi cả 4
    hàm context như bản cũ (xem docstring index()). Import trễ (không ở
    đầu file) GIỮ NGUYÊN như trước — 2 module con vẫn import ngược
    _SOURCE_LABELS/_source_active_state/crawl_bp từ file này, xem
    docstring đầu file + docstring 2 module đó."""
    if tab == "status":
        return _status_tab_context()
    if tab == "maintenance":
        from blueprints.crawl_maintenance import _maintenance_tab_context
        return _maintenance_tab_context()
    if tab == "history":
        from blueprints.crawl_history import _history_tab_context
        return _history_tab_context()
    return _crawl_tab_context()


@crawl_bp.route("/crawl")
@staff_required
def index():
    """Trang chính "Vận hành dữ liệu" — 4 tab (crawl/status/maintenance/
    history).

    SỬA 09/2026 (xem lịch sử trao đổi "load chậm mỗi lần chuyển phân
    trang log — 76 request logs.json chạy nền dù đang đứng ở tab
    khác"): bản trước RENDER CẢ 4 TAB CÙNG LÚC trong 1 response (build
    đủ cả 4 context, kể cả 3 tab người dùng không xem) — mỗi lần
    reload trang (kể cả chỉ để bấm phân trang bảng lịch sử) đều tốn
    công build lại TOÀN BỘ, cộng thêm 2 vòng setInterval poll log ở
    _crawl_tab.html/_maintenance_tab.html tự khởi động lại và chạy nền
    suốt phiên xem trang dù tab đó không hiển thị -> hàng chục request
    thừa mỗi lần, xem chi tiết điều tra trong lịch sử trao đổi trên.

    GIỜ: mỗi request chỉ build ĐÚNG 1 TAB (`tab` query param, mặc định
    "crawl") — 3 tab còn lại KHÔNG build, không render nội dung (client
    thấy khung rỗng, `data-loaded="false"`). JS cuối crawl.html
    (`loadTabIfNeeded()`) tự fetch lại ĐÚNG 1 TAB đó qua chính route
    này (thêm header X-Requested-With để nhận diện AJAX, xem nhánh
    `is_ajax` bên dưới) ở lần đầu người dùng bấm sang tab chưa load —
    load xong thì giữ nguyên trong DOM, bấm qua lại các tab đã từng mở
    không fetch lại nữa (KHÔNG mất tính "tức thời" cho tab đã xem).
    Bảng lịch sử (tab "history") cũng đổi phân trang/lọc từ
    `<a href>`/`<form method=get>` reload cả trang sang fetch AJAX qua
    route này (xem _history_tab.html + JS "ajaxNavigate()") — mỗi lần
    bấm "Trang sau" giờ chỉ tốn đúng 1 round-trip build `history_ctx`,
    không kéo theo 3 context kia và không khởi động lại 2 vòng poll
    nền của tab crawl/maintenance.

    ĐÁNH ĐỔI đã thống nhất với người dùng (không cần giữ nguyên): tab
    ĐẦU TIÊN mở trang (theo ?tab= hoặc mặc định "crawl") vẫn dựng sẵn
    trong response đầu tiên như cũ — tức thời. 3 tab còn lại chỉ chậm
    hơn ở ĐÚNG lần bấm đầu tiên trong phiên xem trang (1 round-trip nhẹ
    build 1 context, không phải chờ tất cả) — chấp nhận được, KHÔNG cần
    tức thời tuyệt đối, chỉ cần nhanh (mục tiêu <=1.5s).

    is_ajax: request tới TỪ chính JS ở crawl.html (loadTabIfNeeded()/
    ajaxNavigate()) — trả THẲNG fragment HTML của 1 partial (không qua
    layout base.html), KHÔNG phải JSON (khác các route *.json khác ở
    file này) vì phía JS chỉ cần chèn thẳng vào innerHTML của
    `.dashboard-tab` tương ứng, không cần parse gì thêm."""
    tab = request.args.get("tab", "crawl")
    if tab not in _TAB_TEMPLATES:
        tab = "crawl"

    ctx = _build_tab_context(tab)
    tab_html = render_template(_TAB_TEMPLATES[tab], **ctx)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        # Fragment thuần — không render qua crawl.html/base.html, tránh
        # JS phải tự bóc lại đúng đoạn <div class="dashboard-tab"> từ
        # 1 trang HTML đầy đủ (header, sidebar, script khác...).
        return tab_html

    return render_template("crawl.html", tab=tab, tab_html=tab_html)


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
@staff_required
def status_json(run_id):
    """JSON polling — JS ở crawl.html gọi định kỳ tới khi status
    'done'/'error'. @staff_required tự trả JSON lỗi (không redirect
    HTML) khi bị chặn quyền, xem docstring decorator."""
    try:
        run = _call_authed(db_data.get_crawl_status, run_id)
    except CrawlerAPIError as exc:
        return jsonify({"error": str(exc)}), (exc.status_code or 500)
    if run is None:
        return jsonify({"error": "Không tìm thấy lượt crawl này."}), 404
    return jsonify(run)


@crawl_bp.route("/crawl/<string:run_id>/logs.json")
@staff_required
def logs_json(run_id):
    """JSON polling khu "Xem log live" — JS ở crawl.html gọi định kỳ
    (song song với status.json) kèm ?after_id=N để chỉ lấy dòng log MỚI
    (xem docstring crawler_client/crawl.py::get_crawl_logs). Cùng cách
    xử lý lỗi như status_json() ở trên (@staff_required tự trả JSON,
    không redirect HTML)."""
    after_id = request.args.get("after_id", "0")
    after_id = int(after_id) if after_id.isdigit() else 0
    try:
        result = _call_authed(db_data.get_crawl_logs, run_id, after_id=after_id)
    except CrawlerAPIError as exc:
        return jsonify({"error": str(exc)}), (exc.status_code or 500)
    return jsonify(result)


@crawl_bp.route("/crawl/batch/<string:batch_id>/status.json")
@staff_required
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
@staff_required
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
