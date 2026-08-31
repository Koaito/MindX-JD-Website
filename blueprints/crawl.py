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
from helpers import _auth_tokens_from_session, _call_authed, _paginate_args, _store_auth_tokens, _io_pool as _pool
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
    """Trang chính "Vận hành dữ liệu" — 3 tab (crawl/status/maintenance),
    RENDER CẢ 3 CÙNG LÚC trong 1 response (08/2026, đổi từ early-return
    theo ?tab=, xem lịch sử trao đổi "phương án 1 — client-side tab như
    dashboard"). Chuyển tab sau khi trang đã tải là JS thuần (ẩn/hiện
    .dashboard-tab, xem script cuối crawl.html) — KHÔNG round-trip nữa.
    ?tab= trong URL giờ chỉ còn ý nghĩa "tab nào active lúc mở link này"
    (đọc bởi JS lúc init, y hệt cách dashboard.html đang làm), KHÔNG còn
    quyết định server render gì.

    3 context (crawl/status/maintenance) CỐ Ý để trong 3 dict RIÊNG
    (crawl_ctx / status_ctx / maintenance_ctx) thay vì merge phẳng vào 1
    namespace — 2 tab crawl và maintenance TRÙNG khá nhiều tên biến
    (active_runs, runs, total_runs, page, total_pages, per_page,
    status_labels, admin_members, filters, pagination_filters); merge
    phẳng bằng **kwargs như code cũ (chỉ merge được 1 tab/lần vì trước
    đây early-return) giờ sẽ làm biến tab sau ĐÈ tab trước nếu gộp cả 3
    cùng lúc. crawl.html tự {% with %} scoped-rename ngay trước mỗi
    {% include %} — KHÔNG phải sửa 1 dòng nào bên trong 3 file partial
    (_crawl_tab.html/_status_tab.html/_maintenance_tab.html), giữ
    nguyên logic JS/Jinja đang chạy ổn định của từng tab.

    CHƯA song song hoá 3 lệnh build context này VỚI NHAU (khác các nơi
    khác trong app đang dùng _io_pool) — _status_tab_context()/
    _maintenance_tab_context() tự đọc Flask session
    (_auth_tokens_from_session()/_call_authed()) bên trong thân hàm, cả
    2 đều CẦN request context, không chạy được trên worker thread (xem
    docstring _source_active_state() ở file này để biết rõ lý do — cùng
    ràng buộc). Song song hoá thật 3 tab với nhau cần refactor 2 hàm đó
    nhận access_token qua tham số thay vì tự đọc session (giống cách
    _source_active_state() đã làm) — để lại cho đợt sau, không đụng vào
    trong lần sửa này để tránh ảnh hưởng luồng refresh-token đang chạy
    ổn định ở 2 hàm đó. Chấp nhận được vì cả 2 tab mới đều rẻ: status =
    2 round-trip SQL cố định (không tăng theo tổng số record), maintenance
    = lịch sử đã phân trang server + 1 call gộp đủ 5 job_type — lần load
    đầu tăng thêm vừa phải, không đáng kể so với tab crawl (vốn đã nặng
    nhất, đã song song hoá nội bộ từ trước)."""
    tab = request.args.get("tab", "crawl")
    if tab not in ("crawl", "status", "maintenance"):
        tab = "crawl"

    status_ctx = _status_tab_context()

    # Import trễ (KHÔNG để đầu file) để tránh import vòng: file đó
    # `from blueprints.crawl import crawl_bp`, import ở đầu file này sẽ
    # chạy TRƯỚC KHI crawl_bp được định nghĩa (dòng 21) -> ImportError.
    # Import trễ bên trong hàm chỉ chạy lúc request thật tới, lúc đó
    # module đã load xong hoàn toàn. Trước đây chỉ import khi tab==
    # 'maintenance' (early-return) — giờ LUÔN cần vì tab maintenance
    # luôn được build cùng 2 tab kia, nhưng vẫn giữ import Ở ĐÂY (không
    # dời lên đầu file) vì lý do vòng lặp import không đổi.
    from blueprints.crawl_maintenance import _maintenance_tab_context
    maintenance_ctx = _maintenance_tab_context()

    # ---- Tab "crawl" (mặc định) — Khu A/B/C, logic y hệt trước đây ----
    # access_token lấy 1 LẦN ở đây (main thread, Flask session context)
    # cho CẢ 3 nhóm việc độc lập bên dưới (per-source poll / list_crawl_runs
    # / list_users) — cùng lý do _source_active_state() không tự gọi
    # _auth_tokens_from_session() (worker thread không có request context).
    access_token, refresh_token = _auth_tokens_from_session()

    f_source = request.args.get("source", "")
    f_status = request.args.get("status", "")
    f_triggered_by = request.args.get("triggered_by", "")
    page, per_page = _paginate_args(30)
    offset = (page - 1) * per_page

    # get_sources() bắn đi NGAY (không phụ thuộc access_token) — độc lập
    # hoàn toàn với list_crawl_runs/list_users bên dưới, nên KHÔNG cần
    # nằm trong _run_wave() (không cần resubmit lại nếu access_token
    # phải refresh — get_sources() không nhận token, refresh không ảnh
    # hưởng gì tới nó).
    sources_future = _pool.submit(db_data.get_sources)

    def _run_wave(token):
        """Bắn 2 việc ĐỘC LẬP NHAU vào _pool: (1) lịch sử crawl phân
        trang (list_crawl_runs), (2) dropdown "người bấm" (list_users) —
        2 việc này thêm 08/2026 (xem lịch sử trao đổi "làm cái crawl từ
        đầu") từng bị xếp NỐI TIẾP sau vòng poll per-source dù không phụ
        thuộc gì vào nó lẫn vào nhau. Trả về future (KHÔNG .result() ở
        đây) để nơi gọi tự quyết định thời điểm chờ — cho phép vòng poll
        per-source (submit NGAY SAU lời gọi hàm này, xem bên dưới) chạy
        chồng lấn thời gian với 2 future này, không phải đợi tuần tự."""
        runs_future = _pool.submit(
            db_data.list_crawl_runs, token, source=f_source, status=f_status,
            triggered_by=f_triggered_by, limit=per_page, offset=offset,
        )
        users_future = _pool.submit(backend_auth.list_users, token)
        return runs_future, users_future

    runs_future, users_future = _run_wave(access_token)

    try:
        sources = sources_future.result()
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        sources = {}

    active_runs = {}
    active_batches = {}
    # Song song hoá vòng lặp per-source (thêm 08/2026, xem lịch sử trao
    # đổi "/crawl chậm 4.69s — cùng nguyên nhân round-trip tuần tự như
    # /companies") — trước đây for source in sources: gọi
    # _active_run_for_source() (+ batch status nếu có) TUẦN TỰ từng
    # nguồn, tổng thời gian = tổng round-trip mọi nguồn. Giờ bắn cả
    # N nguồn cùng lúc qua _pool, tổng thời gian ≈ nguồn CHẬM NHẤT —
    # VÀ chạy CHỒNG LẤN với runs_future/users_future ở trên (2 future đó
    # đã bắn đi TRƯỚC KHI biết sources, đang chạy song song ngay lúc
    # này, không phải đợi thêm round-trip riêng).
    #
    # Nếu access_token hết hạn (401) ở BẤT KỲ nguồn nào (hoặc ở
    # runs_future/users_future), refresh 1 LẦN trên main thread rồi
    # submit lại TOÀN BỘ (cả 3 nhóm) — refresh token là ghi session, chỉ
    # an toàn làm ở main thread.
    def _run_sources(token):
        futures = {source: _pool.submit(_source_active_state, source, token) for source in sources}
        return {source: futures[source].result() for source in sources}

    source_results = _run_sources(access_token)
    had_401 = (
        any(
            isinstance(error, CrawlerAPIError) and error.status_code == 401
            for _s, _r, _b, error in source_results.values()
        )
        or (isinstance(runs_future.exception(), CrawlerAPIError) and runs_future.exception().status_code == 401)
        or (isinstance(users_future.exception(), BackendAuthError) and users_future.exception().status_code == 401)
    )
    if had_401 and refresh_token:
        try:
            pair = backend_auth.refresh(refresh_token)
        except BackendAuthError:
            pair = None
        if pair:
            _store_auth_tokens(pair["access_token"], pair["refresh_token"])
            runs_future, users_future = _run_wave(pair["access_token"])
            source_results = _run_sources(pair["access_token"])

    for source in sources:
        _src, run, batch, error = source_results[source]
        if error:
            flash(str(error), "error")
        if run:
            active_runs[source] = run
            if batch:
                active_batches[source] = batch

    # Lịch sử crawl (list_crawl_runs) — .result() ở ĐÂY (không phải lúc
    # runs_future vừa tạo) vì future đã chạy song song với per-source
    # poll ở trên, tới đây nhiều khả năng đã xong sẵn, .result() gần
    # như không phải chờ thêm.
    try:
        result = runs_future.result()
        runs = result["items"]
        total_runs = result["total"]
        total_pages = max(1, math.ceil(total_runs / per_page))
        page = min(page, total_pages)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        runs, total_runs, total_pages, page, per_page = [], 0, 1, 1, 30

    # Dropdown "người bấm" — CHỈ admin (khớp POST /crawl chỉ admin bấm
    # được, khác staff_members ở activity_logs.py gồm cả ss_team). Cùng
    # lý do trên — future đã chạy song song từ đầu, .result() ở đây gần
    # như không tốn thêm thời gian chờ.
    try:
        all_users = users_future.result()
        admin_members = [u for u in all_users if u.get("role") == "admin"]
    except BackendAuthError as exc:
        flash(str(exc), "error")
        admin_members = []

    # Nhãn category phẳng "source:category" -> label — dùng CẢ server
    # render (Khu C) LẪN JS (Khu B tự thêm dòng lịch sử khi crawl xong,
    # xem crawl.html script) để không phải định nghĩa nhãn 2 lần lệch
    # nhau giữa Jinja và JS.
    category_labels = {
        f"{src}:{cat}": label
        for src, cats in sources.items() for cat, label in cats.items()
    }

    crawl_ctx = {
        "sources": sources, "source_labels": _SOURCE_LABELS,
        "active_runs": active_runs, "active_batches": active_batches, "category_labels": category_labels,
        "runs": runs, "total_runs": total_runs, "page": page, "total_pages": total_pages, "per_page": per_page,
        "status_labels": db_data.CRAWL_STATUS_LABELS, "stat_labels": db_data.CRAWL_STAT_LABELS,
        "admin_members": admin_members,
        "filters": {"source": f_source, "status": f_status, "triggered_by": f_triggered_by},
        "pagination_filters": {k: v for k, v in
                                {"source": f_source, "status": f_status, "triggered_by": f_triggered_by}.items() if v},
    }

    return render_template(
        "crawl.html",
        tab=tab,
        crawl_ctx=crawl_ctx, status_ctx=status_ctx, maintenance_ctx=maintenance_ctx,
    )


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
