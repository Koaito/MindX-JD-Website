"""Crawl blueprint — trang "Crawl dữ liệu" (08/2026). CHỈ admin thấy và
dùng được (khớp yêu cầu gốc, chặt hơn @staff_required cho ss_team đang
dùng ở hầu hết trang quản trị khác) — xem utils/decorators.py::admin_required.

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
# có category, không có nhãn nguồn) — giữ khớp tay với 2 nguồn đã đăng ký
# ở crawl_runner.py phía backend (careerviet CHƯA có adapter, xem lịch sử
# trao đổi — cố tình không liệt kê ở đây).
_SOURCE_LABELS = {"topcv": "TopCV", "vietnamworks": "VietnamWorks"}


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
    """Trang chính — Khu A (kích hoạt), Khu B (đang chạy, tối đa 2 —
    1/nguồn), Khu C (lịch sử, filter + phân trang)."""
    try:
        sources = db_data.get_sources()
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        sources = {}

    active_runs = {}
    for source in sources:
        try:
            run = _active_run_for_source(source)
        except CrawlerAPIError as exc:
            flash(str(exc), "error")
            run = None
        if run:
            active_runs[source] = run

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
        sources=sources, source_labels=_SOURCE_LABELS,
        active_runs=active_runs, category_labels=category_labels,
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
