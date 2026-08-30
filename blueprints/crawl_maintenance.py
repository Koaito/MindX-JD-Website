"""Route cho tab "Bảo trì dữ liệu" ở trang "Vận hành dữ liệu" (08/2026,
xem lịch sử trao đổi "phương án B — generic runner dùng chung"). CHỈ
admin bấm chạy được (@admin_required, khớp POST /maintenance/{job_type}
chỉ admin) — xem utils/decorators.py.

08/2026 (SỬA — xem lịch sử trao đổi "ss_team muốn thấy mục Vận hành dữ
liệu") — 3 route CHỈ ĐỌC bên dưới (maintenance_status_json,
maintenance_logs_json, maintenance_latest_log_runs_json) đổi từ
@admin_required sang @staff_required — ss_team xem được log
live/trạng thái job đang chạy, khớp GET /maintenance/{run_id} + GET
/maintenance/{run_id}/logs + GET /maintenance/latest-log-runs phía
backend (chỉ cần 'ss_team', xem crawler_client/maintenance.py). CHỈ
maintenance_trigger() (POST, bấm chạy job thật) còn giữ
@admin_required — form Khu A ẩn khỏi mắt ss_team ở template (xem
_maintenance_tab.html, current_user.role == 'admin').

TÁCH FILE RIÊNG (khác gộp thẳng vào crawl.py) để crawl.py không phình
to quá — 2 domain (crawl nguồn ngoài / bảo trì dữ liệu nội bộ) đủ khác
nhau để tách, giống cách project đã tách domain khác (companies.py,
contacts.py...). NHƯNG dùng CHUNG 1 blueprint object `crawl_bp` (import
từ blueprints.crawl, KHÔNG tự tạo Blueprint mới) để mọi route ở đây vẫn
mang endpoint 'crawl.*' — giữ nguyên logic active-highlight sidebar
(base.html: `request.endpoint.startswith('crawl.')`) mà không phải sửa
gì thêm, và để cả 2 tab cùng nằm trên đúng 1 mục sidebar "Vận hành dữ
liệu" duy nhất.

Nguồn dữ liệu: bảng maintenance_runs (Postgres, xem
sql/migration_add_maintenance_runs.sql phía backend)."""

import math

from flask import flash, jsonify, redirect, request, url_for

import backend_auth
import crawler_client as db_data
from backend_auth import BackendAuthError

# Import trễ để tránh vòng lặp import thật sự (crawl.py import module
# này ở CUỐI file, sau khi crawl_bp đã tồn tại) — xem docstring cuối
# blueprints/crawl.py.
from blueprints.crawl import crawl_bp
from crawler_client import CrawlerAPIError
from helpers import _auth_tokens_from_session, _call_authed, _paginate_args
from utils.decorators import admin_required, staff_required


def _active_maintenance_runs() -> dict:
    """Trả {job_type: run} cho các job_type ĐANG có 1 lượt
    'queued'/'running' — CHỈ 2 lần gọi API TỔNG CỘNG (không phải 2 lần
    x 5 job_type như _active_run_for_source() bên crawl.py, vì
    list_maintenance_runs() ở đây lọc ĐƯỢC theo status nhưng KHÔNG theo
    job_type khi để trống, nên gom hết job_type trong 1 lần gọi/status
    rồi tự group ở đây) — ưu tiên 'running' hơn 'queued' cho job_type
    nào (hiếm khi) có cả 2 (không thể xảy ra thật do UNIQUE INDEX phía
    backend, nhưng vẫn xử lý an toàn theo đúng thứ tự ưu tiên)."""
    active = {}
    for status in ("queued", "running"):
        result = _call_authed(db_data.list_maintenance_runs, status=status, limit=10)
        for run in result["items"]:
            active[run["job_type"]] = run
    return active


def _maintenance_tab_context() -> dict:
    """Build TOÀN BỘ context cho tab='maintenance' — gọi từ
    blueprints/crawl.py::index() khi tab=maintenance, tách hàm riêng để
    file đó không phải biết chi tiết bên trong (đối xứng cách index()
    tự build context tab='crawl' ngay trong nó, khác biệt CHỦ Ý vì
    context tab maintenance cần nhiều field riêng — tách cho rõ)."""
    active_runs = {}
    try:
        active_runs = _active_maintenance_runs()
    except CrawlerAPIError as exc:
        flash(str(exc), "error")

    try:
        latest_log_runs = _call_authed(db_data.get_maintenance_latest_log_runs)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        latest_log_runs = {j["job_type"]: None for j in db_data.MAINTENANCE_JOBS}

    # Filter lịch sử
    f_job_type = request.args.get("m_job_type", "")
    f_status = request.args.get("m_status", "")
    f_triggered_by = request.args.get("m_triggered_by", "")

    try:
        page, per_page = _paginate_args(30)
        offset = (page - 1) * per_page
        result = _call_authed(
            db_data.list_maintenance_runs, job_type=f_job_type, status=f_status,
            triggered_by=f_triggered_by, limit=per_page, offset=offset,
        )
        runs = result["items"]
        total_runs = result["total"]
        total_pages = max(1, math.ceil(total_runs / per_page))
        page = min(page, total_pages)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        runs, total_runs, total_pages, page, per_page = [], 0, 1, 1, 30

    # Dropdown "người bấm" — CHỈ admin (khớp POST /maintenance/{job_type}
    # chỉ admin bấm được), cùng logic index() bên crawl.py — KHÔNG tái
    # dùng chung 1 hàm vì mỗi nơi tự gọi backend_auth.list_users() 1
    # lần độc lập (đủ rẻ, không đáng tách thêm 1 helper cho 3 dòng).
    try:
        access_token, _ = _auth_tokens_from_session()
        all_users = backend_auth.list_users(access_token)
        admin_members = [u for u in all_users if u.get("role") == "admin"]
    except BackendAuthError as exc:
        flash(str(exc), "error")
        admin_members = []

    return {
        "maintenance_jobs": db_data.MAINTENANCE_JOBS,
        "job_labels": db_data.MAINTENANCE_JOB_LABELS,
        "stat_labels_by_job": db_data.MAINTENANCE_STAT_LABELS,
        "require_limit_job_types": db_data.MAINTENANCE_JOB_TYPES_REQUIRE_LIMIT,
        "check_expired_job_type": db_data.MAINTENANCE_CHECK_EXPIRED_JOB_TYPE,
        "active_runs": active_runs,
        "latest_log_runs": latest_log_runs,
        "runs": runs, "total_runs": total_runs, "page": page,
        "total_pages": total_pages, "per_page": per_page,
        "status_labels": db_data.MAINTENANCE_STATUS_LABELS,
        "admin_members": admin_members,
        "filters": {"job_type": f_job_type, "status": f_status, "triggered_by": f_triggered_by},
        "pagination_filters": {k: v for k, v in
                                {"m_job_type": f_job_type, "m_status": f_status,
                                 "m_triggered_by": f_triggered_by}.items() if v},
    }


@crawl_bp.route("/crawl/maintenance/<string:job_type>/trigger", methods=["POST"])
@admin_required
def maintenance_trigger(job_type):
    """1 route DÙNG CHUNG cho cả 5 job_type (khác crawl phải tách
    trigger()/trigger_batch() vì 2 shape payload khác nhau) — cả 5 job
    bảo trì cùng 1 shape tham số {limit, dry_run?, check_deadline_only?},
    chỉ khác job_type nào NHẬN field nào (chặn ở dưới)."""
    if job_type not in db_data.MAINTENANCE_JOB_LABELS:
        flash(f"job_type '{job_type}' không tồn tại.", "error")
        return redirect(url_for("crawl.index", tab="maintenance"))

    limit_raw = request.form.get("limit", "").strip()
    limit = int(limit_raw) if limit_raw.isdigit() else None

    if limit is None and job_type in db_data.MAINTENANCE_JOB_TYPES_REQUIRE_LIMIT:
        # Lớp chặn ĐẦU (JS + `required` trên input đã chặn trước ở
        # _maintenance_tab.html) — Flask vẫn tự chặn lại đề phòng JS bị
        # tắt/lỗi, cùng nguyên tắc trigger_batch() bên crawl.py. Backend
        # 400 là lớp chặn CUỐI, không phải duy nhất.
        flash(
            f"'{db_data.MAINTENANCE_JOB_LABELS[job_type]}' gọi Tavily/Gemini "
            f"(tốn phí thật) — bắt buộc nhập số lượng giới hạn trước khi bấm chạy.",
            "error",
        )
        return redirect(url_for("crawl.index", tab="maintenance"))

    dry_run = None
    check_deadline_only = None
    if job_type == db_data.MAINTENANCE_CHECK_EXPIRED_JOB_TYPE:
        dry_run = request.form.get("dry_run") == "on"
        check_deadline_only = request.form.get("check_deadline_only") == "on"

    try:
        result = _call_authed(
            db_data.trigger_maintenance_run, job_type=job_type, limit=limit,
            dry_run=dry_run, check_deadline_only=check_deadline_only,
        )
        flash(
            f"Đã bắt đầu '{db_data.MAINTENANCE_JOB_LABELS[job_type]}' "
            f"(run_id={result['run_id'][:8]}...). Theo dõi tiến độ ở khu 'Đang chạy' bên dưới.",
            "success",
        )
    except CrawlerAPIError as exc:
        # 409 (job_type đang bận) hay lỗi khác — message backend đã
        # tiếng Việt sẵn, hiện thẳng (cùng nguyên tắc trigger() bên
        # crawl.py).
        flash(str(exc), "error")

    return redirect(url_for("crawl.index", tab="maintenance"))


@crawl_bp.route("/crawl/maintenance/<string:run_id>/status.json")
@staff_required
def maintenance_status_json(run_id):
    """JSON polling — JS ở _maintenance_tab.html gọi định kỳ tới khi
    status 'done'/'error', cùng cách hoạt động status_json() bên
    crawl.py."""
    try:
        run = _call_authed(db_data.get_maintenance_status, run_id)
    except CrawlerAPIError as exc:
        return jsonify({"error": str(exc)}), (exc.status_code or 500)
    if run is None:
        return jsonify({"error": "Không tìm thấy lượt chạy này."}), 404
    return jsonify(run)


@crawl_bp.route("/crawl/maintenance/<string:run_id>/logs.json")
@staff_required
def maintenance_logs_json(run_id):
    """JSON polling khu "Xem log live" tab Bảo trì — cùng cách hoạt
    động logs_json() bên crawl.py."""
    after_id = request.args.get("after_id", "0")
    after_id = int(after_id) if after_id.isdigit() else 0
    try:
        result = _call_authed(db_data.get_maintenance_logs, run_id, after_id=after_id)
    except CrawlerAPIError as exc:
        return jsonify({"error": str(exc)}), (exc.status_code or 500)
    return jsonify(result)


@crawl_bp.route("/crawl/maintenance/latest-log-runs.json")
@staff_required
def maintenance_latest_log_runs_json():
    """JSON — 5 khung "Log live" (mỗi card 1 khung, LUÔN HIỆN cố định)
    gọi lúc tải trang để biết run_id GẦN NHẤT của TỪNG job_type — khác
    latest_log_run() bên crawl.py (chỉ 1 nguồn) ở chỗ trả đủ 5 job_type
    1 lần, xem docstring get_maintenance_latest_log_runs()."""
    try:
        result = _call_authed(db_data.get_maintenance_latest_log_runs)
    except CrawlerAPIError as exc:
        return jsonify({"error": str(exc)}), (exc.status_code or 500)
    return jsonify(result)
