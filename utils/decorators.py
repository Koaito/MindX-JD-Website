"""Decorators for route protection"""

from functools import wraps
from flask import flash, redirect, url_for
from flask_login import current_user

def staff_required(view):
    """Chỉ tài khoản team SS (role ss_team/admin) mới được vào; còn lại
    bị chặn. Nếu tài khoản đang phải đổi mật khẩu lần đầu
    (must_change_password=True), ép về /change-password trước — trừ
    chính route change_password/logout để không tự khoá lối thoát."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("Vui lòng đăng nhập để tiếp tục.", "error")
            return redirect(url_for("auth.login"))
        if not current_user.is_staff:
            flash("Chức năng này chỉ dành cho tài khoản team SS.", "error")
            return redirect(url_for("jobs.index"))
        if current_user.must_change_password and view.__name__ not in ("change_password", "logout"):
            flash("Vui lòng đổi mật khẩu trước khi tiếp tục.", "error")
            return redirect(url_for("auth.change_password"))
        return view(*args, **kwargs)
    return wrapped
