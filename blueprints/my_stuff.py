"""My Stuff blueprint - student's saved jobs and applications"""

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

import backend_auth
import crawler_client as db_data
from backend_auth import BackendAuthError
from crawler_client import CrawlerAPIError
from helpers import _auth_tokens_from_session

my_stuff_bp = Blueprint("my_stuff", __name__)


@my_stuff_bp.route("/jobs/<string:job_id>/save", methods=["POST"])
@login_required
def job_toggle_save(job_id):
    if current_user.is_staff:
        flash("Tài khoản team SS không dùng để lưu job.", "error")
        return redirect(request.referrer or url_for("jobs.index"))

    access_token, _ = _auth_tokens_from_session()
    try:
        backend_auth.save_job(access_token, job_id)
        flash("Đã lưu job vào danh sách của bạn.", "success")
    except BackendAuthError as exc:
        if exc.status_code == 409:
            try:
                backend_auth.unsave_job(access_token, job_id)
                flash("Đã bỏ lưu job.", "success")
            except BackendAuthError as exc2:
                flash(str(exc2), "error")
        else:
            flash(str(exc), "error")
    return redirect(request.referrer or url_for("jobs.index"))


@my_stuff_bp.route("/jobs/<job_id>/toggle-save.json", methods=["POST"])
@login_required
def job_toggle_save_json(job_id):
    """JSON version for AJAX toggle"""
    if current_user.is_staff:
        return jsonify(ok=False, message="Tài khoản team SS không dùng để lưu job."), 403

    access_token, _ = _auth_tokens_from_session()
    try:
        backend_auth.save_job(access_token, job_id)
        return jsonify(ok=True, saved=True, message="Đã lưu job vào danh sách của bạn.")
    except BackendAuthError as exc:
        if exc.status_code == 409:
            try:
                backend_auth.unsave_job(access_token, job_id)
                return jsonify(ok=True, saved=False, message="Đã bỏ lưu job.")
            except BackendAuthError as exc2:
                return jsonify(ok=False, message=str(exc2)), 400
        return jsonify(ok=False, message=str(exc)), 400


@my_stuff_bp.route("/profile/saved-jobs")
@login_required
def saved_jobs():
    if current_user.is_staff:
        return redirect(url_for("dashboard.index"))

    access_token, _ = _auth_tokens_from_session()
    try:
        saved = backend_auth.list_my_saved_jobs(access_token)
    except BackendAuthError as exc:
        flash(str(exc), "error")
        saved = []

    jobs = []
    for s in saved:
        try:
            job = db_data.get_job(s["job_id"])
        except CrawlerAPIError:
            job = None
        if job:
            jobs.append(job)
    return render_template("saved_jobs.html", jobs=jobs)


@my_stuff_bp.route("/saved-jobs")
@login_required
def saved_jobs_legacy():
    """08/2026 — URL cũ trước khi dời vào sub-nav trang cá nhân. Giữ
    lại để không vỡ bookmark/link cũ đang trỏ /saved-jobs (endpoint
    name my_stuff.saved_jobs không đổi, chỉ path đổi sang
    /profile/saved-jobs — xem _profile_subnav.html)."""
    return redirect(url_for("my_stuff.saved_jobs"))


@my_stuff_bp.route("/jobs/<string:job_id>/apply", methods=["POST"])
@login_required
def job_apply(job_id):
    if current_user.is_staff:
        flash("Tài khoản team SS không dùng để ứng tuyển.", "error")
        return redirect(url_for("jobs.detail", job_id=job_id))

    access_token, _ = _auth_tokens_from_session()
    note = request.form.get("note", "").strip()
    
    cv_file = request.files.get("cv_file")
    if not cv_file or cv_file.filename == "":
        flash("Vui lòng đính kèm file CV (.pdf) khi ứng tuyển.", "error")
        return redirect(url_for("jobs.detail", job_id=job_id))
    
    if not cv_file.filename.lower().endswith(".pdf"):
        flash("Chỉ chấp nhận file CV định dạng PDF (.pdf).", "error")
        return redirect(url_for("jobs.detail", job_id=job_id))

    cv_bytes = cv_file.read()
    if len(cv_bytes) > 5 * 1024 * 1024:
        flash("File CV không được vượt quá 5MB.", "error")
        return redirect(url_for("jobs.detail", job_id=job_id))
    
    try:
        application = backend_auth.apply_to_job(
            access_token, job_id, note=note,
            cv_file_bytes=cv_bytes, cv_filename=cv_file.filename
        )
        flash(
            f"Đã ghi nhận ứng tuyển \"{application['job_title']}\" tại "
            f"{application['company_name']}. Team SS sẽ liên hệ bạn sớm.",
            "success",
        )
    except BackendAuthError as exc:
        if exc.status_code == 409:
            flash("Bạn đã ứng tuyển job này rồi.", "success")
        else:
            flash(str(exc), "error")
    return redirect(url_for("jobs.detail", job_id=job_id))


@my_stuff_bp.route("/jobs/<string:job_id>/withdraw", methods=["POST"])
@login_required
def job_withdraw(job_id):
    """Huỷ ứng tuyển"""
    if current_user.is_staff:
        abort(404)
    access_token, _ = _auth_tokens_from_session()
    note = request.form.get("note", "").strip()
    try:
        backend_auth.withdraw_application(access_token, job_id, note=note)
        flash("Đã huỷ ứng tuyển.", "success")
    except BackendAuthError as exc:
        flash(str(exc), "error")
    return redirect(request.referrer or url_for("my_stuff.my_applications"))


@my_stuff_bp.route("/profile/applications")
@login_required
def my_applications():
    if current_user.is_staff:
        return redirect(url_for("dashboard.index"))
    access_token, _ = _auth_tokens_from_session()
    try:
        applications = backend_auth.list_my_applications(access_token)
    except BackendAuthError as exc:
        flash(str(exc), "error")
        applications = []
    return render_template("my_applications.html", applications=applications)


@my_stuff_bp.route("/my-applications")
@login_required
def my_applications_legacy():
    """08/2026 — URL cũ trước khi dời vào sub-nav trang cá nhân. Giữ
    lại để không vỡ bookmark/link cũ đang trỏ /my-applications (endpoint
    name my_stuff.my_applications không đổi, chỉ path đổi sang
    /profile/applications — xem _profile_subnav.html)."""
    return redirect(url_for("my_stuff.my_applications"))
