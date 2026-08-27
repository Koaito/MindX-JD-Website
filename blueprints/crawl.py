"""Crawl blueprint — trang "Vận hành dữ liệu" (08/2026, đổi tên từ
"Crawl dữ liệu" — xem lịch sử trao đổi "1 mục, 2 tab như
data_management.py"). CHỈ admin thấy và dùng được (khớp yêu cầu gốc,
chặt hơn @staff_required cho ss_team đang dùng ở hầu hết trang quản trị
khác) — xem utils/decorators.py::admin_required.

TAB "crawl" (mặc định) — nội dung y hệt trang cũ, dời sang
_crawl_tab.html, KHÔNG đổi logic.
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

from flask import Blueprint, jsonify, render_template, request, redirect, url_for, flash
from flask_login import current_user

import backend_auth
from backend_auth import BackendAuthError
import crawler_client as db_data
from crawler_client import CrawlerAPIError
from utils.decorators import admin_required
from helpers import _auth_tokens_from_session, _call_authed, _paginate_args

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


@crawl_bp.route("/crawl")
@admin_required
def index():
    """Trang chính — 2 tab (?tab=crawl mặc định | ?tab=maintenance).

    Tab 'crawl': Khu A (kích hoạt), Khu B (đang chạy, tối đa 2 —
    1/nguồn), Khu C (lịch sử, filter + phân trang) — y hệt trước đây.

    Tab 'maintenance': build context riêng ở
    _maintenance_tab_context() (blueprints/crawl_maintenance.py) rồi
    merge vào đây — tách hàm để file này không phình to, KHÔNG tính lại
    context tab đang KHÔNG hiển thị (đỡ gọi API thừa lúc chỉ xem 1 tab)."""
    tab = request.args.get("tab", "crawl")
    if tab not in ("crawl", "maintenance"):
        tab = "crawl"

    if tab == "maintenance":
        # Import trễ (KHÔNG để đầu file) để tránh import vòng: file đó
        # `from blueprints.crawl import crawl_bp`, import ở đầu file
        # này sẽ chạy TRƯỚC KHI crawl_bp được định nghĩa (dòng 21) ->
        # ImportError. Import trễ bên trong hàm chỉ chạy lúc request
        # thật tới, lúc đó module đã load xong hoàn toàn.
        from blueprints.crawl_maintenance import _maintenance_tab_context
        return render_template("crawl.html", tab=tab, **_maintenance_tab_context())

    try:
        sources = db_data.get_sources()
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        sources = {}

    active_runs = {}
    active_batches = {}
    for source in sources:
        try:
            run = _active_run_for_source(source)
        except CrawlerAPIError as exc:
            flash(str(exc), "error")
            run = None
        if run:
            active_runs[source] = run
            # 08/2026 — nếu run đang chạy của nguồn này thuộc 1 batch
            # (batch_id khác None, xem docstring
            # crawler_client/crawl.py::_normalize_crawl_run), lấy thêm
            # tiến độ TỔNG của batch (checklist đủ N category) để Khu B
            # hiện card "2/6 category xong" thay vì card 1-category cũ.
            # Lỗi ở đây KHÔNG chặn render trang (card vẫn hiện, chỉ
            # thiếu checklist) — giống cách active_runs xử lý lỗi ở trên.
            if run.get("batch_id"):
                try:
                    batch = _call_authed(db_data.get_crawl_batch_status, run["batch_id"])
                except CrawlerAPIError as exc:
                    flash(str(exc), "error")
                    batch = None
                if batch:
                    active_batches[source] = batch

    # Filter lịch sử
    f_source = request.args.get("source", "")
    f_status = request.args.get("status", "")
    f_triggered_by = request.args.get("triggered_by", "")

    try:
        page, per_page = _paginate_args(30)
        offset = (page - 1) * per_page
        result = _call_authed(
            db_data.list_crawl_runs, source=f_source, status=f_status,
            triggered_by=f_triggered_by, limit=per_page, offset=offset,
        )
        runs = result["items"]
        total_runs = result["total"]
        total_pages = max(1, math.ceil(total_runs / per_page))
        if page > total_pages:
            page = total_pages
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        runs, total_runs, total_pages, page, per_page = [], 0, 1, 1, 30

    # Dropdown "người bấm" — CHỈ admin (khớp POST /crawl chỉ admin bấm
    # được, khác staff_members ở activity_logs.py gồm cả ss_team).
    access_token, _ = _auth_tokens_from_session()
    try:
        all_users = backend_auth.list_users(access_token)
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

    return render_template(
        "crawl.html",
        tab=tab,
        sources=sources, source_labels=_SOURCE_LABELS,
        active_runs=active_runs, active_batches=active_batches, category_labels=category_labels,
        runs=runs, total_runs=total_runs, page=page, total_pages=total_pages, per_page=per_page,
        status_labels=db_data.CRAWL_STATUS_LABELS, stat_labels=db_data.CRAWL_STAT_LABELS,
        admin_members=admin_members,
        filters={"source": f_source, "status": f_status, "triggered_by": f_triggered_by},
        pagination_filters={k: v for k, v in
                             {"source": f_source, "status": f_status, "triggered_by": f_triggered_by}.items() if v},
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
from blueprints import crawl_maintenance  # noqa: E402,F401
