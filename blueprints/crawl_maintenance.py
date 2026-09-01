"""Route cho tab "Bảo trì dữ liệu" ở trang "Vận hành dữ liệu" (08/2026,
xem lịch sử trao đổi "phương án B — generic runner dùng chung"). CHỈ
admin bấm chạy được (@admin_required, khớp POST /maintenance/{job_type}
chỉ admin) — xem utils/decorators.py.

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
from helpers import _call_authed
from utils.decorators import admin_required


def _active_maintenance_runs() -> dict:
    """Trả {job_type: run} cho các job_type ĐANG có 1 lượt
    'queued'/'running' — CHỈ 2 lần gọi API TỔNG CỘNG (không phải 2 lần
    x 5 job_type như _active_run_for_source() bên crawl.py, vì
    list_maintenance_runs() ở đây lọc ĐƯỢC theo status nhưng KHÔNG theo
    job_type khi để trống, nên gom hết job_type trong 1 lần gọi/status
    rồi tự group ở đây) — ưu tiên 'running' hơn 'queued' cho job_type
    nào (hiếm khi) có cả 2 (không thể xảy ra thật do UNIQUE INDEX phía
    backend, nhưng vẫn xử lý an toàn theo đúng thứ tự ưu tiên).

    Tự gọi _call_authed() (tự refresh khi 401) — DÙNG Ở tab
    'maintenance' (index()::_maintenance_tab_context(), CHỈ gọi hàm này
    1 mình trong request đó, refresh riêng ở đây an toàn). KHÔNG dùng
    hàm này ở tab 'history' — xem _active_maintenance_runs_raw() bên
    dưới, lý do trong docstring của nó."""
    active = {}
    for status in ("queued", "running"):
        result = _call_authed(db_data.list_maintenance_runs, status=status, limit=10)
        for run in result["items"]:
            active[run["job_type"]] = run
    return active


def _active_maintenance_runs_raw(token) -> dict:
    """Như _active_maintenance_runs() nhưng nhận TOKEN TRUYỀN TAY, gọi
    thẳng db_data.list_maintenance_runs(token, ...), KHÔNG qua
    _call_authed() — dùng ở tab 'history'
    (crawl.py::_history_tab_context()), nơi cần gộp NHIỀU lệnh gọi
    backend (bảng lịch sử crawl, list_users, bảng lịch sử bảo trì,
    poll đang chạy crawl, poll đang chạy bảo trì) vào 1 "wave" refresh-
    once DUY NHẤT — để mỗi lệnh tự refresh riêng khi 401 sẽ lặp lại
    đúng bug đã sửa (backend_auth.refresh() xoay vòng refresh_token,
    nhiều refresh độc lập trong 1 request dùng refresh_token cũ đã bị
    vô hiệu → thu hồi session → bị kick, xem docstring
    _maintenance_history_context_raw())."""
    active = {}
    for status in ("queued", "running"):
        result = db_data.list_maintenance_runs(token, status=status, limit=10)
        for run in result["items"]:
            active[run["job_type"]] = run
    return active


def _maintenance_history_context_raw(runs_result, all_users, page, per_page,
                                      *, job_type, status, triggered_by, had_error) -> dict:
    """Build context cho bảng "Lịch sử bảo trì" TỪ DỮ LIỆU ĐÃ FETCH SẴN
    (runs_result = kết quả list_maintenance_runs, all_users = kết quả
    list_users) — KHÔNG tự gọi backend, KHÔNG tự refresh token.

    THAY THẾ bản cũ _maintenance_history_context(page, per_page) (từng
    tự gọi _call_authed()/backend_auth.list_users() bên trong) — bản cũ
    bị BỎ vì đó chính là bug refresh-token-nhiều-lần: tab "history" cần
    gọi backend 4 lần trong 1 request (2 cho bảng crawl + 2 cho bảng
    này), để mỗi lệnh tự refresh riêng khi 401 nghĩa là có thể refresh
    tới 4 lần độc lập trong cùng 1 request — backend_auth.refresh()
    XOAY VÒNG refresh_token (mỗi lần vô hiệu hoá refresh_token cũ), nên
    refresh lần 2 trở đi (dùng refresh_token đọc từ session LÚC ĐẦU,
    đã bị lần 1 vô hiệu) bị coi là reuse → thu hồi session → đúng chuỗi
    lỗi "đang chạy job thì bị kick" đã từng điều tra.

    Giờ nơi gọi DUY NHẤT (blueprints/crawl.py::_history_tab_context())
    tự fetch cả 4 lệnh bằng CÙNG 1 token trong 1 "wave", refresh ĐÚNG 1
    LẦN nếu cần, rồi mới gọi hàm này để build phần context còn lại
    (label, filters, phân trang...) từ dữ liệu đã có — hàm này thuần
    xử lý dữ liệu, không I/O, nên không có gì để refresh nữa."""
    if had_error or runs_result is None:
        runs, total_runs = [], 0
    else:
        runs = runs_result["items"]
        total_runs = runs_result["total"]
    total_pages = max(1, math.ceil(total_runs / per_page))
    page = min(page, total_pages)

    admin_members = [u for u in (all_users or []) if u.get("role") == "admin"]

    return {
        "maintenance_jobs": db_data.MAINTENANCE_JOBS,
        "job_labels": db_data.MAINTENANCE_JOB_LABELS,
        "runs": runs, "total_runs": total_runs, "page": page,
        "total_pages": total_pages, "per_page": per_page,
        "status_labels": db_data.MAINTENANCE_STATUS_LABELS,
        "admin_members": admin_members,
        "filters": {"job_type": job_type, "status": status, "triggered_by": triggered_by},
        "pagination_filters": {k: v for k, v in
                                {"m_job_type": job_type, "m_status": status,
                                 "m_triggered_by": triggered_by}.items() if v},
    }


def _maintenance_tab_context() -> dict:
    """Build TOÀN BỘ context cho tab='maintenance' — gọi từ
    blueprints/crawl.py::index() khi tab=maintenance, tách hàm riêng để
    file đó không phải biết chi tiết bên trong (đối xứng cách index()
    tự build context tab='crawl' ngay trong nó, khác biệt CHỦ Ý vì
    context tab maintenance cần nhiều field riêng — tách cho rõ).

    Từ 08/2026 CHỈ còn Khu A (kích hoạt) + Khu B (đang chạy) — Khu C
    (lịch sử) đã chuyển sang tab "history" riêng, xem
    _maintenance_history_context_raw() ở trên."""
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

    return {
        "maintenance_jobs": db_data.MAINTENANCE_JOBS,
        "job_labels": db_data.MAINTENANCE_JOB_LABELS,
        "stat_labels_by_job": db_data.MAINTENANCE_STAT_LABELS,
        "require_limit_job_types": db_data.MAINTENANCE_JOB_TYPES_REQUIRE_LIMIT,
        "check_expired_job_type": db_data.MAINTENANCE_CHECK_EXPIRED_JOB_TYPE,
        "active_runs": active_runs,
        "latest_log_runs": latest_log_runs,
        # status_labels: KHÔNG còn dùng để render Khu C ở đây (đã
        # chuyển sang tab "history") nhưng JS Khu B (script cuối
        # _maintenance_tab.html, biến STATUS_LABELS) vẫn cần để hiện
        # đúng nhãn trạng thái lúc poll/cập nhật card "đang chạy" —
        # thiếu biến này JS lỗi (Undefined không serialize được qua
        # |tojson) và CẢ TRANG CRASH 500, không chỉ mất mỗi style.
        # Cùng bug/cùng cách sửa như tab 'crawl' (xem index() —
        # comment "status_labels/stat_labels: KHÔNG còn dùng...").
        "status_labels": db_data.MAINTENANCE_STATUS_LABELS,
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
@admin_required
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
@admin_required
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


@crawl_bp.route("/crawl/maintenance/logs-batch.json")
@admin_required
def maintenance_logs_batch_json():
    """JSON — GỘP log MỚI của NHIỀU run_id (mỗi job_type 1 run_id) 1
    lần gọi (09/2026, xem lịch sử trao đổi "gộp 5 request logs.json
    thành 1") — thay 5 lần gọi maintenance_logs_json() riêng biệt của
    JS (1 khung "Log live"/job_type, cùng chu kỳ poll) bằng 1 route duy
    nhất, proxy thẳng GET /maintenance/logs-batch phía backend.

    Query string: `run_ids`/`after_ids` — 2 chuỗi phân cách dấu phẩy,
    khớp theo VỊ TRÍ (giữ nguyên định dạng phía backend, không giải mã/
    mã hoá lại ở tầng Flask này để tránh sai lệch thứ tự)."""
    run_ids = request.args.get("run_ids", "")
    after_ids = request.args.get("after_ids", "")
    run_id_list = [r for r in run_ids.split(",") if r]
    after_id_list = [a for a in after_ids.split(",") if a]

    if not run_id_list:
        return jsonify({})
    if len(run_id_list) != len(after_id_list):
        return jsonify({"error": "run_ids và after_ids phải cùng số lượng."}), 400

    run_after_ids = {}
    for rid, aid in zip(run_id_list, after_id_list):
        run_after_ids[rid] = int(aid) if aid.isdigit() else 0

    try:
        result = _call_authed(db_data.get_maintenance_logs_batch, run_after_ids)
    except CrawlerAPIError as exc:
        return jsonify({"error": str(exc)}), (exc.status_code or 500)
    return jsonify(result)


@crawl_bp.route("/crawl/maintenance/latest-log-runs.json")
@admin_required
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
