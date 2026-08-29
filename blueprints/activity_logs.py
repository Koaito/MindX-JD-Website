"""Activity Logs blueprint - system-wide activity tracking"""

import math
from concurrent.futures import ThreadPoolExecutor

from flask import Blueprint, flash, redirect, render_template, request, url_for

import backend_auth
import crawler_client as db_data
from backend_auth import BackendAuthError
from crawler_client import CrawlerAPIError
from helpers import _auth_tokens_from_session, _call_authed, _paginate_args
from utils.decorators import staff_required

activity_logs_bp = Blueprint("activity_logs", __name__)

# Dùng CHUNG 1 pool nhỏ cho mọi lượt song song hoá trong blueprint này
# (logs() bên dưới) — max_workers=3 KHỚP ĐÚNG số lệnh gọi độc lập tối
# đa cần chạy cùng lúc ở đây (audit logs/companies dropdown/staff
# dropdown). Tạo 1 lần ở module-level (KHÔNG tạo mới mỗi request),
# giống pattern đã áp dụng ở companies.py.
_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="activity-logs-io")


def _list_all_companies():
    """Lấy TOÀN BỘ công ty để dùng dropdown filter (xem app_old_2061_lines.py:1350)"""
    return db_data.list_all_companies()


@activity_logs_bp.route("/activity-logs")
@staff_required
def logs():
    """Trang lịch sử thao tác — 2 tab ?view=auto (tự động) / ?view=manual
    (thủ công), filter theo entity_type/company/actor. Khác /staff-activity
    (tổng hợp JD/công ty/contact theo người tạo) — đây là nhật ký TỪNG thao
    tác chi tiết theo thời gian, có note."""
    view = request.args.get("view", "auto")
    if view not in ("auto", "manual"):
        view = "auto"
    entity_type = request.args.get("entity_type", "")
    company_id = request.args.get("company_id", "")
    actor_id = request.args.get("actor_id", "")

    access_token, _ = _auth_tokens_from_session()

    # Pagination
    page, per_page = _paginate_args(50)  # 50 logs/trang
    offset = (page - 1) * per_page

    # Song song hoá 3 lệnh gọi backend ĐỘC LẬP NHAU — list_audit_logs
    # (đã filter + phân trang theo view/entity_type/company/actor),
    # danh sách công ty và danh sách staff (2 dropdown filter) KHÔNG
    # phụ thuộc kết quả của nhau. Trước đây gọi tuần tự (tổng thời gian
    # = tổng 3 round-trip), giờ bắn cùng lúc bằng ThreadPoolExecutor
    # (tổng thời gian ≈ round-trip CHẬM NHẤT trong 3 cái). An toàn
    # tuyệt đối — cả 3 đều là GET thuần, không có side-effect. Mỗi
    # future được except riêng để 1 lệnh lỗi không chặn 2 lệnh còn lại.
    logs_future = _pool.submit(
        db_data.list_audit_logs,
        access_token, view=view, entity_type=entity_type,
        company_id=company_id, actor_id=actor_id,
        limit=per_page, offset=offset,
    )
    companies_future = _pool.submit(_list_all_companies)
    users_future = _pool.submit(backend_auth.list_users, access_token)

    try:
        result = logs_future.result()
        logs = result["items"]
        total_logs = result["total"]
        total_pages = max(1, math.ceil(total_logs / per_page))
        page = min(page, total_pages)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        logs, total_logs, total_pages, page = [], 0, 1, 1

    # Dropdown công ty/staff cho filter
    try:
        companies = companies_future.result()
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        companies = []
    try:
        all_users = users_future.result()
        staff_members = [u for u in all_users if u.get("role") in ("ss_team", "admin")]
    except BackendAuthError as exc:
        flash(str(exc), "error")
        staff_members = []

    entity_types = list(db_data.ENTITY_TYPE_MAP.values())  # ["JD", "Công ty", "Người liên hệ"]

    return render_template(
        "activity_logs.html", logs=logs, view=view,
        entity_types=entity_types, companies=companies, staff_members=staff_members,
        filters={"entity_type": entity_type, "company_id": company_id, "actor_id": actor_id},
        pagination_filters={k: v for k, v in
                             {"entity_type": entity_type, "company_id": company_id, "actor_id": actor_id}.items() if v},
        total_logs=total_logs, page=page, total_pages=total_pages, per_page=per_page,
    )


@activity_logs_bp.route("/activity-logs/<string:log_id>/note", methods=["POST"])
@staff_required
def update_note(log_id):
    """Sửa note của 1 log — backend CHỈ cho phép actor gốc sửa"""
    note = request.form.get("note", "").strip()
    access_token, _ = _auth_tokens_from_session()
    try:
        _call_authed(db_data.update_audit_log_note, log_id, note)
        flash("Đã cập nhật ghi chú.", "success")
    except CrawlerAPIError as exc:
        if exc.status_code == 403:
            flash("Bạn không có quyền sửa ghi chú của người khác.", "error")
        else:
            flash(str(exc), "error")
    return redirect(url_for("activity_logs.logs", view=request.args.get("view", "auto")))
