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


def admin_required(view):
    """Chỉ tài khoản role='admin' mới được vào — CHẶT HƠN
    @staff_required (cho cả ss_team). Dùng cho trang "Crawl dữ liệu"
    (08/2026, xem blueprints/crawl.py) — yêu cầu gốc "chỉ có quyền admin
    mới thấy và dùng được", khớp đúng mức POST /crawl ở backend
    (Depends(require_admin), chặt hơn GET /crawl/{run_id} + GET /crawl
    chỉ cần 'ss_team').

    Bọc LẠI @staff_required (không viết trùng lặp check is_authenticated/
    must_change_password) — tự chạy is_staff trước, rồi mới check thêm
    role=='admin'. Cùng cách xử lý JSON (_wants_json()) cho route
    polling trạng thái crawl (GET /crawl/<run_id>/status.json) — thiếu
    bước này sẽ khiến JS fetch().then(res => res.json()) crash nếu
    ss_team thường cố gọi thẳng URL, giống lý do gốc staff_required đã
    né ở docstring phía trên."""
    @wraps(view)
    @staff_required
    def wrapped(*args, **kwargs):
        if current_user.role != "admin":
            if _wants_json():
                return jsonify({"error": "Chức năng này chỉ dành cho tài khoản admin."}), 403
            flash("Chức năng này chỉ dành cho tài khoản admin.", "error")
            return redirect(url_for("jobs.index"))
        return view(*args, **kwargs)
    return wrapped
