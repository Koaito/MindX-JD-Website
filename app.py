import os
from datetime import datetime
from functools import wraps

from env_loader import load_env_file

load_env_file()

from flask import Flask, render_template, request, redirect, url_for, flash, abort, session
from flask_login import (
    LoginManager, login_user, logout_user,
    login_required, current_user,
)

from types import SimpleNamespace

from auth import BackendUser
import crawler_client as db_data
from crawler_client import CrawlerAPIError
import backend_auth
from backend_auth import BackendAuthError

app = Flask(__name__, static_folder="public", static_url_path="")
# ⚠️ Đổi 08/2026 để khớp Vercel: Vercel khuyến cáo KHÔNG serve static qua
# app.static_folder mặc định của Flask khi deploy — mà phải để file tĩnh
# trong thư mục public/ ở gốc repo (Vercel tự CDN hoá). Trỏ static_folder
# của Flask VỀ ĐÚNG public/ (thay vì static/ mặc định) + static_url_path=""
# (file nằm ở public/style.css sẽ phục vụ tại /style.css, KHÔNG phải
# /static/style.css) — vừa khớp chuẩn Vercel, vừa chạy `python app.py`
# local bình thường (không cần đổi gì thêm ở template, url_for('static',
# filename='style.css') vẫn ra đúng /style.css).
# Job/Contact/Company: đọc/ghi qua API backend (crawler_client.py).
# Tài khoản (đăng ký/đăng nhập, cả học viên lẫn team SS): xác thực qua
# hệ JWT của CHÍNH backend đó (backend_auth.py).
# SavedJob/JobApplication (ứng tuyển + lưu job): CŨNG đã chuyển hẳn sang
# API backend (GET/POST/DELETE /me/applications, /me/saved-jobs — xem
# backend_auth.py) — KHÔNG còn SQLite/Flask-SQLAlchemy nào trong app
# này nữa, mọi dữ liệu đều đi qua API, không có gì lưu cục bộ trên máy
# chạy Flask (đúng định hướng bảo mật đã chốt: không giữ dữ liệu người
# dùng ở tầng frontend).
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "mindx-ss-dev-key")

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Vui lòng đăng nhập để tiếp tục."
login_manager.login_message_category = "error"

# ---------------------------------------------------------------------------
# Hằng số dropdown (không phải model DB — chỉ là danh sách lựa chọn UI)
#
# ⚠️ Đổi 08/2026 (khớp đúng enum backend thật, xem lịch sử trao đổi):
#   - JOB_STATUSES/CONTACT_STATUSES giờ lấy TRỰC TIẾP từ map VN trong
#     crawler_client.py (JOB_STATUS_MAP/CONTACT_STATUS_MAP) — CHỈ còn
#     đúng số lượng giá trị backend hỗ trợ (3 job status, 4 contact
#     status), KHÔNG còn các nhãn cũ backend không có chỗ lưu (vd "Chưa
#     xác minh", "Đã gửi cho học viên", "Có JD"...).
#   - LEVELS mở rộng đủ 7 bậc backend hỗ trợ (trước chỉ có 3).
#   - WORK_TYPES, SALARY_TYPES: mới thêm — job giờ cần field có cấu
#     trúc thay vì 1 ô "mức lương" tự do.
#   - FIT_LEVELS: BỎ HẲN — company/job không có cột lưu field này ở
#     backend (đã quyết định để sau, xem lịch sử trao đổi mục "3, 4").
# ---------------------------------------------------------------------------

INDUSTRIES = ["Code", "Data Analysis", "Business Analysis"]
LEVELS = db_data.LEVEL_CODES
LOCATIONS = ["Hà Nội", "TP.HCM", "Remote", "Hybrid"]
JOB_STATUSES = list(db_data.JOB_STATUS_MAP.values())
WORK_TYPES = list(db_data.WORK_TYPE_MAP.values())
SALARY_TYPES = list(db_data.SALARY_TYPE_MAP.values())

CONTACT_STATUSES = list(db_data.CONTACT_STATUS_MAP.values())


# Job/Contact/Company nằm ở backend Postgres (qua crawler_client.py, API
# FastAPI). Ứng tuyển (JobApplication) và lưu job (SavedJob) trước đây
# là 2 bảng SQLite riêng — giờ KHÔNG còn model DB nào ở file này nữa,
# toàn bộ đã chuyển sang gọi API /me/applications, /me/saved-jobs (xem
# backend_auth.py). Tài khoản cũng 100% ở backend — xem auth.py.


def _store_auth_tokens(access_token, refresh_token):
    """Lưu cặp token vào Flask session (session cookie ký server-side
    mặc định của Flask — đủ dùng cho quy mô đồ án nội bộ). Dùng chung
    cho cả học viên lẫn team SS vì chỉ còn 1 hệ đăng nhập."""
    session["access_token"] = access_token
    session["refresh_token"] = refresh_token


def _clear_auth_tokens():
    session.pop("access_token", None)
    session.pop("refresh_token", None)


def _auth_tokens_from_session():
    return session.get("access_token"), session.get("refresh_token")


@login_manager.user_loader
def load_user(user_id):
    access_token, refresh_token = _auth_tokens_from_session()
    if not access_token:
        return None
    try:
        me = backend_auth.get_me(access_token)
    except BackendAuthError:
        # Access token (30 phút) hết hạn giữa chừng phiên Flask -> thử
        # refresh 1 lần bằng refresh_token trước khi bó tay.
        if not refresh_token:
            return None
        try:
            pair = backend_auth.refresh(refresh_token)
            _store_auth_tokens(pair["access_token"], pair["refresh_token"])
            me = backend_auth.get_me(pair["access_token"])
        except BackendAuthError:
            _clear_auth_tokens()
            return None
    return BackendUser(me)


def staff_required(view):
    """Chỉ tài khoản team SS (role ss_team/admin) mới được vào; còn lại
    bị chặn. Nếu tài khoản đang phải đổi mật khẩu lần đầu
    (must_change_password=True), ép về /change-password trước — trừ
    chính route change_password/logout để không tự khoá lối thoát."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        if not current_user.is_staff:
            flash("Chức năng này chỉ dành cho tài khoản team SS.", "error")
            return redirect(url_for("jobs_index"))
        if current_user.must_change_password and view.__name__ not in ("change_password", "logout"):
            flash("Vui lòng đổi mật khẩu trước khi tiếp tục.", "error")
            return redirect(url_for("change_password"))
        return view(*args, **kwargs)
    return wrapped


def _call_authed(fn, *args, **kwargs):
    """Gọi 1 hàm crawler_client.* cần access_token, TỰ ĐỘNG refresh 1
    lần nếu dính 401 (access token 30 phút hết hạn giữa chừng thao tác
    job/company/contact) rồi thử lại — cùng logic với load_user(), chỉ
    khác là dùng cho các thao tác GHI (POST/PATCH/DELETE) thay vì load
    user lúc đầu request.

    fn: 1 hàm crawler_client.* có tham số ĐẦU TIÊN là access_token (vd
    create_job, update_company...). args/kwargs còn lại truyền y nguyên.
    KHÔNG dùng cho hàm không cần token (list_jobs, get_job...)."""
    access_token, refresh_token = _auth_tokens_from_session()
    try:
        return fn(access_token, *args, **kwargs)
    except CrawlerAPIError as exc:
        if exc.status_code != 401 or not refresh_token:
            raise
        try:
            pair = backend_auth.refresh(refresh_token)
        except BackendAuthError:
            _clear_auth_tokens()
            raise CrawlerAPIError("Phiên đăng nhập đã hết hạn — vui lòng đăng nhập lại.", status_code=401)
        _store_auth_tokens(pair["access_token"], pair["refresh_token"])
        return fn(pair["access_token"], *args, **kwargs)




# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_date(value):
    """Parse ngày dạng 'YYYY-MM-DD' (dropdown filter jobs) -> date object."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


@app.template_filter("format_date")
def format_date(value, fmt="%d/%m/%Y"):
    """Jinja filter — parse an toàn 1 chuỗi ngày/giờ trả về TỪ API (JSON
    nên luôn là string, không phải Python date/datetime object như hồi
    còn SQLAlchemy) rồi format lại kiểu VN. Dùng thay cho việc gọi thẳng
    .strftime() lên field từ API (sẽ crash vì string không có .strftime).

    Chấp nhận cả 2 dạng backend hay trả: 'YYYY-MM-DD' (deadline job) và
    ISO 8601 đầy đủ có 'T' + timezone (created_at/applied_at). Trả '—'
    nếu rỗng hoặc không parse được, KHÔNG raise lỗi ra template."""
    if not value:
        return "—"
    if isinstance(value, str):
        text = value.replace("Z", "+00:00")  # fromisoformat không tự hiểu hậu tố "Z"
        for parser in (
            lambda s: datetime.fromisoformat(s),
            lambda s: datetime.strptime(s, "%Y-%m-%d"),
        ):
            try:
                return parser(text).strftime(fmt)
            except ValueError:
                continue
        return value  # không parse được -> hiện nguyên chuỗi thay vì nuốt mất thông tin
    try:
        return value.strftime(fmt)  # phòng khi value lỡ đã là date/datetime thật
    except AttributeError:
        return "—"


@app.context_processor
def inject_saved_job_ids():
    """Set các job_id (string UUID) mà học viên hiện tại đã lưu — dùng
    để tô nút '🔖 Đã lưu' trên mọi trang có danh sách job. Gọi GET
    /me/saved-jobs mỗi request (giống hệt cách bản gốc query SQLite mỗi
    request — không tối ưu hơn hay kém hơn bản cũ, chỉ đổi nguồn dữ
    liệu). Team SS không có khái niệm 'lưu job' nên bỏ qua."""
    if current_user.is_authenticated and not current_user.is_staff:
        access_token, _ = _auth_tokens_from_session()
        if access_token:
            try:
                saved = backend_auth.list_my_saved_jobs(access_token)
                return {"saved_job_ids": {s["job_id"] for s in saved}}
            except BackendAuthError:
                pass
    return {"saved_job_ids": set()}


# ---------------------------------------------------------------------------
# Auth routes (dùng chung cho học viên + team SS — đều qua backend JWT)
# ---------------------------------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("jobs_index"))

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
        elif len(password) < 8:  # khớp RegisterRequest.password (min_length=8) bên backend
            error = "Mật khẩu cần ít nhất 8 ký tự."
        elif password != password_confirm:
            error = "Mật khẩu nhập lại không khớp."

        if error:
            flash(error, "error")
            return render_template("register.html", industries=INDUSTRIES, form=request.form)

        try:
            # POST /auth/register (public) -> luôn tạo role='user' (học
            # viên). KHÔNG trả token — tài khoản phải bấm link xác thực
            # trong email trước khi đăng nhập được (email_verified=false).
            backend_auth.register(full_name, email, password, phone, track)
        except BackendAuthError as exc:
            flash(str(exc), "error")
            return render_template("register.html", industries=INDUSTRIES, form=request.form)

        flash(
            f"Đã tạo tài khoản cho {full_name}. Vui lòng kiểm tra email ({email}) "
            "và bấm vào link xác thực trước khi đăng nhập.",
            "success",
        )
        return redirect(url_for("login"))

    return render_template("register.html", industries=INDUSTRIES, form={})


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard") if current_user.is_staff else url_for("jobs_index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        try:
            token_data = backend_auth.login(email, password)
        except BackendAuthError as exc:
            flash(str(exc), "error")
            # Chưa xác thực email -> gợi ý nút gửi lại link ngay dưới form.
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
            return redirect(url_for("change_password"))

        next_url = request.args.get("next")
        return redirect(next_url or (url_for("dashboard") if user.is_staff else url_for("jobs_index")))

    return render_template("login.html")


@app.route("/resend-verification", methods=["POST"])
def resend_verification():
    email = request.form.get("email", "").strip().lower()
    if email:
        try:
            backend_auth.resend_verification(email)
        except BackendAuthError as exc:
            flash(str(exc), "error")
            return redirect(url_for("login"))
    flash("Nếu email tồn tại và chưa xác thực, link mới đã được gửi — kiểm tra hộp thư.", "success")
    return redirect(url_for("login"))


@app.route("/change-password", methods=["GET", "POST"])
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

        # Backend thu hồi TOÀN BỘ refresh token hiện có khi đổi mật khẩu
        # thành công (đăng xuất mọi thiết bị khác) -> phiên hiện tại ở
        # đây cũng không còn hợp lệ, bắt đăng nhập lại bằng mật khẩu mới.
        _clear_auth_tokens()
        logout_user()
        flash("Đã đổi mật khẩu. Vui lòng đăng nhập lại bằng mật khẩu mới.", "success")
        return redirect(url_for("login"))

    return render_template("change_password.html")


@app.route("/logout")
@login_required
def logout():
    _, refresh_token = _auth_tokens_from_session()
    if refresh_token:
        backend_auth.logout(refresh_token)  # revoke phía backend, không raise nếu lỗi
    _clear_auth_tokens()
    logout_user()  # xóa session phía Flask-Login
    flash("Đã đăng xuất.", "success")
    return redirect(url_for("jobs_index"))


@app.route("/jobs/<string:job_id>/save", methods=["POST"])
@login_required
def job_toggle_save(job_id):
    if current_user.is_staff:
        flash("Tài khoản team SS không dùng để lưu job.", "error")
        return redirect(request.referrer or url_for("jobs_index"))

    access_token, _ = _auth_tokens_from_session()
    try:
        backend_auth.save_job(access_token, job_id)
        flash("Đã lưu job vào danh sách của bạn.", "success")
    except BackendAuthError as exc:
        if exc.status_code == 409:
            # Đã lưu rồi -> đây là bấm nút lần 2 -> coi là "bỏ lưu" (toggle).
            try:
                backend_auth.unsave_job(access_token, job_id)
                flash("Đã bỏ lưu job.", "success")
            except BackendAuthError as exc2:
                flash(str(exc2), "error")
        else:
            flash(str(exc), "error")
    return redirect(request.referrer or url_for("jobs_index"))


@app.route("/saved-jobs")
@login_required
def saved_jobs():
    access_token, _ = _auth_tokens_from_session()
    try:
        saved = backend_auth.list_my_saved_jobs(access_token)
    except BackendAuthError as exc:
        flash(str(exc), "error")
        saved = []

    # GET /me/saved-jobs đã trả sẵn job_title/company_name/job_status,
    # nhưng template saved_jobs.html được viết theo format job đầy đủ
    # của _normalize_job() (job.position, job.industry, job.level,
    # job.location, job.salary...) — nên gọi lại db_data.get_job() cho
    # từng job để có đủ field hiển thị đúng như trang chủ, thay vì viết
    # lại toàn bộ card job trong template. Đánh đổi: N+1 lần gọi API khi
    # có N job đã lưu — chấp nhận được ở quy mô đồ án (không phải hàng
    # nghìn job đã lưu/1 học viên).
    jobs = []
    for s in saved:
        try:
            job = db_data.get_job(s["job_id"])
        except CrawlerAPIError:
            job = None
        if job:
            jobs.append(job)
    return render_template("saved_jobs.html", jobs=jobs)


@app.route("/jobs/<string:job_id>/apply", methods=["POST"])
@login_required
def job_apply(job_id):
    if current_user.is_staff:
        flash("Tài khoản team SS không dùng để ứng tuyển.", "error")
        return redirect(url_for("job_detail", job_id=job_id))

    access_token, _ = _auth_tokens_from_session()
    note = request.form.get("note", "").strip()
    try:
        application = backend_auth.apply_to_job(access_token, job_id, note)
        flash(
            f"Đã ghi nhận ứng tuyển “{application['job_title']}” tại "
            f"{application['company_name']}. Team SS sẽ liên hệ bạn sớm.",
            "success",
        )
    except BackendAuthError as exc:
        if exc.status_code == 409:
            flash("Bạn đã ứng tuyển job này rồi.", "success")
        else:
            # 400 = job không ở trạng thái OPEN (backend tự chặn) hoặc
            # job_id sai định dạng — message tiếng Việt đã đủ rõ để flash thẳng.
            flash(str(exc), "error")
    return redirect(url_for("job_detail", job_id=job_id))


@app.route("/jobs/<string:job_id>/withdraw", methods=["POST"])
@login_required
def job_withdraw(job_id):
    """Huỷ ứng tuyển — trước đây (bản SQLite) không có nút này vì xoá
    thẳng dòng DB không cần route riêng; giờ backend có hẳn DELETE
    /me/applications/{job_id} nên thêm route tương ứng cho học viên tự
    huỷ đơn nếu muốn ứng tuyển lại job khác hoặc đổi ý."""
    if current_user.is_staff:
        abort(404)
    access_token, _ = _auth_tokens_from_session()
    try:
        backend_auth.withdraw_application(access_token, job_id)
        flash("Đã huỷ ứng tuyển.", "success")
    except BackendAuthError as exc:
        flash(str(exc), "error")
    return redirect(request.referrer or url_for("my_applications"))


@app.route("/my-applications")
@login_required
def my_applications():
    if current_user.is_staff:
        return redirect(url_for("dashboard"))
    access_token, _ = _auth_tokens_from_session()
    try:
        applications = backend_auth.list_my_applications(access_token)
    except BackendAuthError as exc:
        flash(str(exc), "error")
        applications = []
    return render_template("my_applications.html", applications=applications)


# ---------------------------------------------------------------------------
# Job routes
# ---------------------------------------------------------------------------

@app.route("/")
@app.route("/jobs")
def jobs_index():
    q = request.args.get("q", "").strip()
    industry = request.args.get("industry", "")
    level = request.args.get("level", "")
    location = request.args.get("location", "")
    status = request.args.get("status", "")

    try:
        jobs = db_data.list_jobs(q=q, industry=industry, level=level, location=location, status=status)
        total_jobs = db_data.count_jobs()
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        jobs, total_jobs = [], 0

    return render_template(
        "index.html", jobs=jobs, industries=INDUSTRIES, levels=LEVELS,
        locations=LOCATIONS, statuses=JOB_STATUSES,
        filters={"q": q, "industry": industry, "level": level, "location": location, "status": status},
        total_jobs=total_jobs,
    )


@app.route("/jobs/<string:job_id>")
def job_detail(job_id):
    try:
        job = db_data.get_job(job_id)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        return redirect(url_for("jobs_index"))
    if not job:
        abort(404)
    job = dict(job)
    try:
        job["is_duplicate_candidate"] = db_data.is_duplicate_candidate(job)
    except CrawlerAPIError:
        job["is_duplicate_candidate"] = False

    applicants = None
    already_applied = False
    if current_user.is_authenticated:
        access_token, _ = _auth_tokens_from_session()
        if current_user.is_staff:
            try:
                # GET /jobs/{id}/applications trả sẵn full_name/email —
                # không cần tra chéo qua GET /auth/users nữa.
                raw_applicants = backend_auth.list_job_applicants(access_token, job["id"])
            except BackendAuthError as exc:
                flash(str(exc), "error")
                raw_applicants = []
            applicants = [
                SimpleNamespace(
                    application_id=a["application_id"],
                    job_id=a["job_id"],
                    note=a.get("note"),
                    applied_at=a["applied_at"],
                    student=SimpleNamespace(full_name=a["full_name"], email=a["email"], phone=None),
                )
                for a in raw_applicants
            ]
        else:
            try:
                my_apps = backend_auth.list_my_applications(access_token)
                already_applied = any(a["job_id"] == job["id"] for a in my_apps)
            except BackendAuthError:
                already_applied = False
    return render_template("job_detail.html", job=job, applicants=applicants,
                            already_applied=already_applied, statuses=JOB_STATUSES)


def _resolve_company_id(form):
    """Job cần company_id có sẵn (backend không tự tạo company kèm job) —
    form add_job.html cho chọn 1 trong 2: company có sẵn (select) hoặc
    tạo mới ngay tại chỗ (bật qua company_mode=new, điền company_name +
    tax_id để tránh tạo trùng nếu công ty đã từng được crawl)."""
    mode = form.get("company_mode", "existing")
    if mode == "new":
        company_name = (form.get("new_company_name") or "").strip()
        if not company_name:
            raise CrawlerAPIError("Vui lòng nhập tên công ty mới.")
        company_form = {
            "company": company_name,
            "tax_id": form.get("new_company_tax_id", ""),
            "website": form.get("new_company_website", ""),
            "industry": form.get("new_company_industry", ""),
            "city": form.get("new_company_city", ""),
        }
        company = _call_authed(db_data.create_company, company_form)
        return company["id"]
    company_id = (form.get("company_id") or "").strip()
    if not company_id:
        raise CrawlerAPIError("Vui lòng chọn công ty.")
    return company_id


@app.route("/jobs/add", methods=["GET", "POST"])
@staff_required
def job_add():
    if request.method == "POST":
        try:
            company_id = _resolve_company_id(request.form)
            job = _call_authed(db_data.create_job, request.form, company_id)
        except CrawlerAPIError as exc:
            flash(str(exc), "error")
            companies = db_data.list_companies(limit=500)
            return render_template("add_job.html", industries=INDUSTRIES, levels=LEVELS,
                                    locations=LOCATIONS, statuses=JOB_STATUSES,
                                    work_types=WORK_TYPES, salary_types=SALARY_TYPES,
                                    companies=companies, job=request.form)
        flash(f"Đã thêm job “{job['position']}” tại {job['company']}.", "success")
        return redirect(url_for("jobs_index"))
    companies = db_data.list_companies(limit=500)
    return render_template("add_job.html", industries=INDUSTRIES, levels=LEVELS,
                            locations=LOCATIONS, statuses=JOB_STATUSES,
                            work_types=WORK_TYPES, salary_types=SALARY_TYPES,
                            companies=companies, job=None)


@app.route("/jobs/<string:job_id>/edit", methods=["GET", "POST"])
@staff_required
def job_edit(job_id):
    job = db_data.get_job(job_id)
    if not job:
        abort(404)
    if request.method == "POST":
        try:
            updated = _call_authed(db_data.update_job, job_id, request.form)
        except CrawlerAPIError as exc:
            flash(str(exc), "error")
            return render_template("add_job.html", industries=INDUSTRIES, levels=LEVELS,
                                    locations=LOCATIONS, statuses=JOB_STATUSES,
                                    work_types=WORK_TYPES, salary_types=SALARY_TYPES,
                                    job=job, edit_id=job_id)
        flash(f"Đã cập nhật job “{updated['position']}”.", "success")
        return redirect(url_for("job_detail", job_id=job_id))
    return render_template("add_job.html", industries=INDUSTRIES, levels=LEVELS,
                            locations=LOCATIONS, statuses=JOB_STATUSES,
                            work_types=WORK_TYPES, salary_types=SALARY_TYPES,
                            job=job, edit_id=job_id)


@app.route("/jobs/<string:job_id>/status", methods=["POST"])
@staff_required
def job_update_status(job_id):
    job = db_data.get_job(job_id)
    if not job:
        abort(404)
    try:
        _call_authed(db_data.update_job_status, job_id, request.form.get("status", job["status"]))
        flash("Đã cập nhật trạng thái job.", "success")
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
    return redirect(url_for("job_detail", job_id=job_id))


@app.route("/jobs/<string:job_id>/delete", methods=["POST"])
@staff_required
def job_delete(job_id):
    """KHÔNG xoá thật — backend không có DELETE /jobs/{id} (job xoá thật
    sẽ bị crawl lại tạo trùng ở lượt sau). "Xóa" ở đây = đóng job
    (job_status=CLOSED), giữ tên route/hàm cũ để không phải sửa lại
    url_for() rải rác ở template, chỉ đổi hành vi bên trong."""
    job = db_data.get_job(job_id)
    if not job:
        abort(404)
    try:
        _call_authed(db_data.update_job_status, job_id, "CLOSED")
        flash("Đã đóng job (không xoá dữ liệu — job đóng vẫn xem được, chỉ ẩn khỏi tìm kiếm mặc định).", "success")
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        return redirect(url_for("job_detail", job_id=job_id))
    return redirect(url_for("jobs_index"))



# ---------------------------------------------------------------------------
# Company routes (trước đây gọi là "contact" — SAI khái niệm, xem lịch sử
# trao đổi: company và company_contact (người liên hệ HR) là 2 bảng khác
# nhau ở backend, company không sửa/xoá field CRM (fit_level/owner/
# hires_intern/products...) vì backend không có cột lưu — đã quyết định
# bỏ các field này khỏi UI, xem app.py phần hằng số dropdown phía trên).
# ---------------------------------------------------------------------------

@app.route("/companies")
@staff_required
def companies_index():
    q = request.args.get("q", "").strip()
    city = request.args.get("city", "")

    try:
        companies = db_data.list_companies(q=q, city=city)
        cities = db_data.list_company_cities()
        total_companies = db_data.count_companies()
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        companies, cities, total_companies = [], [], 0

    return render_template(
        "companies.html", companies=companies, cities=cities,
        filters={"q": q, "city": city}, total_companies=total_companies,
    )


@app.route("/companies/add", methods=["GET", "POST"])
@staff_required
def company_add():
    if request.method == "POST":
        try:
            company = _call_authed(db_data.create_company, request.form)
        except CrawlerAPIError as exc:
            flash(str(exc), "error")
            return render_template("add_company.html", company=request.form)
        flash(f"Đã thêm công ty {company['company']}.", "success")
        return redirect(url_for("company_detail", company_id=company["id"]))
    return render_template("add_company.html", company=None)


@app.route("/companies/<string:company_id>/edit", methods=["GET", "POST"])
@staff_required
def company_edit(company_id):
    company = db_data.get_company(company_id)
    if not company:
        abort(404)
    if request.method == "POST":
        try:
            updated = _call_authed(db_data.update_company, company_id, request.form)
        except CrawlerAPIError as exc:
            flash(str(exc), "error")
            return render_template("add_company.html", company=company, edit_id=company_id)
        flash(f"Đã cập nhật công ty {updated['company']}.", "success")
        return redirect(url_for("company_detail", company_id=company_id))
    return render_template("add_company.html", company=company, edit_id=company_id)


@app.route("/companies/<string:company_id>")
@staff_required
def company_detail(company_id):
    company = db_data.get_company(company_id)
    if not company:
        abort(404)
    access_token, _ = _auth_tokens_from_session()
    try:
        contacts = db_data.list_contacts(access_token, company_id)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        contacts = []
    return render_template(
        "company_detail.html", company=company, contacts=contacts, statuses=CONTACT_STATUSES,
    )


# ---------------------------------------------------------------------------
# Contact routes (người liên hệ HR — bảng con của company, route
# /companies/<company_id>/contacts/... khớp đúng backend)
# ---------------------------------------------------------------------------

@app.route("/companies/<string:company_id>/contacts/add", methods=["GET", "POST"])
@staff_required
def contact_add(company_id):
    company = db_data.get_company(company_id)
    if not company:
        abort(404)
    if request.method == "POST":
        try:
            _call_authed(db_data.create_contact, company_id, request.form)
        except CrawlerAPIError as exc:
            flash(str(exc), "error")
            return render_template("add_contact.html", company=company, contact=request.form)
        flash("Đã thêm người liên hệ.", "success")
        return redirect(url_for("company_detail", company_id=company_id))
    return render_template("add_contact.html", company=company, contact=None)


@app.route("/companies/<string:company_id>/contacts/<string:contact_id>/edit", methods=["GET", "POST"])
@staff_required
def contact_edit(company_id, contact_id):
    access_token, _ = _auth_tokens_from_session()
    contact = db_data.get_contact(access_token, company_id, contact_id)
    company = db_data.get_company(company_id)
    if not contact or not company:
        abort(404)
    if request.method == "POST":
        try:
            _call_authed(db_data.update_contact, company_id, contact_id, request.form)
        except CrawlerAPIError as exc:
            flash(str(exc), "error")
            return render_template("add_contact.html", company=company, contact=contact, edit_id=contact_id)
        flash("Đã cập nhật người liên hệ.", "success")
        return redirect(url_for("company_detail", company_id=company_id))
    return render_template("add_contact.html", company=company, contact=contact, edit_id=contact_id)


@app.route("/companies/<string:company_id>/contacts/<string:contact_id>/status", methods=["POST"])
@staff_required
def contact_update_status(company_id, contact_id):
    try:
        _call_authed(db_data.update_contact_status, company_id, contact_id, request.form.get("status", ""))
        flash("Đã cập nhật trạng thái liên hệ.", "success")
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
    return redirect(url_for("company_detail", company_id=company_id))


@app.route("/companies/<string:company_id>/contacts/<string:contact_id>/delete", methods=["POST"])
@staff_required
def contact_delete(company_id, contact_id):
    try:
        _call_authed(db_data.delete_contact, company_id, contact_id)
        flash("Đã xoá người liên hệ.", "success")
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
    return redirect(url_for("company_detail", company_id=company_id))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.route("/dashboard")
@staff_required
def dashboard():
    try:
        jobs = db_data.list_jobs()
        companies = db_data.list_companies(limit=1000)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        jobs, companies = [], []

    jobs_by_industry = {ind: sum(1 for j in jobs if j["industry"] == ind) for ind in INDUSTRIES}
    jobs_by_level = {lv: sum(1 for j in jobs if j["level"] == lv) for lv in LEVELS}
    jobs_by_status = {st: sum(1 for j in jobs if j["status"] == st) for st in JOB_STATUSES}
    jobs_by_location = {}
    for j in jobs:
        jobs_by_location[j["location"]] = jobs_by_location.get(j["location"], 0) + 1

    companies_by_city = {}
    for c in companies:
        companies_by_city[c["city"]] = companies_by_city.get(c["city"], 0) + 1

    # Tổng học viên (role='user') nằm ở backend, không còn Supabase.
    # GET /auth/users đòi role ss_team+ nên luôn gọi được ở đây (route
    # này @staff_required); nếu backend lỗi tạm thời thì hiện None thay
    # vì làm sập cả trang dashboard.
    total_students = None
    access_token, _ = _auth_tokens_from_session()
    if access_token:
        try:
            users = backend_auth.list_users(access_token)
            total_students = sum(1 for u in users if u.get("role") == "user")
        except BackendAuthError:
            pass
    # Tổng đơn ứng tuyển: backend CHƯA có endpoint đếm tổng (chỉ có
    # GET /me/applications — của riêng 1 user — và GET /jobs/{id}/applications
    # — của riêng 1 job). Gọi list_job_applicants() cho từng job trong
    # `jobs` rồi cộng dồn là khả thi nhưng tốn N lần gọi API mỗi lần mở
    # dashboard (N = tổng số job) — không đáng đánh đổi chỉ để ra 1 con
    # số thống kê. Tạm hiện None (ẩn ở template) — nên đề xuất backend
    # thêm 1 endpoint đếm tổng kiểu GET /stats/applications sau này.
    total_applications = None

    return render_template(
        "dashboard.html",
        total_jobs=len(jobs), total_contacts=len(companies),
        total_students=total_students, total_applications=total_applications,
        jobs_by_industry=jobs_by_industry, jobs_by_level=jobs_by_level,
        jobs_by_status=jobs_by_status, jobs_by_location=jobs_by_location,
        contacts_by_city=companies_by_city,
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
