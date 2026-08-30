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

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, logout_user

import backend_auth
from backend_auth import BackendAuthError
from constants import INDUSTRIES
from helpers import _auth_tokens_from_session, _clear_auth_tokens

profile_bp = Blueprint("profile", __name__, url_prefix="/profile")


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
