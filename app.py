import os

from env_loader import load_env_file

load_env_file()

from flask import Flask
from flask_login import LoginManager, current_user

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
    to_bullets,
)

app = Flask(__name__, static_folder="public", static_url_path="")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "mindx-ss-dev-key")

login_manager = LoginManager(app)
login_manager.login_view = "auth.login"
login_manager.login_message = "Vui lòng đăng nhập để tiếp tục."
login_manager.login_message_category = "error"

# ---------------------------------------------------------------------------
# Cache-busting cho CSS/JS tĩnh
# ---------------------------------------------------------------------------

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
# Template filters (logic thật nằm ở helpers.py — ở đây chỉ đăng ký)
# ---------------------------------------------------------------------------

app.add_template_filter(format_date, name="format_date")
app.add_template_filter(to_bullets, name="to_bullets")


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
from blueprints.my_stuff import my_stuff_bp
from blueprints.staff import staff_bp
from blueprints.staff_activity import staff_activity_bp
from blueprints.students import students_bp

app.register_blueprint(auth_bp)
app.register_blueprint(my_stuff_bp)
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
# Run app
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
