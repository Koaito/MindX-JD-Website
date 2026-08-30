"""Profile blueprint — "Trang cá nhân", thêm 08/2026.

Gom các trang liên quan tới hồ sơ CHÍNH NGƯỜI ĐANG ĐĂNG NHẬP (mọi role
— học viên/team SS/admin) vào 1 khu vực có sub-nav dùng chung, thay vì
rải rác nhiều route độc lập như trước (auth.change_password đứng 1
mình, không có nơi nào giới thiệu "đây là 1 phần của hồ sơ cá nhân").

Route trong blueprint này:
  GET/POST /profile           — overview: xem thông tin + đổi full_name
                                 (+ phone/track nếu là học viên).
  GET/POST /profile/security   — đổi mật khẩu. THAY THẾ hẳn
                                 auth.change_password cũ (route cũ giờ
                                 chỉ còn redirect sang đây — xem
                                 blueprints/auth.py — để không vỡ
                                 bookmark/link cũ đang trỏ tới
                                 /change-password).
  GET /profile/activity        — CHỈ team SS/admin (is_staff, chặn bằng
                                 @staff_required). Job/công ty/contact
                                 CHÍNH MÌNH đã tự thêm tay + contact
                                 đang được giao phụ trách — cùng dữ
                                 liệu/logic với staff_activity.detail()
                                 (blueprints/staff_activity.py, trang
                                 "Hoạt động team SS" dành cho admin xem
                                 người khác) nhưng CHỈ xem được của bản
                                 thân. staff_activity.detail() chặn
                                 không cho xem chính mình qua đường đó
                                 nữa (redirect sang đây) — tránh 2 nơi
                                 cùng hiển thị 1 dữ liệu, xem comment ở
                                 đó.

2 mục còn lại của sub-nav — GET /profile/saved-jobs và
GET /profile/applications — KHÔNG nằm trong blueprint này. Logic
nghiệp vụ save/apply/withdraw vẫn thuộc "my stuff" nên 2 route đó vẫn
định nghĩa trong blueprints/my_stuff.py (hàm saved_jobs/my_applications),
chỉ đổi path sang dưới /profile/... và include cùng
_profile_subnav.html để nằm chung sub-nav với 2 trang overview/security
ở đây. URL cũ /saved-jobs, /my-applications vẫn còn, redirect sang URL
mới (xem my_stuff.py) — cùng pattern với auth.change_password ở trên.
Cả 2 chỉ hiện trong sub-nav với học viên (is_student), staff/admin
không thấy.

Sub-nav hiển thị mục nào tuỳ role — xem templates/_profile_subnav.html.
"""

from concurrent.futures import ThreadPoolExecutor

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, logout_user

import backend_auth
import crawler_client as db_data
from backend_auth import BackendAuthError
from constants import INDUSTRIES
from crawler_client import CrawlerAPIError
from helpers import _auth_tokens_from_session, _clear_auth_tokens
from utils.decorators import staff_required

profile_bp = Blueprint("profile", __name__, url_prefix="/profile")

# Dùng riêng cho profile.activity() bên dưới — song song hoá 4 lệnh gọi
# backend độc lập nhau (jobs/companies/contacts-created/contacts-assigned
# của CHÍNH current_user), cùng pattern với _pool trong
# blueprints/staff_activity.py (không import chung pool đó qua module
# khác — 2 blueprint độc lập, mỗi bên tự có pool riêng của mình).
_activity_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="profile-activity-io")


@profile_bp.route("", methods=["GET", "POST"])
@login_required
def index():
    """Overview — xem thông tin tài khoản + form đổi full_name (mọi
    role) và phone/track (chỉ học viên, ẩn hẳn input với staff vì 2
    field này vô nghĩa với team SS/admin — xem UserOut backend)."""
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip() if current_user.is_student else ""
        track = request.form.get("track", "").strip() if current_user.is_student else ""

        if not full_name:
            flash("Vui lòng nhập họ và tên.", "error")
            return render_template(
                "profile_overview.html", industries=INDUSTRIES,
                form={"full_name": full_name, "phone": phone, "track": track},
            )

        access_token, _ = _auth_tokens_from_session()
        try:
            me = backend_auth.update_profile(
                access_token, full_name,
                phone=phone or None, track=track or None,
            )
        except BackendAuthError as exc:
            flash(str(exc), "error")
            return render_template(
                "profile_overview.html", industries=INDUSTRIES,
                form={"full_name": full_name, "phone": phone, "track": track},
            )

        # current_user (BackendUser) được dựng 1 lần lúc load_user() đầu
        # request — sidebar/base.html đang hiển thị full_name CŨ nếu
        # không cập nhật lại object này ngay, dù DB backend đã đổi
        # xong. Gán trực tiếp thay vì bắt người dùng F5/đăng nhập lại.
        current_user.full_name = me.get("full_name") or full_name
        current_user.phone = me.get("phone")
        current_user.track = me.get("track")

        flash("Đã cập nhật thông tin cá nhân.", "success")
        return redirect(url_for("profile.index"))

    form = {
        "full_name": current_user.full_name,
        "phone": current_user.phone or "",
        "track": current_user.track or "",
    }
    return render_template("profile_overview.html", industries=INDUSTRIES, form=form)


@profile_bp.route("/security", methods=["GET", "POST"])
@login_required
def security():
    """Đổi mật khẩu — nội dung nghiệp vụ giống hệt auth.change_password
    cũ (xem blueprints/auth.py, hàm đó giờ chỉ redirect sang đây), chỉ
    đổi URL + đặt trong layout sub-nav của trang cá nhân."""
    if request.method == "POST":
        old_password = request.form.get("old_password", "")
        new_password = request.form.get("new_password", "")
        new_password_confirm = request.form.get("new_password_confirm", "")

        if len(new_password) < 8:
            flash("Mật khẩu mới cần ít nhất 8 ký tự.", "error")
            return render_template("profile_security.html")
        if new_password != new_password_confirm:
            flash("Mật khẩu mới nhập lại không khớp.", "error")
            return render_template("profile_security.html")
        if not current_user.must_change_password and not old_password:
            flash("Vui lòng nhập mật khẩu hiện tại.", "error")
            return render_template("profile_security.html")

        access_token, _ = _auth_tokens_from_session()
        try:
            backend_auth.change_password(
                access_token, new_password,
                old_password=old_password or None,
            )
        except BackendAuthError as exc:
            flash(str(exc), "error")
            return render_template("profile_security.html")

        _clear_auth_tokens()
        logout_user()
        flash("Đã đổi mật khẩu. Vui lòng đăng nhập lại bằng mật khẩu mới.", "success")
        return redirect(url_for("auth.login"))

    return render_template("profile_security.html")


@profile_bp.route("/activity")
@staff_required
def activity():
    """Hoạt động CHÍNH BẠN đã tạo — job/công ty/contact tự thêm tay +
    contact đang được giao phụ trách. @staff_required (không phải
    @login_required như 2 route trên) vì học viên không tạo job/công
    ty/contact, mục "Hoạt động" cũng không hiện với họ trong sub-nav.

    Cùng 4 lệnh gọi backend + cách song song hoá bằng ThreadPoolExecutor
    như staff_activity.detail() (blueprints/staff_activity.py) — chỉ
    khác created_by/assigned_ss_user luôn là current_user.id, không
    nhận tham số ss_user_id từ URL."""
    access_token, _ = _auth_tokens_from_session()
    ss_user_id = current_user.id

    try:
        all_users = backend_auth.list_users(access_token)
    except BackendAuthError as exc:
        flash(str(exc), "error")
        all_users = []
    staff_members = [u for u in all_users if u.get("role") in ("ss_team", "admin")]
    staff_by_id = {u["ss_user_id"]: u for u in all_users}

    jobs_future = _activity_pool.submit(db_data.list_all_jobs, created_by=ss_user_id)
    companies_future = _activity_pool.submit(db_data.list_all_companies, created_by=ss_user_id)
    contacts_created_future = _activity_pool.submit(
        db_data.list_all_contacts, access_token, created_by=ss_user_id,
    )
    contacts_assigned_future = _activity_pool.submit(
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
        "profile_activity.html",
        jobs_created=jobs_created, companies_created=companies_created,
        contacts_created=contacts_created, contacts_assigned=contacts_assigned,
        staff_members=staff_members, staff_by_id=staff_by_id,
        next_url=request.path,
    )
