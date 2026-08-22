"""Decorators for route protection"""

from functools import wraps
from flask import flash, jsonify, redirect, request, url_for
from flask_login import current_user


def _wants_json():
    """True nếu request là gọi AJAX tới 1 JSON endpoint (vd: fetch() lấy
    danh sách company gợi ý ở _dm_import.html), không phải người dùng bấm
    link/điều hướng trình duyệt bình thường.

    Dựa vào header X-Requested-With: các fetch() gọi JSON endpoint trong
    codebase này tự set header này (xem _dm_import.html) — khác jQuery
    $.ajax vốn tự động thêm header đó, fetch() thì không nên phải set tay.
    Không dùng Accept header vì fetch() mặc định gửi Accept: */* (không
    phân biệt được với điều hướng trang bình thường của trình duyệt)."""
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def staff_required(view):
    """Chỉ tài khoản team SS (role ss_team/admin) mới được vào; còn lại
    bị chặn. Nếu tài khoản đang phải đổi mật khẩu lần đầu
    (must_change_password=True), ép về /change-password trước — trừ
    chính route change_password/logout để không tự khoá lối thoát.

    Với các route trả JSON (vd: company_suggestions) mà bị chặn ở đây,
    trả thẳng JSON lỗi thay vì redirect sang trang HTML login/error —
    redirect trả về HTML khiến fetch().then(res => res.json()) phía
    client crash với lỗi "Unexpected token '<'" vì cố parse HTML như
    JSON. Áp dụng chung cho MỌI route dùng @staff_required (không riêng
    company_suggestions) để các JSON endpoint thêm sau này tự động được
    bảo vệ đúng cách, không phải nhớ tự xử lý lại mỗi nơi."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            if _wants_json():
                return jsonify({"error": "Vui lòng đăng nhập để tiếp tục."}), 401
            flash("Vui lòng đăng nhập để tiếp tục.", "error")
            return redirect(url_for("auth.login"))
        if not current_user.is_staff:
            if _wants_json():
                return jsonify({"error": "Chức năng này chỉ dành cho tài khoản team SS."}), 403
            flash("Chức năng này chỉ dành cho tài khoản team SS.", "error")
            return redirect(url_for("jobs.index"))
        if current_user.must_change_password and view.__name__ not in ("change_password", "logout"):
            if _wants_json():
                return jsonify({"error": "Vui lòng đổi mật khẩu trước khi tiếp tục."}), 403
            flash("Vui lòng đổi mật khẩu trước khi tiếp tục.", "error")
            return redirect(url_for("auth.change_password"))
        return view(*args, **kwargs)
    return wrapped
