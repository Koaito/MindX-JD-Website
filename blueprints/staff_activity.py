"""Staff Activity blueprint - monitor team SS member activities"""

from concurrent.futures import ThreadPoolExecutor

from flask import Blueprint, abort, flash, render_template

import backend_auth
import crawler_client as db_data
from backend_auth import BackendAuthError
from constants import CONTACT_STATUSES
from crawler_client import CrawlerAPIError
from helpers import _auth_tokens_from_session
from utils.decorators import staff_required

staff_activity_bp = Blueprint("staff_activity", __name__)

# Dùng CHUNG 1 pool nhỏ cho mọi lượt song song hoá trong blueprint này
# (detail() bên dưới) — max_workers=4 KHỚP ĐÚNG số lệnh gọi độc lập tối
# đa cần chạy cùng lúc ở đây (jobs/companies/contacts-created/contacts-
# assigned). Tạo 1 lần ở module-level (KHÔNG tạo mới mỗi request),
# giống pattern đã áp dụng ở companies.py.
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="staff-activity-io")


@staff_activity_bp.route("/staff-activity")
@staff_required
def index():
    """List all staff members with activity summary"""
    access_token, _ = _auth_tokens_from_session()
    try:
        all_users = backend_auth.list_users(access_token)
    except BackendAuthError as exc:
        flash(str(exc), "error")
        all_users = []
    staff_members = [u for u in all_users if u.get("role") in ("ss_team", "admin")]
    return render_template("staff_activity.html", staff_members=staff_members)


@staff_activity_bp.route("/staff-activity/<string:ss_user_id>")
@staff_required
def detail(ss_user_id):
    """Detail view of one staff member's activities"""
    access_token, _ = _auth_tokens_from_session()

    staff_member = None
    all_users = []
    try:
        all_users = backend_auth.list_users(access_token)
        staff_member = next(
            (u for u in all_users if u["ss_user_id"] == ss_user_id and u.get("role") in ("ss_team", "admin")),
            None,
        )
    except BackendAuthError as exc:
        flash(str(exc), "error")
    if staff_member is None:
        abort(404)

    staff_members = [u for u in all_users if u.get("role") in ("ss_team", "admin")]
    staff_by_id = {u["ss_user_id"]: u for u in all_users}

    # Song song hoá 4 lệnh gọi backend HOÀN TOÀN ĐỘC LẬP NHAU — jobs/
    # companies/contacts(created)/contacts(assigned) đều đã filter theo
    # created_by/assigned_ss_user=ss_user_id (không kéo toàn hệ thống),
    # không phụ thuộc kết quả của nhau. Trước đây gọi tuần tự (tổng thời
    # gian = tổng 4 round-trip), giờ bắn cùng lúc bằng ThreadPoolExecutor
    # (tổng thời gian ≈ round-trip CHẬM NHẤT trong 4 cái). An toàn tuyệt
    # đối — cả 4 đều là GET thuần, không có side-effect. Mỗi future được
    # except riêng để 1 lệnh lỗi không chặn 3 lệnh còn lại.
    jobs_future = _pool.submit(db_data.list_all_jobs, created_by=ss_user_id)
    companies_future = _pool.submit(db_data.list_all_companies, created_by=ss_user_id)
    contacts_created_future = _pool.submit(
        db_data.list_all_contacts, access_token, created_by=ss_user_id,
    )
    contacts_assigned_future = _pool.submit(
        db_data.list_all_contacts, access_token, assigned_ss_user=ss_user_id,
    )

    try:
        jobs_created = jobs_future.result()
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        jobs_created = []

    try:
        companies_created = companies_future.result()
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        companies_created = []

    try:
        contacts_created = contacts_created_future.result()
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        contacts_created = []

    try:
        contacts_assigned = contacts_assigned_future.result()
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        contacts_assigned = []

    return render_template(
        "staff_activity_detail.html", staff_member=staff_member,
        staff_members=staff_members, staff_by_id=staff_by_id,
        jobs_created=jobs_created, companies_created=companies_created,
        contacts_created=contacts_created, contacts_assigned=contacts_assigned,
        statuses=CONTACT_STATUSES,
    )
