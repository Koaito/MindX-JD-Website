import os

from env_loader import load_env_file

load_env_file()

from flask import Flask, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, current_user
from flask_wtf import CSRFProtect
from flask_wtf.csrf import CSRFError

import backend_auth
import crawler_client as db_data
from auth import BackendUser
from backend_auth import BackendAuthError
from constants import ROLE_LABELS
from crawler_client import CrawlerAPIError
from helpers import (
    _auth_tokens_from_session,
    _clear_auth_tokens,
    _store_auth_tokens,
    format_date,
    industry_class,
    to_bullets,
)

app = Flask(__name__, static_folder="public", static_url_path="")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "mindx-ss-dev-key")

# Deploy trên Vercel luôn qua HTTPS — set tường minh thay vì trông chờ default
# của Flask, để cookie session không bao giờ bị gửi qua kênh không mã hoá và
# không bị gửi kèm request cross-site.
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# CSRF protection cho toàn bộ form POST (xem templates/*.html — mỗi form có
# {{ csrf_token() }} hidden input) và các request fetch() POST bằng JS (gắn
# header X-CSRFToken qua getCsrfToken(), đọc từ <meta name="csrf-token"> ở
# base.html).
csrf = CSRFProtect(app)

login_manager = LoginManager(app)
login_manager.login_view = "auth.login"
login_manager.login_message = "Vui lòng đăng nhập để tiếp tục."
login_manager.login_message_category = "error"

# ---------------------------------------------------------------------------
# Cache-busting cho CSS/JS tĩnh
# ---------------------------------------------------------------------------

# TRƯỚC ĐÂY (khi style.css còn @import 19 file trong public/css/):
# hàm này quét thêm cả public/css/*.css để tính mtime, vì style.css tự nó
# không đổi khi sửa 1 file con — cần quét cả 19 file mới bắt được thay đổi.
#
# GIỜ (sau khi gộp bằng build_css.py — xem file đó để biết lý do): public/
# style.css là file ĐÃ ĐƯỢC BUILD, nội dung nó tự thay đổi mỗi khi
# build_css.py chạy lại (vì được ghi đè trực tiếp) — nên chỉ cần lấy mtime
# của chính style.css là đủ, không cần quét public/css/ nữa. public/css/
# giờ chỉ là mã nguồn để sửa, không phải thứ browser tải trực tiếp.
def _asset_version(filename):
    path = os.path.join(app.static_folder, filename)
    try:
        return str(int(os.path.getmtime(path)))
    except OSError:
        return "0"


app.jinja_env.globals["asset_version"] = _asset_version

# ---------------------------------------------------------------------------
# Template filters (logic thật nằm ở helpers.py — ở đây chỉ đăng ký)
# ---------------------------------------------------------------------------

app.add_template_filter(format_date, name="format_date")
app.add_template_filter(to_bullets, name="to_bullets")
app.add_template_filter(industry_class, name="industry_class")


@login_manager.user_loader
def load_user(user_id):
    access_token, refresh_token = _auth_tokens_from_session()
    if not access_token:
        return None
    try:
        me = backend_auth.get_me(access_token)
    except BackendAuthError:
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


@app.context_processor
def inject_role_labels():
    return {"role_labels": ROLE_LABELS}


@app.context_processor
def inject_saved_job_ids():
    if current_user.is_authenticated and not current_user.is_staff:
        access_token, _ = _auth_tokens_from_session()
        if access_token:
            try:
                saved = backend_auth.list_my_saved_jobs(access_token)
                return {"saved_job_ids": {s["job_id"] for s in saved}}
            except BackendAuthError:
                pass
    return {"saved_job_ids": set()}


@app.context_processor
def inject_unread_message_count():
    """Số tin nhắn chưa đọc hiện ngay ở badge sidebar (base.html) lúc
    tải trang lần đầu — public/app.js sẽ tự poll (20-30s) để cập nhật
    tiếp sau đó mà không cần tải lại trang, xem
    blueprints/messages.py::unread_count_json(). Cùng pattern
    inject_saved_job_ids() ngay trên: chỉ gọi API khi đã đăng nhập,
    nuốt lỗi (không flash) để 1 lượt gọi backend chập chờn không kéo
    theo lỗi hiển thị ở MỌI trang (badge chỉ là phụ trợ, không phải nội
    dung chính của trang đang xem)."""
    if current_user.is_authenticated:
        access_token, _ = _auth_tokens_from_session()
        if access_token:
            try:
                return {"unread_message_count": backend_auth.get_unread_count(access_token)}
            except BackendAuthError:
                pass
    return {"unread_message_count": 0}


@app.context_processor
def inject_email_templates():
    """Nạp danh sách mẫu email ra MỌI trang có nút "✉ Mẫu email"
    (contacts.html, company_detail.html — popup dùng chung, markup nằm
    1 lần ở base.html) — base.html tự nhúng thành <script
    id="emailTemplatesData"> để app.js đọc (xem getEmailTemplatesData()).

    CHỈ gọi API khi user là staff đã đăng nhập (nút "✉ Mẫu email" chỉ
    hiện ở trang staff) — tránh round-trip mạng thừa cho học viên/khách
    chưa đăng nhập, giống lý do inject_saved_job_ids() ở trên chỉ gọi
    khi cần.

    Lỗi gọi API (CrawlerAPIError) bị NUỐT ở đây (không flash) — 1 trang
    bất kỳ lỡ gặp lúc backend chập chờn không nên vì thế mà hỏng luôn cả
    trang đó chỉ vì phần phụ trợ (popup mẫu email) không tải được; popup
    khi đó tự hiện "Chưa có mẫu email nào" (xem .et-template-empty)."""
    if current_user.is_authenticated and current_user.is_staff:
        access_token, _ = _auth_tokens_from_session()
        if access_token:
            try:
                templates = db_data.list_email_templates(access_token)
                return {"email_templates": templates}
            except CrawlerAPIError:
                pass
    return {"email_templates": []}


# ---------------------------------------------------------------------------
# Register Blueprints
# ---------------------------------------------------------------------------

from blueprints.activity_logs import activity_logs_bp
from blueprints.auth import auth_bp
from blueprints.companies import companies_bp
from blueprints.contacts import contacts_bp
from blueprints.crawl import crawl_bp
from blueprints.dashboard import dashboard_bp
from blueprints.data_management import data_mgmt_bp
from blueprints.jobs import jobs_bp
from blueprints.messages import messages_bp
from blueprints.my_stuff import my_stuff_bp
from blueprints.profile import profile_bp
from blueprints.staff import staff_bp
from blueprints.staff_activity import staff_activity_bp
from blueprints.students import students_bp

app.register_blueprint(auth_bp)
app.register_blueprint(messages_bp)
app.register_blueprint(my_stuff_bp)
app.register_blueprint(profile_bp)
app.register_blueprint(jobs_bp)
app.register_blueprint(companies_bp)
app.register_blueprint(contacts_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(staff_bp)
app.register_blueprint(students_bp)
app.register_blueprint(staff_activity_bp)
app.register_blueprint(activity_logs_bp)
app.register_blueprint(data_mgmt_bp)
app.register_blueprint(crawl_bp)


# ---------------------------------------------------------------------------
# Trang lỗi tuỳ chỉnh (400/403/404/500)
# ---------------------------------------------------------------------------
# 1 template dùng chung (templates/error.html) + 1 stylesheet dùng chung
# (public/css/17-error-pages.css) cho cả 4 mã lỗi — layout giống hệt
# nhau, chỉ khác số/nội dung/tông màu ("tone"), nên tách 4 file riêng
# là dư thừa. Vẫn extends base.html (giữ nguyên sidebar + flash stack)
# để người dùng luôn có đường quay lại nav, không bị "văng" ra trang
# trắng không lối thoát — các route abort(404)/abort(403) rải rác ở
# blueprints/*.py (jobs, companies, contacts, staff_activity,
# my_stuff, data_management...) từ trước tới giờ rơi vào trang lỗi mặc
# định của Flask (không đồng bộ giao diện) vì chưa đăng ký handler.
#
# tone: "muted" (404 — không có gì sai, chỉ là không tồn tại),
#       "warn" (400/403 — cảnh báo, không phải hệ thống hỏng),
#       "danger" (500 — thật sự có lỗi ở server).


@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    """Token CSRF thiếu/hết hạn (session quá lâu không thao tác, hoặc mở lại
    form từ tab cũ) — thay vì văng ra lỗi 400 khó hiểu, flash thông báo dễ
    hiểu rồi quay lại trang trước để người dùng thử lại thao tác."""
    flash("Phiên làm việc đã hết hạn, vui lòng thử lại.", "error")
    return redirect(request.referrer or url_for("dashboard.index"))


@app.errorhandler(400)
def handle_400(e):
    return (
        render_template(
            "error.html",
            code=400,
            tone="warn",
            chip_label="Yêu cầu không hợp lệ",
            title="Yêu cầu không hợp lệ",
            message="Có gì đó không đúng với dữ liệu vừa gửi lên. Thử quay lại và kiểm tra lại thao tác vừa rồi.",
        ),
        400,
    )


@app.errorhandler(403)
def handle_403(e):
    return (
        render_template(
            "error.html",
            code=403,
            tone="warn",
            chip_label="Không đủ quyền",
            title="Bạn không có quyền truy cập trang này",
            message="Tài khoản hiện tại không đủ quyền cho khu vực này. Nếu bạn nghĩ đây là nhầm lẫn, liên hệ quản trị viên team SS.",
        ),
        403,
    )


@app.errorhandler(404)
def handle_404(e):
    return (
        render_template(
            "error.html",
            code=404,
            tone="muted",
            chip_label="Không tìm thấy",
            title="Không tìm thấy trang này",
            message="Đường dẫn không tồn tại, hoặc job/công ty này đã bị xoá hay ngừng tuyển. Kiểm tra lại link, hoặc quay về danh sách job.",
        ),
        404,
    )


@app.errorhandler(500)
def handle_500(e):
    return (
        render_template(
            "error.html",
            code=500,
            tone="danger",
            chip_label="Lỗi hệ thống",
            title="Có lỗi xảy ra ở hệ thống",
            message="Một sự cố ngoài ý muốn vừa xảy ra ở server. Thử tải lại trang — nếu vẫn lỗi, báo lại cho team kỹ thuật kèm theo thao tác bạn vừa làm.",
        ),
        500,
    )


# ---------------------------------------------------------------------------
# Run app
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
