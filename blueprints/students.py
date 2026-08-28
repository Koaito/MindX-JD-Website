"""Students blueprint - student activity monitoring and CV download"""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

import backend_auth
from backend_auth import BackendAuthError
from helpers import _auth_tokens_from_session
from utils.decorators import staff_required

students_bp = Blueprint("students", __name__)


@students_bp.route("/student-activity")
@staff_required
def activity_index():
    """List all students with activity summary"""
    access_token, _ = _auth_tokens_from_session()
    try:
        all_users = backend_auth.list_users(access_token)
    except BackendAuthError as exc:
        flash(str(exc), "error")
        all_users = []
    students = [u for u in all_users if u.get("role") == "user"]
    return render_template("student_activity.html", students=students)


@students_bp.route("/students/cv/<string:application_id>")
@login_required
def cv_download(application_id):
    """Staff click link tải CV → redirect tới Signed URL do backend cấp.

    (Bug cũ: bản trước gọi backend_auth.get_cv() — hàm này không tồn
    tại — và coi kết quả như dict {"content", "filename"} để stream
    trực tiếp. Hàm thật là get_cv_signed_url(), trả về 1 CHUỖI URL, cần
    redirect tới đó chứ không phải đọc bytes. Khôi phục đúng logic gốc
    từ app_old_2061_lines.py.)"""
    if not current_user.is_staff:
        abort(403)
    access_token, _ = _auth_tokens_from_session()
    try:
        signed_url = backend_auth.get_cv_signed_url(access_token, application_id)
        if not signed_url:
            flash("Không thể tạo link tải CV lúc này.", "error")
            return redirect(request.referrer or url_for("students.activity_index"))
        return redirect(signed_url)
    except BackendAuthError as exc:
        flash(str(exc), "error")
        return redirect(request.referrer or url_for("students.activity_index"))


@students_bp.route("/student-activity/<string:ss_user_id>")
@staff_required
def activity_detail(ss_user_id):
    """Detail view of one student's activity"""
    access_token, _ = _auth_tokens_from_session()
    try:
        all_users = backend_auth.list_users(access_token)
        student = next((u for u in all_users if u.get("ss_user_id") == ss_user_id), None)
        
        if not student or student.get("role") != "user":
            flash("Không tìm thấy học viên này.", "error")
            return redirect(url_for("students.activity_index"))
        
        applications = backend_auth.list_applications_of_user(access_token, ss_user_id)
        saved_jobs = backend_auth.list_saved_jobs_of_user(access_token, ss_user_id)
    except BackendAuthError as exc:
        flash(str(exc), "error")
        return redirect(url_for("students.activity_index"))
    
    return render_template(
        "student_activity_detail.html",
        student=student,
        applications=applications,
        saved_jobs=saved_jobs,
    )
