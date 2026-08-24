"""Fixtures dùng chung cho toàn bộ test suite.

Vài điểm cần biết khi đọc/sửa file này:

1. CRAWLER_API_KEY được set TRƯỚC khi import bất kỳ module nào của app
   (xem dòng os.environ ở đầu file, chạy trước mọi `import`). Thiếu biến
   này, `crawler_client._headers()` / `backend_auth._headers()` sẽ tự
   raise lỗi ngay cả với các hàm chỉ đọc dict tĩnh không gọi mạng gì —
   xem crawler_client.py dòng 77-86.

2. `reset_enums_cache` là fixture autouse — tự chạy trước MỌI test,
   không cần khai báo trong signature. Nó reset biến cấp module
   `crawler_client._enums_cache` về rỗng trước mỗi test, tránh tình
   trạng test A chạy trước "làm bẩn" cache khiến test B (chạy sau) nhận
   nhầm dữ liệu cũ — xem crawler_client.py dòng 150.

3. `app` fixture import thẳng module app.py thật (không tự dựng Flask
   app giả) để test đi qua đúng cấu hình blueprint/login_manager thật.
   Vì Python cache module, `app.py` chỉ thực sự chạy 1 lần cho cả test
   session (session-scoped) — các side-effect (đăng ký blueprint...) chỉ
   xảy ra 1 lần, đúng ý muốn.

4. `staff_user` / `logged_in_staff_client` dựng 1 `auth.BackendUser` giả
   đúng interface thật (is_staff, must_change_password...) — KHÔNG gọi
   backend thật nào. Dùng `flask_login.login_user()` trong 1 request
   context tạm để set session, rồi tái sử dụng session đó cho client.
"""

import os

os.environ.setdefault("CRAWLER_API_KEY", "test-key")

import pytest

import crawler_client
from auth import BackendUser


@pytest.fixture(autouse=True)
def reset_enums_cache():
    """Tự chạy trước MỖI test — tránh rò rỉ cache giữa các test.

    Không dùng fixture này (hoặc quên gọi) sẽ khiến test pass/fail phụ
    thuộc thứ tự chạy — rất khó debug về sau (xem điểm #2 đã bàn khi lên
    kế hoạch)."""
    crawler_client._enums_cache["data"] = None
    crawler_client._enums_cache["fetched_at"] = 0.0
    yield
    crawler_client._enums_cache["data"] = None
    crawler_client._enums_cache["fetched_at"] = 0.0


@pytest.fixture(scope="session")
def flask_app():
    """Import app.py thật 1 lần cho cả session test."""
    import app as app_module

    app_module.app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SERVER_NAME="localhost",
    )
    return app_module.app


@pytest.fixture()
def client(flask_app):
    """Flask test client CHƯA đăng nhập — dùng cho test decorator
    staff_required (case chưa login)."""
    return flask_app.test_client()


def _make_backend_user(**overrides):
    """Dựng 1 auth.BackendUser giả, khớp đúng interface thật
    (BackendUser.__init__ đọc từ dict kiểu response GET /auth/me) —
    không gọi backend thật nào."""
    me = {
        "ss_user_id": "staff-001",
        "email": "staff@example.com",
        "full_name": "Nguyen Van Staff",
        "role": "ss_team",
        "must_change_password": False,
        "is_active": True,
    }
    me.update(overrides)
    return BackendUser(me)


@pytest.fixture()
def staff_user():
    """1 BackendUser giả, role ss_team, đã đổi mật khẩu — case "đủ điều
    kiện" cơ bản nhất cho staff_required."""
    return _make_backend_user()


@pytest.fixture()
def admin_user():
    return _make_backend_user(ss_user_id="admin-001", email="admin@example.com", role="admin")


@pytest.fixture()
def student_user():
    return _make_backend_user(ss_user_id="student-001", email="student@example.com", role="user")


@pytest.fixture()
def must_change_password_user():
    return _make_backend_user(ss_user_id="staff-002", must_change_password=True)


def _login_client(flask_app, user):
    """Đăng nhập `user` vào 1 test client mới qua flask_login.login_user(),
    KHÔNG qua form/backend thật. Trả về client đã mang session cookie."""
    from flask_login import login_user

    client = flask_app.test_client()
    with client.session_transaction() as sess:
        pass  # đảm bảo session cookie tồn tại trước khi login_user set thêm key

    with flask_app.test_request_context():
        login_user(user)
        # login_user() ghi vào flask.session của request context tạm này —
        # cần copy thủ công sang session_transaction() của client vì đây
        # là 2 request context khác nhau.
        from flask import session as tmp_session
        session_data = dict(tmp_session)

    with client.session_transaction() as sess:
        sess.update(session_data)
        # Token giả — đủ để _auth_tokens_from_session() không trả None,
        # nhưng lớp 3 mock hết crawler_client/backend_auth nên giá trị
        # thật của token không quan trọng.
        sess["access_token"] = "fake-access-token"
        sess["refresh_token"] = "fake-refresh-token"

    return client


@pytest.fixture()
def staff_client(flask_app, staff_user, mocker):
    """Test client ĐÃ login staff. Patch load_user() để mỗi request Flask-
    Login "load lại" đúng staff_user này (thay vì gọi backend_auth.get_me
    thật) — xem app.py::load_user()."""
    mocker.patch("app.backend_auth.get_me", return_value={
        "ss_user_id": staff_user.id, "email": staff_user.email,
        "full_name": staff_user.full_name, "role": staff_user.role,
        "must_change_password": staff_user.must_change_password,
        "is_active": True,
    })
    return _login_client(flask_app, staff_user)


@pytest.fixture()
def must_change_password_client(flask_app, must_change_password_user, mocker):
    mocker.patch("app.backend_auth.get_me", return_value={
        "ss_user_id": must_change_password_user.id,
        "email": must_change_password_user.email,
        "full_name": must_change_password_user.full_name,
        "role": must_change_password_user.role,
        "must_change_password": True,
        "is_active": True,
    })
    return _login_client(flask_app, must_change_password_user)


@pytest.fixture()
def student_client(flask_app, student_user, mocker):
    mocker.patch("app.backend_auth.get_me", return_value={
        "ss_user_id": student_user.id, "email": student_user.email,
        "full_name": student_user.full_name, "role": student_user.role,
        "must_change_password": False, "is_active": True,
    })
    # app.py::inject_saved_job_ids là context_processor chạy TỰ ĐỘNG trên
    # MỌI request của user không phải staff (xem app.py) — gọi
    # backend_auth.list_my_saved_jobs() để tô sáng nút "đã lưu" trên mọi
    # trang. Mock mặc định ở đây để MỌI test dùng student_client không
    # cần tự nhớ mock lại — quên mock sẽ khiến test lỡ gọi network thật.
    mocker.patch("app.backend_auth.list_my_saved_jobs", return_value=[])
    return _login_client(flask_app, student_user)
