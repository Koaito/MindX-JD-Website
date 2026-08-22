"""Authentication blueprint - register, login, logout, password management"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user

from auth import BackendUser
import backend_auth
from backend_auth import BackendAuthError
from constants import INDUSTRIES
from helpers import _auth_tokens_from_session, _clear_auth_tokens, _store_auth_tokens

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("jobs.index"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")
        phone = request.form.get("phone", "").strip()
        track = request.form.get("track", "")

        error = None
        if not full_name or not email or not password:
            error = "Vui lòng điền đầy đủ họ tên, email và mật khẩu."
        elif len(password) < 8:
            error = "Mật khẩu cần ít nhất 8 ký tự."
        elif password != password_confirm:
            error = "Mật khẩu nhập lại không khớp."

        if error:
            flash(error, "error")
            return render_template("register.html", industries=INDUSTRIES, form=request.form)

        try:
            backend_auth.register(full_name, email, password, phone, track)
        except BackendAuthError as exc:
            flash(str(exc), "error")
            return render_template("register.html", industries=INDUSTRIES, form=request.form)

        flash(
            f"Đã tạo tài khoản cho {full_name}. Vui lòng kiểm tra email ({email}) "
            "và bấm vào link xác thực trước khi đăng nhập.",
            "success",
        )
        return redirect(url_for("auth.login"))

    return render_template("register.html", industries=INDUSTRIES, form={})


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index") if current_user.is_staff else url_for("jobs.index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        try:
            token_data = backend_auth.login(email, password)
        except BackendAuthError as exc:
            flash(str(exc), "error")
            return render_template("login.html", show_resend=exc.email_not_verified, resend_email=email)

        _store_auth_tokens(token_data["access_token"], token_data["refresh_token"])
        try:
            me = backend_auth.get_me(token_data["access_token"])
        except BackendAuthError as exc:
            _clear_auth_tokens()
            flash(str(exc), "error")
            return render_template("login.html")

        user = BackendUser(me)
        login_user(user)
        flash(f"Chào mừng trở lại, {user.full_name}!", "success")

        if user.is_staff and user.must_change_password:
            flash("Đây là lần đăng nhập đầu — vui lòng đặt mật khẩu mới.", "error")
            return redirect(url_for("auth.change_password"))

        next_url = request.args.get("next")
        return redirect(next_url or (url_for("dashboard.index") if user.is_staff else url_for("jobs.index")))

    return render_template("login.html")


@auth_bp.route("/resend-verification", methods=["POST"])
def resend_verification():
    email = request.form.get("email", "").strip().lower()
    if email:
        try:
            backend_auth.resend_verification(email)
        except BackendAuthError as exc:
            flash(str(exc), "error")
            return redirect(url_for("auth.login"))
    flash("Nếu email tồn tại và chưa xác thực, link mới đã được gửi — kiểm tra hộp thư.", "success")
    return redirect(url_for("auth.login"))


@auth_bp.route("/verify-email")
def verify_email():
    """Backend redirect(302) tới đây SAU KHI đã tự xử lý token"""
    status = request.args.get("status", "invalid")
    if status not in ("success", "expired", "invalid"):
        status = "invalid"
    return render_template("verify_email.html", status=status)


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Bước 1/2 của luồng quên mật khẩu"""
    if current_user.is_authenticated:
        return redirect(url_for("jobs.index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not email:
            flash("Vui lòng nhập email.", "error")
            return render_template("forgot_password.html", email=email)
        try:
            result = backend_auth.forgot_password(email)
            flash(result.get("message", "Nếu email này có tài khoản, link đặt lại mật khẩu đã được gửi."), "success")
        except BackendAuthError as exc:
            flash(str(exc), "error")
            return render_template("forgot_password.html", email=email)
        return redirect(url_for("auth.login"))

    return render_template("forgot_password.html", email="")


@auth_bp.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    """Bước 2/2 — link trong email trỏ về đây kèm ?token=..."""
    if current_user.is_authenticated:
        return redirect(url_for("jobs.index"))

    token = request.args.get("token", "").strip() if request.method == "GET" else request.form.get("token", "").strip()
    if not token:
        flash("Link đặt lại mật khẩu không hợp lệ — thiếu token. Vui lòng dùng đúng link trong email.", "error")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        new_password = request.form.get("new_password", "")
        new_password_confirm = request.form.get("new_password_confirm", "")

        if len(new_password) < 8:
            flash("Mật khẩu mới cần ít nhất 8 ký tự.", "error")
            return render_template("reset_password.html", token=token)
        if new_password != new_password_confirm:
            flash("Mật khẩu mới nhập lại không khớp.", "error")
            return render_template("reset_password.html", token=token)

        try:
            backend_auth.reset_password(token, new_password)
        except BackendAuthError as exc:
            flash(str(exc), "error")
            return redirect(url_for("auth.forgot_password"))

        flash("Đã đặt lại mật khẩu. Vui lòng đăng nhập bằng mật khẩu mới.", "success")
        return redirect(url_for("auth.login"))

    return render_template("reset_password.html", token=token)


@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        old_password = request.form.get("old_password", "")
        new_password = request.form.get("new_password", "")
        new_password_confirm = request.form.get("new_password_confirm", "")

        if len(new_password) < 8:
            flash("Mật khẩu mới cần ít nhất 8 ký tự.", "error")
            return render_template("change_password.html")
        if new_password != new_password_confirm:
            flash("Mật khẩu mới nhập lại không khớp.", "error")
            return render_template("change_password.html")
        if not current_user.must_change_password and not old_password:
            flash("Vui lòng nhập mật khẩu hiện tại.", "error")
            return render_template("change_password.html")

        access_token, refresh_token = _auth_tokens_from_session()
        try:
            backend_auth.change_password(
                access_token, new_password,
                old_password=old_password or None,
            )
        except BackendAuthError as exc:
            flash(str(exc), "error")
            return render_template("change_password.html")

        _clear_auth_tokens()
        logout_user()
        flash("Đã đổi mật khẩu. Vui lòng đăng nhập lại bằng mật khẩu mới.", "success")
        return redirect(url_for("auth.login"))

    return render_template("change_password.html")


@auth_bp.route("/logout")
@login_required
def logout():
    _, refresh_token = _auth_tokens_from_session()
    if refresh_token:
        backend_auth.logout(refresh_token)
    _clear_auth_tokens()
    logout_user()
    flash("Đã đăng xuất.", "success")
    return redirect(url_for("jobs.index"))
