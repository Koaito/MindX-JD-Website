"""Staff blueprint - team SS account management"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort
from flask_login import current_user
from utils.decorators import staff_required
import backend_auth
from backend_auth import BackendAuthError
from constants import ROLE_LABELS
from helpers import _auth_tokens_from_session

staff_bp = Blueprint("staff", __name__)


@staff_bp.route("/staff-accounts")
@staff_required
def accounts():
    """List all staff accounts"""
    access_token, _ = _auth_tokens_from_session()
    try:
        users = backend_auth.list_users(access_token)
    except BackendAuthError as exc:
        flash(str(exc), "error")
        users = []

    new_account = session.pop("new_staff_account", None)

    return render_template(
        "staff_accounts.html", users=users, role_labels=ROLE_LABELS,
        roles=list(ROLE_LABELS.keys()), new_account=new_account,
    )


@staff_bp.route("/staff-accounts/add", methods=["GET", "POST"])
@staff_required
def add():
    """Add new staff account"""
    if current_user.role != "admin":
        flash("Chỉ tài khoản admin mới tạo được tài khoản mới.", "error")
        return redirect(url_for("staff.accounts"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        role = request.form.get("role", "ss_team")

        error = None
        if not full_name or not email:
            error = "Vui lòng điền đầy đủ họ tên và email."
        elif role not in ROLE_LABELS:
            error = "Role không hợp lệ."

        if error:
            flash(error, "error")
            return render_template("staff_account_add.html", role_labels=ROLE_LABELS, form=request.form)

        access_token, _ = _auth_tokens_from_session()
        try:
            created = backend_auth.create_user(access_token, full_name, email, role)
        except BackendAuthError as exc:
            flash(str(exc), "error")
            return render_template("staff_account_add.html", role_labels=ROLE_LABELS, form=request.form)

        session["new_staff_account"] = {
            "full_name": created["full_name"],
            "email": created["email"],
            "role": created["role"],
            "temp_password": created["temp_password"],
        }
        flash(f"Đã tạo tài khoản cho {full_name}.", "success")
        return redirect(url_for("staff.accounts"))

    return render_template("staff_account_add.html", role_labels=ROLE_LABELS, form={})


@staff_bp.route("/staff-accounts/<string:ss_user_id>/role", methods=["POST"])
@staff_required
def update_role(ss_user_id):
    """Update staff role"""
    if current_user.role != "admin":
        flash("Chỉ tài khoản admin mới đổi được role.", "error")
        return redirect(url_for("staff.accounts"))

    role = request.form.get("role", "")
    if role not in ROLE_LABELS:
        abort(400)

    access_token, _ = _auth_tokens_from_session()
    try:
        backend_auth.update_user_role(access_token, ss_user_id, role)
        flash("Đã cập nhật role.", "success")
    except BackendAuthError as exc:
        flash(str(exc), "error")
    return redirect(url_for("staff.accounts"))


@staff_bp.route("/staff-accounts/<string:ss_user_id>/active-status", methods=["POST"])
@staff_required
def update_active_status(ss_user_id):
    """Update staff active status"""
    if current_user.role != "admin":
        flash("Chỉ tài khoản admin mới khoá/mở được tài khoản.", "error")
        return redirect(url_for("staff.accounts"))

    access_token, _ = _auth_tokens_from_session()
    is_active_str = request.form.get("is_active", "true")
    is_active = is_active_str.lower() == "true"
    try:
        backend_auth.update_user_active_status(access_token, ss_user_id, is_active)
        flash("Đã cập nhật trạng thái tài khoản.", "success")
    except BackendAuthError as exc:
        flash(str(exc), "error")
    return redirect(url_for("staff.accounts"))
