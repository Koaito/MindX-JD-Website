import math
import os
from datetime import date, datetime
from functools import wraps

from env_loader import load_env_file

load_env_file()

from flask import Flask, render_template, request, redirect, url_for, flash, abort, session, jsonify
from markupsafe import Markup, escape
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
# Cache-busting cho CSS/JS tĩnh (public/style.css, public/app.js)
#
# Vercel tự CDN hoá thư mục public/ (xem comment ở static_folder phía trên)
# — request tới /style.css, /app.js KHÔNG chạy qua Flask nữa nên Flask
# không kiểm soát được cache-control của chúng. Vì <link>/<script> trong
# base.html trước giờ trỏ y nguyên 1 URL không đổi (/style.css, /app.js),
# mỗi lần deploy code CSS/JS mới, CDN/trình duyệt đã cache bản cũ vẫn có
# thể tiếp tục phục vụ y nguyên bản cũ — nhìn như "code mới không lên".
#
# Cách sửa: gắn thêm ?v=<mtime file mới nhất> vào URL trong base.html
# (asset_version() bên dưới). mtime đổi mỗi khi nội dung file thật sự đổi
# (git checkout/deploy ghi lại file -> mtime mới) -> URL đổi -> CDN/trình
# duyệt buộc phải tải bản mới, không cần tự tay đổi version mỗi lần sửa
# CSS/JS. style.css chỉ @import các file css/*.css (bản thân nó hiếm khi
# đổi nội dung) nên version của "style.css" tính theo mtime MỚI NHẤT
# trong số chính nó + toàn bộ public/css/*.css nó kéo vào.
def _asset_version(filename):
    base_dir = app.static_folder
    paths = [os.path.join(base_dir, filename)]
    if filename == "style.css":
        css_dir = os.path.join(base_dir, "css")
        if os.path.isdir(css_dir):
            paths += [
                os.path.join(css_dir, f)
                for f in os.listdir(css_dir)
                if f.endswith(".css")
            ]
    mtimes = []
    for p in paths:
        try:
            mtimes.append(os.path.getmtime(p))
        except OSError:
            pass
    return str(int(max(mtimes))) if mtimes else "0"


app.jinja_env.globals["asset_version"] = _asset_version

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

INDUSTRIES = [
    "Code", "Data Analysis", "Data Engineer", "Data Scientist",
    "Business Analysis", "UI/UX Design",
]  # ⚠️ Đổi 08/2026 — khớp ĐÚNG matching_industry của cả 6 category
   # backend crawl (xem config.py: TOPCV_CATEGORIES/VIETNAMWORKS_CATEGORIES).
   # Trước chỉ có 3 ngành -> job crawl được thuộc "Data Engineer",
   # "Data Scientist", "UI/UX Design" vẫn hiện đúng trên card (dữ liệu
   # backend không sai), nhưng KHÔNG chọn được trong dropdown filter/thêm
   # job vì thiếu option -> nhìn như "job biến mất" dù job vẫn còn.
LEVELS = db_data.LEVEL_CODES
LOCATIONS = ["Hà Nội", "TP.HCM", "Remote", "Hybrid"]
JOB_STATUSES = list(db_data.JOB_STATUS_MAP.values())
WORK_TYPES = list(db_data.WORK_TYPE_MAP.values())
SALARY_TYPES = list(db_data.SALARY_TYPE_MAP.values())
SALARY_PERIODS = list(db_data.SALARY_PERIOD_MAP.values())

CONTACT_STATUSES = list(db_data.CONTACT_STATUS_MAP.values())
PARTNERSHIP_POTENTIALS = list(db_data.PARTNERSHIP_POTENTIAL_MAP.values())

# Số card/hàng mỗi trang cho danh sách job và công ty — 20 là điểm cân bằng
# phổ biến ở các trang tuyển dụng (TopCV/VietnamWorks ~20-25, Indeed ~15,
# LinkedIn ~25): đủ lướt nhanh 1 lần cuộn, không load quá nặng, chia đẹp
# cho layout grid 4 cột (.job-grid) ở màn hình rộng.
JOBS_PER_PAGE = 20
COMPANIES_PER_PAGE = 20


def _paginate_args(default_per_page):
    """Đọc ?page= từ query string, ép về số nguyên >=1 (giá trị rác/âm/0
    coi như trang 1 thay vì lỗi 500)."""
    try:
        page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    if page < 1:
        page = 1
    return page, default_per_page

# Nhãn tiếng Việt cho 3 role backend hỗ trợ (user/ss_team/admin) — dùng
# ở trang quản lý tài khoản team SS (staff_accounts.html) cho dropdown
# đổi role và hiển thị. Thứ tự dict cũng là thứ tự hiện trong <select>.
ROLE_LABELS = {"user": "Học viên", "ss_team": "Team SS", "admin": "Admin"}


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


def _parse_any_date(value):
    """Như parse_date(), nhưng chấp nhận CẢ 2 dạng ngày mà API job trả
    về: 'YYYY-MM-DD' (deadline) và ISO 8601 đầy đủ có 'T'+timezone
    (date_collected/created_at) — cùng logic parse với filter
    format_date() bên dưới, chỉ khác là trả về date object để tính toán
    (group theo tháng...) thay vì string đã format sẵn để hiển thị.
    Trả None nếu rỗng hoặc không parse được."""
    if not value or not isinstance(value, str):
        return None
    text = value.replace("Z", "+00:00")  # fromisoformat không tự hiểu hậu tố "Z"
    for parser in (
        lambda s: datetime.fromisoformat(s),
        lambda s: datetime.strptime(s, "%Y-%m-%d"),
    ):
        try:
            return parser(text).date()
        except ValueError:
            continue
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


def _jobs_by_month(jobs, date_field, months_back=6, only_past=False):
    """Đếm số job theo tháng, dựa trên field ngày chỉ định (date_field
    là 'date_collected' hoặc 'deadline') — dùng cho biểu đồ "JD theo
    tháng" trên dashboard (so sánh JD mới thêm vs JD hết hạn).

    Trả về 2 list cùng độ dài months_back, THEO THỨ TỰ THỜI GIAN TĂNG
    DẦN (tháng cũ nhất trước, tháng hiện tại cuối cùng):
      - labels: ['MM/YYYY', ...] để hiện trên trục X
      - counts: [int, ...] số job có date_field rơi vào tháng đó

    Luôn trả đủ months_back tháng kể cả khi tháng đó không có job nào
    (count=0) — để biểu đồ không bị "nhảy cóc" thiếu tháng giữa chừng.
    Job có date_field rỗng/không parse được bị bỏ qua (không tính vào
    tháng nào), KHÔNG làm crash việc tính toán các job còn lại.

    only_past=True: chỉ đếm job có date_field THỰC SỰ đã qua so với
    hôm nay (d < today) — dùng cho cột "JD hết hạn" để không tính nhầm
    những job deadline còn ở tương lai (job vẫn đang mở, chưa hết hạn)
    vào biểu đồ. Ví dụ job deadline 12/09/2026 trong khi hôm nay mới là
    20/08/2026 sẽ KHÔNG được tính, dù deadline đó "rơi vào tháng
    09/2026" theo lịch — vì job đó trên thực tế chưa hết hạn.
    """
    today = datetime.now().date()
    # Danh sách months_back tháng gần nhất, cũ nhất trước — tính lùi từ
    # tháng hiện tại bằng cách trừ số tháng qua năm/tháng (không dùng
    # timedelta vì độ dài tháng không cố định).
    month_keys = []
    y, m = today.year, today.month
    for _ in range(months_back):
        month_keys.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    month_keys.reverse()

    counts_by_key = {key: 0 for key in month_keys}
    for job in jobs:
        d = _parse_any_date(job.get(date_field))
        if d is None:
            continue
        if only_past and d >= today:
            continue  # deadline còn ở hiện tại/tương lai -> job chưa thực sự hết hạn, bỏ qua
        key = (d.year, d.month)
        if key in counts_by_key:
            counts_by_key[key] += 1

    labels = ["%02d/%d" % (m, y) for (y, m) in month_keys]
    counts = [counts_by_key[key] for key in month_keys]
    return labels, counts


@app.template_filter("to_bullets")
def to_bullets(value):
    """Jinja filter — JD description/requirements từ crawler thường là 1
    khối text nhiều dòng (mỗi dòng 1 ý), hiện tại chỉ show bằng
    white-space:pre-line (giữ xuống dòng nhưng không có gạch đầu dòng,
    khó đọc). Filter này tách theo dòng và render thành <ul><li> thật.

    Tự escape() từng dòng (KHÔNG tin dữ liệu crawl là an toàn) rồi mới
    ghép HTML — trả về Markup để Jinja không escape lần 2 phần <ul>/<li>
    mà mình tự dựng.
    Nếu chỉ có 1 dòng hoặc rỗng, trả lại y nguyên dạng <p> để không tạo
    list rỗng/1 dòng trông kỳ.
    """
    if not value:
        return ""
    lines = [ln.strip(" \t-•*") for ln in value.splitlines()]
    lines = [ln for ln in lines if ln]
    if len(lines) <= 1:
        return Markup("<p>{}</p>").format(value)
    items = "".join("<li>{}</li>".format(escape(ln)) for ln in lines)
    return Markup("<ul class=\"jd-bullets\">{}</ul>").format(Markup(items))


@app.context_processor
def inject_role_labels():
    """Cho mọi template dùng được ROLE_LABELS (vd base.html hiện đúng
    nhãn vai trò trong sidebar — 'Admin'/'Team SS'/'Học viên' — thay vì
    hardcode 1 chữ cố định cho mọi is_staff=True, gây admin cũng hiện
    nhầm thành 'Team SS')."""
    return {"role_labels": ROLE_LABELS}


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


@app.route("/verify-email")
def verify_email():
    """Backend redirect(302) tới đây SAU KHI đã tự xử lý token (xem
    GET /auth/verify-email phía api/routers/auth.py — route đó KHÔNG
    còn trả HTML tĩnh nữa, chỉ redirect kèm ?status=...). Route này
    KHÔNG tự gọi backend gì cả, chỉ đọc status trên URL rồi hiển thị
    đúng theme của site — mọi việc xác thực/hết hạn/hợp lệ đã xong ở
    phía backend trước khi tới đây."""
    status = request.args.get("status", "invalid")
    if status not in ("success", "expired", "invalid"):
        status = "invalid"
    return render_template("verify_email.html", status=status)


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Bước 1/2 của luồng quên mật khẩu — nhập email, gọi POST
    /auth/forgot-password. Backend LUÔN trả cùng 1 message chung chung
    dù email tồn tại hay không (chống dò email) nên route này KHÔNG có
    nhánh lỗi "email không tồn tại" — chỉ lỗi khi bản thân request thất
    bại (mất mạng, backend sập)."""
    if current_user.is_authenticated:
        return redirect(url_for("jobs_index"))

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
        return redirect(url_for("login"))

    return render_template("forgot_password.html", email="")


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    """Bước 2/2 — link trong email trỏ về đây kèm ?token=..., nhập mật
    khẩu mới, gọi POST /auth/reset-password. Chặn ngay từ GET nếu thiếu
    token trên URL (truy cập trực tiếp, không qua email) — không hiện
    form vô ích, tránh người dùng nhập xong mới biết link sai."""
    if current_user.is_authenticated:
        return redirect(url_for("jobs_index"))

    token = request.args.get("token", "").strip() if request.method == "GET" else request.form.get("token", "").strip()
    if not token:
        flash("Link đặt lại mật khẩu không hợp lệ — thiếu token. Vui lòng dùng đúng link trong email.", "error")
        return redirect(url_for("forgot_password"))

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
            # Token sai/hết hạn/đã dùng -> message backend đã đủ rõ,
            # kèm gợi ý xin link mới thay vì để người dùng bế tắc.
            flash(str(exc), "error")
            return redirect(url_for("forgot_password"))

        # Backend đã thu hồi toàn bộ refresh token của user khi đổi mật
        # khẩu thành công -> không có session nào ở đây để clear (route
        # này chưa từng đăng nhập), chỉ cần điều hướng về /login.
        flash("Đã đặt lại mật khẩu. Vui lòng đăng nhập bằng mật khẩu mới.", "success")
        return redirect(url_for("login"))

    return render_template("reset_password.html", token=token)


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


@app.route("/jobs/<job_id>/toggle-save.json", methods=["POST"])
@login_required
def job_toggle_save_json(job_id):
    """Same toggle-save logic as job_toggle_save, but returns JSON instead of
    redirecting, so the button can update in place without a full page
    reload (issue: every save/unsave click reloaded the whole page).
    The form-based route above is kept as-is for no-JS fallback."""
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
    page, per_page = _paginate_args(JOBS_PER_PAGE)

    # `status` rỗng (chưa chọn gì trong dropdown, kể cả lần đầu vào
    # trang) TRƯỚC ĐÂY = không lọc gì -> trộn lẫn cả job OPEN/EXPIRED/
    # CLOSED trong danh sách mặc định, học viên phải tự chọn "Đang
    # tuyển" mới lọc sạch được job chết. Giờ đổi mặc định: rỗng ->
    # ngầm hiểu là OPEN (đang tuyển) — muốn xem EXPIRED/CLOSED phải chủ
    # động chọn dropdown, kể cả chọn hẳn "Tất cả trạng thái" (option
    # riêng, value="ALL") nếu muốn xem trộn lẫn như hành vi cũ.
    if status == "ALL":
        status_filter = ""  # value đặc biệt -> KHÔNG lọc gì, xem cả 3 trạng thái
    elif status:
        status_filter = status  # đã chọn cụ thể (Hết hạn/Đã đóng/Đang tuyển)
    else:
        status_filter = "Đang tuyển"  # mặc định khi chưa chọn gì

    try:
        total_jobs = db_data.count_jobs(q=q, industry=industry, level=level, location=location, status=status_filter)
        total_pages = max(1, math.ceil(total_jobs / per_page))
        # Trang xin quá số trang thực tế (vd sửa tay ?page=999) -> kéo về
        # trang cuối cùng có dữ liệu thay vì trả trang trắng.
        if page > total_pages:
            page = total_pages
        jobs = db_data.list_jobs(
            q=q, industry=industry, level=level, location=location, status=status_filter,
            limit=per_page, offset=(page - 1) * per_page,
        )
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        jobs, total_jobs, total_pages, page = [], 0, 1, 1

    return render_template(
        "index.html", jobs=jobs, industries=INDUSTRIES, levels=LEVELS,
        locations=LOCATIONS, statuses=JOB_STATUSES,
        filters={"q": q, "industry": industry, "level": level, "location": location, "status": status},
        # Bản filter đã bỏ field rỗng — dùng riêng cho link phân trang, để
        # URL trang 2 không kéo theo ?q=&industry=&... (Flask url_for vẫn
        # add param dù value rỗng, nhìn rối và không cần thiết).
        pagination_filters={k: v for k, v in
                             {"q": q, "industry": industry, "level": level,
                              "location": location, "status": status}.items() if v},
        total_jobs=total_jobs, page=page, total_pages=total_pages, per_page=per_page,
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
    savers = None
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
            # Thêm 08/2026 — mirror ĐÚNG khối applicants ở trên nhưng
            # cho chiều "lưu" (GET /jobs/{id}/saved-jobs, xem
            # backend_auth.list_job_savers()) — xem lịch sử trao đổi để
            # biết lý do saved_jobs từ chỗ riêng tư 100% chuyển sang cho
            # staff xem được.
            try:
                raw_savers = backend_auth.list_job_savers(access_token, job["id"])
            except BackendAuthError as exc:
                flash(str(exc), "error")
                raw_savers = []
            savers = [
                SimpleNamespace(
                    saved_job_id=s["saved_job_id"],
                    job_id=s["job_id"],
                    created_at=s["created_at"],
                    student=SimpleNamespace(full_name=s["full_name"], email=s["email"], phone=s.get("phone")),
                )
                for s in raw_savers
            ]
        else:
            try:
                my_apps = backend_auth.list_my_applications(access_token)
                already_applied = any(a["job_id"] == job["id"] for a in my_apps)
            except BackendAuthError:
                already_applied = False
    return render_template("job_detail.html", job=job, applicants=applicants, savers=savers,
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
            try:
                companies = _list_all_companies()
            except CrawlerAPIError as exc2:
                flash(str(exc2), "error")
                companies = []
            return render_template("add_job.html", industries=INDUSTRIES, levels=LEVELS,
                                    locations=LOCATIONS, statuses=JOB_STATUSES,
                                    work_types=WORK_TYPES, salary_types=SALARY_TYPES, salary_periods=SALARY_PERIODS,
                                    companies=companies, job=request.form)
        flash(f"Đã thêm job “{job['position']}” tại {job['company']}.", "success")
        return redirect(url_for("jobs_index"))
    try:
        companies = _list_all_companies()
    except CrawlerAPIError as exc:
        # Trước đây KHÔNG bọc try/except ở đây -> backend chậm/lỗi (vd
        # Render free tier "ngủ", cold start quá REQUEST_TIMEOUT) sẽ làm
        # Flask crash thẳng ra trang 500 trắng, không rõ lý do gì. Giờ
        # flash lỗi thật ra màn hình + trả list rỗng, trang vẫn vào
        # được (chỉ dropdown công ty rỗng), người dùng biết cần thử lại.
        flash(str(exc), "error")
        companies = []
    return render_template("add_job.html", industries=INDUSTRIES, levels=LEVELS,
                            locations=LOCATIONS, statuses=JOB_STATUSES,
                            work_types=WORK_TYPES, salary_types=SALARY_TYPES, salary_periods=SALARY_PERIODS,
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
                                    work_types=WORK_TYPES, salary_types=SALARY_TYPES, salary_periods=SALARY_PERIODS,
                                    job=job, edit_id=job_id)
        flash(f"Đã cập nhật job “{updated['position']}”.", "success")
        return redirect(url_for("job_detail", job_id=job_id))
    return render_template("add_job.html", industries=INDUSTRIES, levels=LEVELS,
                            locations=LOCATIONS, statuses=JOB_STATUSES,
                            work_types=WORK_TYPES, salary_types=SALARY_TYPES, salary_periods=SALARY_PERIODS,
                            job=job, edit_id=job_id)


@app.route("/jobs/<string:job_id>/status", methods=["POST"])
@staff_required
def job_update_status(job_id):
    job = db_data.get_job(job_id)
    if not job:
        abort(404)
    try:
        _call_authed(
            db_data.update_job_status, job_id, request.form.get("status", job["status"]),
            request.form.get("activity_note", ""),
        )
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
        _call_authed(db_data.update_job_status, job_id, "CLOSED", request.form.get("activity_note", ""))
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
    page, per_page = _paginate_args(COMPANIES_PER_PAGE)

    try:
        cities = db_data.list_company_cities()
        total_companies = db_data.count_companies(q=q, city=city)
        total_pages = max(1, math.ceil(total_companies / per_page))
        if page > total_pages:
            page = total_pages
        companies = db_data.list_companies(q=q, city=city, limit=per_page, offset=(page - 1) * per_page)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        companies, cities, total_companies, total_pages, page = [], [], 0, 1, 1

    return render_template(
        "companies.html", companies=companies, cities=cities,
        filters={"q": q, "city": city}, total_companies=total_companies,
        pagination_filters={k: v for k, v in {"q": q, "city": city}.items() if v},
        page=page, total_pages=total_pages, per_page=per_page,
    )


@app.route("/companies/add", methods=["GET", "POST"])
@staff_required
def company_add():
    if request.method == "POST":
        try:
            company = _call_authed(db_data.create_company, request.form)
        except CrawlerAPIError as exc:
            flash(str(exc), "error")
            return render_template("add_company.html", company=request.form, partnership_potentials=PARTNERSHIP_POTENTIALS)
        flash(f"Đã thêm công ty {company['company']}.", "success")
        return redirect(url_for("company_detail", company_id=company["id"]))
    return render_template("add_company.html", company=None, partnership_potentials=PARTNERSHIP_POTENTIALS)


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
            return render_template("add_company.html", company=company, edit_id=company_id, partnership_potentials=PARTNERSHIP_POTENTIALS)
        flash(f"Đã cập nhật công ty {updated['company']}.", "success")
        return redirect(url_for("company_detail", company_id=company_id))
    return render_template("add_company.html", company=company, edit_id=company_id, partnership_potentials=PARTNERSHIP_POTENTIALS)


@app.route("/companies/<string:company_id>/delete", methods=["POST"])
@staff_required
def company_delete(company_id):
    """Xoá MỀM (thêm 08/2026) — trước đây company KHÔNG có cách xoá nào
    ở cả UI lẫn backend. note BẮT BUỘC (backend chặn cứng 422 nếu
    thiếu), kiểm tra sớm ở đây trước để tránh round-trip mạng vô ích."""
    note = (request.form.get("note") or "").strip()
    if not note:
        flash("Xoá công ty bắt buộc phải nhập ghi chú lý do.", "error")
        return redirect(url_for("company_detail", company_id=company_id))
    try:
        _call_authed(db_data.delete_company, company_id, note)
        flash("Đã xoá công ty (xoá mềm — vẫn xem lại được qua Lịch sử thao tác, JD/contact liên quan không bị mất).", "success")
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        return redirect(url_for("company_detail", company_id=company_id))
    return redirect(url_for("companies_index"))


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
# Danh sách contact tổng hợp (GỘP TẤT CẢ công ty) — khác company_detail.html
# vốn chỉ hiện contact của 1 company_id. Route riêng /contacts, KHÔNG lồng
# dưới /companies/<company_id>/... như các route contact CRUD bên dưới.
# ---------------------------------------------------------------------------

@app.route("/contacts")
@staff_required
def contacts_index():
    status_vn = request.args.get("status", "")
    company_id = request.args.get("company_id", "")
    search = request.args.get("q", "").strip()

    status_raw = db_data.CONTACT_STATUS_MAP_REV.get(status_vn, "") if status_vn else ""

    access_token, _ = _auth_tokens_from_session()
    try:
        contacts = db_data.list_all_contacts(
            access_token, status_raw=status_raw, company_id=company_id, search=search,
        )
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        contacts = []

    try:
        # list_all_companies() tự phân trang dưới giới hạn 200/lần của
        # backend — trước đây gọi list_companies(limit=500) thẳng bị lỗi
        # 422 "Input should be less than or equal to 200".
        companies = db_data.list_all_companies()
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        companies = []

    # staff_members: dropdown "gán phụ trách" trên mỗi dòng contact (thêm
    # 08/2026) — chỉ ss_team/admin mới được gán (khớp _validate_assignee()
    # phía backend), tái dùng GET /auth/users đã gọi sẵn ở nhiều trang
    # quản trị khác (staff_accounts, student_activity), không route riêng.
    try:
        all_users = backend_auth.list_users(access_token)
        staff_members = [u for u in all_users if u.get("role") in ("ss_team", "admin")]
    except BackendAuthError as exc:
        flash(str(exc), "error")
        staff_members = []
    # staff_by_id: tra tên hiển thị cho c.assigned_ss_user (chỉ là UUID)
    # trong template — dùng chung ở cả contacts.html lẫn staff_activity*.html.
    staff_by_id = {u["ss_user_id"]: u for u in staff_members}

    return render_template(
        "contacts.html", contacts=contacts, companies=companies, statuses=CONTACT_STATUSES,
        staff_members=staff_members, staff_by_id=staff_by_id,
        filters={"status": status_vn, "company_id": company_id, "q": search},
    )


# ---------------------------------------------------------------------------
# Contact routes (người liên hệ HR — bảng con của company, route
# /companies/<company_id>/contacts/... khớp đúng backend)
# ---------------------------------------------------------------------------

@app.route("/contacts/add", methods=["GET", "POST"])
@staff_required
def contact_add_any():
    """Thêm contact KHÔNG cần vào từng trang company trước — chọn công ty
    ngay trên form qua dropdown. Khác contact_add(company_id) bên dưới
    (route cũ /companies/<company_id>/contacts/add, company đã biết sẵn
    từ URL, dùng khi thêm contact ngay trong lúc đang xem 1 company cụ
    thể) — 2 route cùng tồn tại, phục vụ 2 lối vào khác nhau, không thay
    thế nhau."""
    try:
        companies = db_data.list_all_companies()
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        companies = []

    if request.method == "POST":
        company_id = request.form.get("company_id", "")
        if not company_id:
            flash("Cần chọn công ty.", "error")
            return render_template("add_contact.html", company=None, companies=companies, contact=request.form)
        try:
            _call_authed(db_data.create_contact, company_id, request.form)
        except CrawlerAPIError as exc:
            flash(str(exc), "error")
            return render_template("add_contact.html", company=None, companies=companies, contact=request.form)
        flash("Đã thêm người liên hệ.", "success")
        return redirect(url_for("contacts_index"))

    return render_template("add_contact.html", company=None, companies=companies, contact=None)


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
            _call_authed(
                db_data.update_contact, company_id, contact_id, request.form,
                request.form.get("activity_note", ""),
            )
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
    note = (request.form.get("note") or "").strip()
    if not note:
        # Chặn ở tầng Flask TRƯỚC KHI gọi backend — cùng validate với
        # backend (422 nếu thiếu note) nhưng bắt sớm hơn để tránh 1
        # round-trip mạng không cần thiết cho lỗi chắc chắn xảy ra.
        flash("Xoá người liên hệ bắt buộc phải nhập ghi chú lý do.", "error")
        return redirect(url_for("company_detail", company_id=company_id))
    try:
        _call_authed(db_data.delete_contact, company_id, contact_id, note)
        flash("Đã xoá người liên hệ.", "success")
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
    return redirect(url_for("company_detail", company_id=company_id))


@app.route("/companies/<string:company_id>/contacts/<string:contact_id>/hard-delete", methods=["POST"])
@staff_required
def contact_hard_delete(company_id, contact_id):
    """Xoá THẬT (mới 08/2026) — chỉ hiện nút này ở UI cho contact ĐÃ
    xoá mềm (xem company_detail.html), nhưng backend vẫn tự kiểm tra
    lại (409 nếu chưa soft-delete / còn job_contact_links) nên route
    này AN TOÀN dù staff cố tình gọi thẳng URL bỏ qua UI."""
    try:
        _call_authed(db_data.hard_delete_contact, company_id, contact_id)
        flash("Đã xoá hẳn người liên hệ (không thể khôi phục).", "success")
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
    return redirect(url_for("company_detail", company_id=company_id))


@app.route("/companies/<string:company_id>/contacts/<string:contact_id>/assign", methods=["POST"])
@staff_required
def contact_assign(company_id, contact_id):
    """Gán (hoặc bỏ gán, khi select để trống) người phụ trách 1 contact
    — thêm 08/2026, dùng ở contacts.html (dropdown inline, cùng cách
    làm với contact_update_status() ở trên) và staff_activity_detail.html
    (đổi người phụ trách ngay tại trang xem hoạt động 1 staff).

    next: URL quay lại sau khi submit — mặc định company_detail, nhưng
    contacts.html/staff_activity_detail.html truyền request.referrer qua
    hidden input để user quay lại ĐÚNG trang đang đứng (danh sách contact
    tổng hợp, hoặc trang staff-activity của người vừa được gán) thay vì
    luôn nhảy về company_detail như các route contact khác."""
    try:
        _call_authed(
            db_data.assign_contact, company_id, contact_id,
            request.form.get("assigned_ss_user", ""),
            request.form.get("note", ""),
        )
        flash("Đã cập nhật người phụ trách.", "success")
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
    next_url = request.form.get("next", "")
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect(url_for("company_detail", company_id=company_id))


def _list_all_companies():
    """Lấy TOÀN BỘ công ty (không chỉ 1 trang) — backend giới hạn cứng
    limit tối đa 200/lần gọi (api/routers/companies.py: le=200), nên
    phải tự phân trang bằng offset thay vì gọi limit lớn hơn 200 (sẽ bị
    backend trả 422 "Input should be less than or equal to 200").
    Dùng chung cho job_add() (dropdown chọn công ty) và dashboard()
    (đếm công ty theo thành phố) — trước đây mỗi chỗ tự viết 1 kiểu,
    job_add() còn viết SAI (limit=500) nên bị 422 mỗi lần vào trang."""
    companies = []
    offset = 0
    while True:
        batch = db_data.list_companies(limit=200, offset=offset)
        if not batch:
            break
        companies.extend(batch)
        if len(batch) < 200:
            break
        offset += 200
    return companies


# ---------------------------------------------------------------------------
# Dashboard — helpers cho tab "Gợi ý học viên" (nhóm A)
# ---------------------------------------------------------------------------

def _merge_engagement_into_jobs(jobs, engagement_jobs):
    """Gộp application_count/saved_count (từ GET /stats/engagement) vào
    từng job trong `jobs` (list đã có từ list_all_jobs()) theo job_id —
    sửa TRỰC TIẾP trên list jobs hiện có thay vì tạo list riêng, để mọi
    chỗ dùng `jobs` sau đó (kể cả các bar-chart theo ngành/level cũ) đều
    thấy field mới nếu cần, không phải truyền thêm biến song song.

    engagement_jobs chỉ có job đang OPEN (xem db.get_job_engagement_counts
    ở backend) — job KHÔNG có trong engagement_jobs (đã đóng/hết hạn)
    được gán application_count=None/saved_count=None, KHÔNG phải 0, để
    phân biệt "chắc chắn 0 lượt quan tâm" với "không có dữ liệu" (job
    đã đóng thì không còn ý nghĩa để tính vào 'JD ế'/'JD sắp hết hạn')."""
    by_id = {e.get("job_id"): e for e in engagement_jobs or []}
    for job in jobs:
        eng = by_id.get(job.get("id"))
        job["application_count"] = eng.get("application_count") if eng else None
        job["saved_count"] = eng.get("saved_count") if eng else None


def _jd_needing_push(jobs, days_min=7, days_max=14):
    """'JD sắp hết hạn cần đẩy gấp' — job OPEN, deadline rơi trong
    days_min..days_max ngày tới, và CHƯA có ai lưu/ứng tuyển. Sort theo
    deadline gần nhất trước (job sắp hết hạn nhất ưu tiên gọi/đẩy trước)."""
    today = datetime.now().date()
    result = []
    for job in jobs:
        if job.get("status_raw") != "OPEN":
            continue
        if job.get("application_count") is None:  # không có dữ liệu engagement -> bỏ qua, tránh báo nhầm
            continue
        if job["application_count"] or job["saved_count"]:
            continue
        d = _parse_any_date(job.get("deadline"))
        if d is None:
            continue
        days_left = (d - today).days
        if days_min <= days_left <= days_max:
            result.append({**job, "days_left": days_left})
    result.sort(key=lambda j: j["days_left"])
    return result


def _jd_stale(jobs, min_age_days=30):
    """'JD ế' — job OPEN đã đăng >= min_age_days ngày mà vẫn 0 lượt
    lưu/ứng tuyển. Sort theo ngày đăng cũ nhất trước (nằm im lâu nhất,
    cần xem lại/gỡ trước)."""
    today = datetime.now().date()
    result = []
    for job in jobs:
        if job.get("status_raw") != "OPEN":
            continue
        if job.get("application_count") is None:
            continue
        if job["application_count"] or job["saved_count"]:
            continue
        d = _parse_any_date(job.get("date_collected"))
        if d is None:
            continue
        age_days = (today - d).days
        if age_days >= min_age_days:
            result.append({**job, "age_days": age_days})
    result.sort(key=lambda j: -j["age_days"])
    return result


def _top_skills(jobs, days_recent=30, top_n=10):
    """Top skill hot — đếm tần suất skill (field 'skills', chuỗi phân
    cách dấu phẩy) trong JD mới thêm trong days_recent ngày gần đây.
    Chỉ tính JD mới để phản ánh đúng nhu cầu HIỆN TẠI của doanh
    nghiệp, không lẫn skill từ JD cũ đăng nhiều tháng trước."""
    today = datetime.now().date()
    counts: dict = {}
    for job in jobs:
        d = _parse_any_date(job.get("date_collected"))
        if d is None or (today - d).days > days_recent:
            continue
        for raw_skill in (job.get("skills") or "").split(","):
            skill = raw_skill.strip()
            if skill:
                counts[skill] = counts.get(skill, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])[:top_n]


def _salary_ranges_by_industry_level(jobs):
    """Khoảng lương trung bình theo (ngành, level) — chỉ gộp job có
    currency=VNĐ và trả theo tháng (salary_period_raw mặc định MONTH,
    hoặc rỗng) để không lẫn đơn vị/kỳ hạn khác nhau vào cùng 1 con số
    trung bình (job trả USD hoặc theo NĂM bị bỏ qua khỏi bảng này, vẫn
    xem chi tiết được ở trang /jobs như bình thường)."""
    groups: dict = {}
    for job in jobs:
        if (job.get("currency") or "VNĐ") != "VNĐ":
            continue
        if (job.get("salary_period_raw") or "MONTH") != "MONTH":
            continue
        lo, hi = job.get("salary_min"), job.get("salary_max")
        if not lo and not hi:
            continue
        key = (job.get("industry") or "Khác", job.get("level") or "Khác")
        g = groups.setdefault(key, {"mins": [], "maxs": []})
        if lo:
            g["mins"].append(lo)
        if hi:
            g["maxs"].append(hi)
    rows = []
    for (industry, level), vals in groups.items():
        avg_min = sum(vals["mins"]) / len(vals["mins"]) if vals["mins"] else None
        avg_max = sum(vals["maxs"]) / len(vals["maxs"]) if vals["maxs"] else None
        rows.append({
            "industry": industry, "level": level,
            "avg_min": avg_min, "avg_max": avg_max,
            "sample_size": len(vals["mins"]) or len(vals["maxs"]),
        })
    rows.sort(key=lambda r: -(r["avg_max"] or r["avg_min"] or 0))
    # Format thành chuỗi hiển thị sẵn ở đây (không phải trong template)
    # — cùng cách "{:,.0f}" như _fmt_salary() bên crawler_client.py, để
    # 2 nơi hiện số lương ra UI dùng chung 1 kiểu định dạng.
    for r in rows:
        r["avg_min_fmt"] = f"{r['avg_min']:,.0f}" if r["avg_min"] else None
        r["avg_max_fmt"] = f"{r['avg_max']:,.0f}" if r["avg_max"] else None
    return rows


# ---------------------------------------------------------------------------
# Dashboard — helpers cho tab "Doanh nghiệp" (nhóm B)
# ---------------------------------------------------------------------------

def _companies_high_potential_no_contact(companies, contacts, quiet_days=60):
    """'Công ty tiềm năng nhưng thiếu contact' — công ty Tiềm năng hợp
    tác = Cao mà (a) chưa có contact nào, hoặc (b) MỌI contact đều đã
    liên hệ lần cuối >= quiet_days ngày trước (hoặc chưa từng liên hệ
    lần nào). Chỉ cần 1 contact còn "nóng" là công ty coi như đang được
    theo dõi, không tính vào đây. Sort: chưa có contact/chưa từng liên
    hệ lên đầu, rồi tới nguội lâu nhất."""
    today = datetime.now().date()
    contacts_by_company: dict = {}
    for ct in contacts:
        contacts_by_company.setdefault(ct.get("company_id"), []).append(ct)

    result = []
    for c in companies:
        if c.get("partnership_potential") != "Cao":
            continue
        company_contacts = contacts_by_company.get(c.get("id"), [])
        if not company_contacts:
            result.append({**c, "reason": "Chưa có contact nào", "last_contacted": None})
            continue
        last_dates = [_parse_any_date(ct.get("last_contacted")) for ct in company_contacts]
        if any(d is not None and (today - d).days < quiet_days for d in last_dates):
            continue  # có ít nhất 1 contact còn "nóng" -> bỏ qua công ty này
        most_recent = max((d for d in last_dates if d), default=None)
        result.append({
            **c,
            "reason": "Contact đã nguội" if most_recent else "Có contact nhưng chưa từng liên hệ",
            "last_contacted": most_recent,
        })
    result.sort(key=lambda c: c["last_contacted"] or date.min)
    return result


def _companies_job_activity(jobs, companies, expanding_days=30, expanding_min_jobs=2, quiet_days=75):
    """Trả 2 nhóm cùng lúc (dùng chung 1 lượt group job theo company_id):
    - expanding: công ty có >= expanding_min_jobs job mới trong
      expanding_days ngày gần đây -> dấu hiệu mở rộng tuyển dụng mạnh,
      cơ hội đề xuất hợp tác dài hạn.
    - quiet: công ty ĐÃ TỪNG có job nhưng job MỚI NHẤT cũng đã >=
      quiet_days ngày trước -> cần chủ động liên hệ lại xem còn nhu cầu
      tuyển không."""
    today = datetime.now().date()
    jobs_by_company: dict = {}
    for j in jobs:
        d = _parse_any_date(j.get("date_collected"))
        if d is None or not j.get("company_id"):
            continue
        jobs_by_company.setdefault(j["company_id"], []).append(d)

    companies_idx = {c["id"]: c for c in companies}
    expanding, quiet = [], []
    for company_id, dates in jobs_by_company.items():
        company = companies_idx.get(company_id)
        if not company:
            continue
        recent_count = sum(1 for d in dates if (today - d).days <= expanding_days)
        if recent_count >= expanding_min_jobs:
            expanding.append({**company, "recent_job_count": recent_count})
        latest = max(dates)
        quiet_for = (today - latest).days
        if quiet_for >= quiet_days:
            quiet.append({**company, "quiet_days": quiet_for, "last_job_date": latest})

    expanding.sort(key=lambda c: -c["recent_job_count"])
    quiet.sort(key=lambda c: -c["quiet_days"])
    return expanding, quiet


# ---------------------------------------------------------------------------
# Dashboard — helpers cho tab "Báo cáo tháng" (nhóm C)
# ---------------------------------------------------------------------------

def _pct_change(current, previous):
    """% thay đổi so tháng trước — trả None nếu tháng trước = 0 (chia
    cho 0 vô nghĩa); template tự hiện '—' hoặc 'Mới' thay vì 'inf%'."""
    if not previous:
        return None
    return round((current - previous) / previous * 100)


def _monthly_recap(jobs, companies, engagement_monthly):
    """Khối 'recap' tự động cho tab Báo cáo tháng — số job/công ty mới
    tháng này (kèm % so tháng trước), top 3 ngành, top 5 công ty đăng
    nhiều job nhất tháng, và số ứng tuyển/lưu job tháng này vs tháng
    trước (lấy từ GET /stats/engagement, xem crawler_client.
    get_engagement_stats())."""
    today = datetime.now().date()
    this_y, this_m = today.year, today.month
    last_y, last_m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)

    def _in_month(raw_date, y, m):
        d = _parse_any_date(raw_date)
        return d is not None and d.year == y and d.month == m

    jobs_this_month = [j for j in jobs if _in_month(j.get("date_collected"), this_y, this_m)]
    jobs_last_month = [j for j in jobs if _in_month(j.get("date_collected"), last_y, last_m)]
    # Job hết hạn tháng này = deadline rơi vào tháng này VÀ đã thực sự
    # qua hạn tính đến hôm nay (nhất quán với _jobs_by_month(only_past=True)
    # dùng cho biểu đồ ở tab Tổng quan).
    jobs_expired_this_month = [
        j for j in jobs
        if _in_month(j.get("deadline"), this_y, this_m) and _parse_any_date(j.get("deadline")) < today
    ]
    companies_this_month = [c for c in companies if _in_month(c.get("date_collected"), this_y, this_m)]
    companies_last_month = [c for c in companies if _in_month(c.get("date_collected"), last_y, last_m)]

    industry_this: dict = {}
    for j in jobs_this_month:
        ind = j.get("industry") or "Khác"
        industry_this[ind] = industry_this.get(ind, 0) + 1
    industry_last: dict = {}
    for j in jobs_last_month:
        ind = j.get("industry") or "Khác"
        industry_last[ind] = industry_last.get(ind, 0) + 1
    top_industries = [
        {"industry": ind, "count": cnt, "pct_change": _pct_change(cnt, industry_last.get(ind, 0))}
        for ind, cnt in sorted(industry_this.items(), key=lambda kv: -kv[1])[:3]
    ]

    company_job_count: dict = {}
    for j in jobs_this_month:
        cid = j.get("company_id")
        if cid:
            company_job_count[cid] = company_job_count.get(cid, 0) + 1
    companies_idx = {c["id"]: c for c in companies}
    top_companies = [
        {"company": companies_idx.get(cid, {}).get("company", "—"), "company_id": cid, "count": cnt}
        for cid, cnt in sorted(company_job_count.items(), key=lambda kv: -kv[1])[:5]
    ]

    monthly = engagement_monthly or {}
    applications = monthly.get("applications") or {}
    saved_jobs = monthly.get("saved_jobs") or {}

    return {
        "jobs_new": len(jobs_this_month),
        "jobs_new_pct": _pct_change(len(jobs_this_month), len(jobs_last_month)),
        "jobs_expired": len(jobs_expired_this_month),
        "companies_new": len(companies_this_month),
        "companies_new_pct": _pct_change(len(companies_this_month), len(companies_last_month)),
        "top_industries": top_industries,
        "top_companies": top_companies,
        "applications_this_month": applications.get("this_month", 0),
        "applications_pct": _pct_change(applications.get("this_month", 0), applications.get("last_month", 0)),
        "saved_jobs_this_month": saved_jobs.get("this_month", 0),
        "saved_jobs_pct": _pct_change(saved_jobs.get("this_month", 0), saved_jobs.get("last_month", 0)),
    }


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.route("/dashboard")
@staff_required
def dashboard():
    try:
        # list_all_jobs() (không phải list_jobs()) — backend giới hạn
        # 200 job/request, nhưng dashboard cần TOÀN BỘ job (không chỉ
        # 200 job đầu) để mọi số liệu/biểu đồ khớp đúng tổng thật, đặc
        # biệt là biểu đồ JD theo tháng bên dưới (cần biết deadline/
        # date_collected của từng job, kể cả các job ngoài 200 đầu).
        jobs = db_data.list_all_jobs()
        companies = _list_all_companies()
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        jobs, companies = [], []

    jobs_by_industry = {ind: sum(1 for j in jobs if j["industry"] == ind) for ind in INDUSTRIES}
    jobs_by_level = {lv: sum(1 for j in jobs if j["level"] == lv) for lv in LEVELS}
    jobs_by_status = {st: sum(1 for j in jobs if j["status"] == st) for st in JOB_STATUSES}
    jobs_by_location = {}
    for j in jobs:
        jobs_by_location[j["location"]] = jobs_by_location.get(j["location"], 0) + 1

    # JD theo tháng (6 tháng gần nhất) — so sánh JD mới thêm vào hệ
    # thống (date_collected) vs JD đã THỰC SỰ hết hạn tính đến hôm nay
    # (deadline, only_past=True — job có deadline còn ở tương lai vẫn
    # đang mở, không tính vào đây). Dùng cho biểu đồ cột kép Chart.js ở
    # đầu trang dashboard.
    monthly_labels, monthly_new = _jobs_by_month(jobs, "date_collected", months_back=6)
    _, monthly_expired = _jobs_by_month(jobs, "deadline", months_back=6, only_past=True)

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
    # Tổng đơn ứng tuyển: backend đã bổ sung total_applications vào
    # GET /stats (commit b508644, 08/2026) — gọi 1 lần, không cần lặp
    # qua từng job. Lỗi backend tạm thời thì hiện None (ẩn ở template)
    # thay vì làm sập cả trang dashboard.
    total_applications = None
    total_saved_jobs = None
    try:
        stats = db_data.get_stats()
        total_applications = stats.get("total_applications")
        # Thêm 08/2026 cùng lúc với /student-activity (theo dõi học
        # viên lưu/ứng tuyển JD) — backend đã bổ sung total_saved_jobs
        # cân xứng total_applications ở trên, xem db.get_stats_summary().
        total_saved_jobs = stats.get("total_saved_jobs")
    except CrawlerAPIError:
        pass

    # ---- Dữ liệu riêng cho 3 tab mới (Gợi ý học viên / Doanh nghiệp /
    # Báo cáo tháng) — xem trao đổi thiết kế "dashboard 4 tab". Gọi
    # GET /stats/engagement (thêm 08/2026) 1 lần, gộp counts vào `jobs`
    # đã có sẵn; lỗi backend tạm thời thì các tab này hiện rỗng thay vì
    # làm sập cả trang (giống pattern total_applications ở trên).
    try:
        engagement = db_data.get_engagement_stats()
    except CrawlerAPIError:
        engagement = {}
    _merge_engagement_into_jobs(jobs, engagement.get("jobs", []))

    # Contact cần cho tab Doanh nghiệp (công ty tiềm năng thiếu contact)
    # — dashboard trước đây không gọi /contacts, giờ cần để join với
    # companies theo company_id. Cùng access_token đã lấy ở trên cho
    # total_students.
    try:
        all_contacts = db_data.list_all_contacts(access_token) if access_token else []
    except CrawlerAPIError:
        all_contacts = []

    jd_needing_push = _jd_needing_push(jobs)
    jd_stale = _jd_stale(jobs)
    top_skills = _top_skills(jobs)
    salary_ranges = _salary_ranges_by_industry_level(jobs)

    companies_no_contact = _companies_high_potential_no_contact(companies, all_contacts)
    companies_expanding, companies_quiet = _companies_job_activity(jobs, companies)

    monthly_recap = _monthly_recap(jobs, companies, engagement.get("monthly"))

    return render_template(
        "dashboard.html",
        total_jobs=len(jobs), total_contacts=len(companies),
        total_students=total_students, total_applications=total_applications,
        total_saved_jobs=total_saved_jobs,
        jobs_by_industry=jobs_by_industry, jobs_by_level=jobs_by_level,
        jobs_by_status=jobs_by_status, jobs_by_location=jobs_by_location,
        contacts_by_city=companies_by_city,
        # Biểu đồ JD theo tháng (Chart.js, xem templates/dashboard.html)
        # — encode sẵn thành JSON string ở đây (không phải trong
        # template) vì |tojson trong Jinja tự escape để an toàn nhúng
        # vào <script>, dùng nhất quán với cách các trang khác truyền
        # dữ liệu list/dict cho JS.
        monthly_labels=monthly_labels,
        monthly_new=monthly_new,
        monthly_expired=monthly_expired,
        # Tab "Gợi ý học viên"
        jd_needing_push=jd_needing_push,
        jd_stale=jd_stale,
        top_skills=top_skills,
        salary_ranges=salary_ranges,
        # Tab "Doanh nghiệp"
        companies_no_contact=companies_no_contact,
        companies_expanding=companies_expanding,
        companies_quiet=companies_quiet,
        # Tab "Báo cáo tháng"
        recap=monthly_recap,
    )


# ---------------------------------------------------------------------------
# Quản lý tài khoản team SS (đọc: ss_team+, tạo/đổi role/khoá-mở khoá:
# admin-only — backend tự chặn 403 nếu gọi sai quyền, ở đây check thêm
# để UI không hiện nút/form vô ích cho người không có quyền bấm).
# ---------------------------------------------------------------------------

@app.route("/staff-accounts")
@staff_required
def staff_accounts():
    access_token, _ = _auth_tokens_from_session()
    try:
        users = backend_auth.list_users(access_token)
    except BackendAuthError as exc:
        flash(str(exc), "error")
        users = []

    # Mật khẩu tạm của tài khoản VỪA tạo (nếu có) — session.pop() để
    # chỉ hiện đúng 1 lần, F5/quay lại trang sau đó sẽ không còn thấy.
    new_account = session.pop("new_staff_account", None)

    return render_template(
        "staff_accounts.html", users=users, role_labels=ROLE_LABELS,
        roles=list(ROLE_LABELS.keys()), new_account=new_account,
    )


@app.route("/staff-accounts/add", methods=["GET", "POST"])
@staff_required
def staff_account_add():
    if current_user.role != "admin":
        flash("Chỉ tài khoản admin mới tạo được tài khoản mới.", "error")
        return redirect(url_for("staff_accounts"))

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
        return redirect(url_for("staff_accounts"))

    return render_template("staff_account_add.html", role_labels=ROLE_LABELS, form={})


@app.route("/staff-accounts/<string:ss_user_id>/role", methods=["POST"])
@staff_required
def staff_account_update_role(ss_user_id):
    if current_user.role != "admin":
        flash("Chỉ tài khoản admin mới đổi được role.", "error")
        return redirect(url_for("staff_accounts"))

    role = request.form.get("role", "")
    if role not in ROLE_LABELS:
        abort(400)

    access_token, _ = _auth_tokens_from_session()
    try:
        backend_auth.update_user_role(access_token, ss_user_id, role)
        flash("Đã cập nhật role.", "success")
    except BackendAuthError as exc:
        flash(str(exc), "error")
    return redirect(url_for("staff_accounts"))


@app.route("/staff-accounts/<string:ss_user_id>/active-status", methods=["POST"])
@staff_required
def staff_account_update_active_status(ss_user_id):
    if current_user.role != "admin":
        flash("Chỉ tài khoản admin mới khoá/mở khoá được tài khoản.", "error")
        return redirect(url_for("staff_accounts"))

    # Form gửi giá trị "true"/"false" (string) — không dùng checkbox vì
    # checkbox không gửi field khi unchecked, khó phân biệt "false" với
    # "không gửi field" trong request.form.get().
    is_active_raw = request.form.get("is_active", "")
    if is_active_raw not in ("true", "false"):
        abort(400)
    is_active = is_active_raw == "true"

    access_token, _ = _auth_tokens_from_session()
    try:
        backend_auth.update_user_active_status(access_token, ss_user_id, is_active)
        flash(
            "Đã kích hoạt lại tài khoản." if is_active else "Đã vô hiệu hoá tài khoản.",
            "success",
        )
    except BackendAuthError as exc:
        flash(str(exc), "error")
    return redirect(url_for("staff_accounts"))


# ---------------------------------------------------------------------------
# Hoạt động học viên — theo dõi học viên đang lưu/ứng tuyển JD nào
# (thêm 08/2026, đọc: ss_team+, giống hệt mức quyền của /staff-accounts).
#
# Trước đây SS team/admin chỉ xem được ứng tuyển theo CHIỀU "1 job có ai
# ứng tuyển" (job_detail.html) và hoàn toàn không xem được saved_jobs.
# Mục này bổ sung CHIỀU NGƯỢC LẠI, "1 học viên đã ứng tuyển/lưu job
# nào" — 2 route:
#   /student-activity            — danh sách toàn bộ học viên (role=
#                                   'user'), tái dùng GET /auth/users đã
#                                   có sẵn (KHÔNG gọi thêm API nào khác
#                                   ở đây — quan trọng để trang danh
#                                   sách luôn nhẹ dù số học viên tăng
#                                   lên nhiều trong tương lai, không bị
#                                   N+1 request).
#   /student-activity/<id>       — chi tiết 1 học viên, CHỈ lúc này mới
#                                   gọi 2 API mới GET /auth/users/{id}/
#                                   applications và .../saved-jobs (lazy
#                                   — đúng học viên nào đang xem mới gọi
#                                   cho học viên đó).
# ---------------------------------------------------------------------------

@app.route("/student-activity")
@staff_required
def student_activity_index():
    access_token, _ = _auth_tokens_from_session()
    try:
        all_users = backend_auth.list_users(access_token)
    except BackendAuthError as exc:
        flash(str(exc), "error")
        all_users = []

    # Chỉ role='user' mới có JD để ứng tuyển/lưu — ss_team/admin không
    # phải đối tượng cần theo dõi ở màn hình này (khác /staff-accounts,
    # liệt kê MỌI role vì đó là màn hình quản lý tài khoản nói chung).
    students = [u for u in all_users if u.get("role") == "user"]

    return render_template("student_activity.html", students=students)


@app.route("/student-activity/<string:ss_user_id>")
@staff_required
def student_activity_detail(ss_user_id):
    access_token, _ = _auth_tokens_from_session()

    # GET /auth/users/{id}/applications và .../saved-jobs (2 route mới,
    # xem backend_auth.py) không trả kèm full_name/email của chính học
    # viên đang xem (chỉ trả thông tin JOB) — cần tra riêng qua GET
    # /auth/users để hiện tên ở đầu trang. list_users() đã gọi ở trang
    # danh sách phía trên, nhưng đây là 1 request GET riêng (người dùng
    # có thể vào thẳng URL này qua link ngoài), nên gọi lại — chấp nhận
    # thêm 1 lần gọi API, không đáng kể so với lợi ích trang list ở trên
    # không bị N+1.
    student = None
    try:
        all_users = backend_auth.list_users(access_token)
        student = next((u for u in all_users if u["ss_user_id"] == ss_user_id and u.get("role") == "user"), None)
    except BackendAuthError as exc:
        flash(str(exc), "error")
    if student is None:
        abort(404)

    try:
        applications = backend_auth.list_applications_of_user(access_token, ss_user_id)
    except BackendAuthError as exc:
        flash(str(exc), "error")
        applications = []

    try:
        saved_jobs = backend_auth.list_saved_jobs_of_user(access_token, ss_user_id)
    except BackendAuthError as exc:
        flash(str(exc), "error")
        saved_jobs = []

    return render_template(
        "student_activity_detail.html", student=student,
        applications=applications, saved_jobs=saved_jobs,
    )


# ---------------------------------------------------------------------------
# Hoạt động team SS/admin — theo dõi 1 thành viên đã tự thêm job/company/
# contact nào, và đang được giao phụ trách contact nào (thêm 08/2026).
#
# Mirror ĐÚNG cấu trúc 2-route của /student-activity ở trên (xem comment
# khối đó để biết lý do tách index/detail: trang danh sách KHÔNG gọi
# thêm API nào ngoài GET /auth/users để luôn nhẹ dù số staff tăng lên,
# việc đếm/liệt kê job-company-contact CHỈ xảy ra khi bấm vào xem 1
# người cụ thể). Khác /student-activity ở việc lọc role != 'user' (staff
# thay vì học viên), và trang chi tiết có 4 mục thay vì 2 (job đã tạo,
# company đã tạo, contact đã tạo, contact được giao phụ trách) — 2 mục
# cuối dùng 2 field ĐỘC LẬP nhau của company_contacts (created_by vs
# assigned_ss_user, xem crawler_client.list_all_contacts()).
# ---------------------------------------------------------------------------

@app.route("/staff-activity")
@staff_required
def staff_activity_index():
    access_token, _ = _auth_tokens_from_session()
    try:
        all_users = backend_auth.list_users(access_token)
    except BackendAuthError as exc:
        flash(str(exc), "error")
        all_users = []

    staff_members = [u for u in all_users if u.get("role") in ("ss_team", "admin")]

    return render_template("staff_activity.html", staff_members=staff_members)


@app.route("/staff-activity/<string:ss_user_id>")
@staff_required
def staff_activity_detail(ss_user_id):
    access_token, _ = _auth_tokens_from_session()

    staff_member = None
    all_users = []
    try:
        all_users = backend_auth.list_users(access_token)
        staff_member = next(
            (u for u in all_users if u["ss_user_id"] == ss_user_id and u.get("role") in ("ss_team", "admin")),
            None,
        )
    except BackendAuthError as exc:
        flash(str(exc), "error")
    if staff_member is None:
        abort(404)

    # staff_members: dropdown "gán phụ trách" ngay trên trang này (đổi
    # người phụ trách 1 contact mà không cần rời trang) — cùng danh sách
    # dùng ở contacts.html. staff_by_id: tra tên "người tạo" hiển thị ở
    # mục "Contact đang phụ trách" bên dưới (người tạo có thể KHÁC người
    # đang xem trang này, vì đây là 2 field độc lập).
    staff_members = [u for u in all_users if u.get("role") in ("ss_team", "admin")]
    staff_by_id = {u["ss_user_id"]: u for u in all_users}

    try:
        jobs_created = db_data.list_all_jobs(created_by=ss_user_id)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        jobs_created = []

    try:
        companies_created = db_data.list_all_companies(created_by=ss_user_id)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        companies_created = []

    try:
        contacts_created = db_data.list_all_contacts(access_token, created_by=ss_user_id)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        contacts_created = []

    try:
        contacts_assigned = db_data.list_all_contacts(access_token, assigned_ss_user=ss_user_id)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        contacts_assigned = []

    return render_template(
        "staff_activity_detail.html", staff_member=staff_member,
        staff_members=staff_members, staff_by_id=staff_by_id,
        jobs_created=jobs_created, companies_created=companies_created,
        contacts_created=contacts_created, contacts_assigned=contacts_assigned,
    )


# ---------------------------------------------------------------------------
# Activity Logs — Lịch sử thao tác (audit log)
# ---------------------------------------------------------------------------

@app.route("/activity-logs")
@staff_required
def activity_logs():
    """Trang lịch sử thao tác — 2 tab ?view=auto (tự động) / ?view=manual
    (thủ công), filter theo entity_type/company/actor. Khác /staff-activity
    (tổng hợp JD/công ty/contact theo người tạo) — đây là nhật ký TỪNG thao
    tác chi tiết theo thời gian, có note."""
    view = request.args.get("view", "auto")
    if view not in ("auto", "manual"):
        view = "auto"
    entity_type = request.args.get("entity_type", "")
    company_id = request.args.get("company_id", "")
    actor_id = request.args.get("actor_id", "")

    access_token, _ = _auth_tokens_from_session()
    try:
        # Pagination
        page, per_page = _paginate_args(50)  # 50 logs/trang, vừa đủ cho bảng chi tiết
        offset = (page - 1) * per_page

        result = db_data.list_audit_logs(
            access_token, view=view, entity_type=entity_type,
            company_id=company_id, actor_id=actor_id,
            limit=per_page, offset=offset,
        )
        logs = result["items"]
        total_logs = result["total"]
        total_pages = max(1, math.ceil(total_logs / per_page))
        if page > total_pages:
            page = total_pages
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        logs, total_logs, total_pages, page = [], 0, 1, 1

    # Dropdown công ty/staff cho filter
    try:
        companies = _list_all_companies()
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        companies = []
    try:
        all_users = backend_auth.list_users(access_token)
        staff_members = [u for u in all_users if u.get("role") in ("ss_team", "admin")]
    except BackendAuthError as exc:
        flash(str(exc), "error")
        staff_members = []

    entity_types = list(db_data.ENTITY_TYPE_MAP.values())  # ["JD", "Công ty", "Người liên hệ"]

    return render_template(
        "activity_logs.html", logs=logs, view=view,
        entity_types=entity_types, companies=companies, staff_members=staff_members,
        filters={"entity_type": entity_type, "company_id": company_id, "actor_id": actor_id},
        pagination_filters={k: v for k, v in
                             {"entity_type": entity_type, "company_id": company_id, "actor_id": actor_id}.items() if v},
        total_logs=total_logs, page=page, total_pages=total_pages, per_page=per_page,
    )


@app.route("/activity-logs/<string:log_id>/note", methods=["POST"])
@staff_required
def activity_log_update_note(log_id):
    """Sửa note của 1 log — backend CHỈ cho phép actor gốc sửa (xem
    api/routers/audit_logs.py::update_note), app.py ẨN nút sửa nếu
    current_user khác actor nhưng vẫn phải bắt 403 phòng gọi thẳng URL."""
    note = request.form.get("note", "").strip()
    access_token, _ = _auth_tokens_from_session()
    try:
        _call_authed(db_data.update_audit_log_note, log_id, note)
        flash("Đã cập nhật ghi chú.", "success")
    except CrawlerAPIError as exc:
        if exc.status_code == 403:
            flash("Bạn không có quyền sửa ghi chú của người khác.", "error")
        else:
            flash(str(exc), "error")
    return redirect(url_for("activity_logs", view=request.args.get("view", "auto")))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
