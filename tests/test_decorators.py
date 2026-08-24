"""Lớp 2 cho utils/decorators.py::staff_required.

4 nhánh cần cover (theo đúng thứ tự check trong code):
  1. Chưa đăng nhập -> redirect (HTML) hoặc 401 JSON (tuỳ header
     X-Requested-With).
  2. Đã đăng nhập nhưng không phải staff (role='user'/học viên) -> chặn.
  3. Là staff nhưng must_change_password=True -> ép về đổi mật khẩu,
     TRỪ chính route change_password/logout (không tự khoá lối thoát).
  4. Đủ điều kiện -> cho qua, chạy view thật.

Dùng route /data-management (bất kỳ route @staff_required nào cũng
được — chọn route đơn giản nhất) làm route thử nghiệm thay vì tạo route
giả riêng, để test đi qua đúng decorator thật đang gắn trên blueprint
thật.
"""

import pytest


class TestStaffRequiredNotAuthenticated:
    def test_html_request_redirects_to_login(self, client):
        resp = client.get("/data-management")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_json_request_returns_401(self, client):
        resp = client.get(
            "/data-management/import/job/company-suggestions",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 401
        assert resp.get_json()["error"]


class TestStaffRequiredNonStaff:
    def test_student_redirected_to_jobs_index(self, student_client):
        resp = student_client.get("/data-management")
        assert resp.status_code == 302
        # jobs.index đăng ký cả ở "/" lẫn "/jobs" — chỉ cần chắc chắn
        # KHÔNG bị đá về login (đã đăng nhập rồi, chỉ là sai quyền)
        assert "/login" not in resp.headers["Location"]

    def test_student_json_request_returns_403(self, student_client):
        resp = student_client.get(
            "/data-management/import/job/company-suggestions",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 403
        assert resp.get_json()["error"]


class TestStaffRequiredMustChangePassword:
    def test_redirects_to_change_password(self, must_change_password_client):
        resp = must_change_password_client.get("/data-management")
        assert resp.status_code == 302
        assert "change-password" in resp.headers["Location"]

    def test_json_request_returns_403(self, must_change_password_client):
        resp = must_change_password_client.get(
            "/data-management/import/job/company-suggestions",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 403
        assert resp.get_json()["error"]

    def test_change_password_route_itself_not_blocked(self, must_change_password_client, mocker):
        """View tên 'change_password' phải được LOẠI TRỪ khỏi vòng lặp ép
        đổi mật khẩu — nếu không, user must_change_password=True sẽ bị
        redirect vô hạn (không bao giờ tới được trang đổi mật khẩu)."""
        # change_password() thật gọi backend — GET chỉ render form, không
        # gọi crawler/backend_auth nên không cần mock gì thêm.
        resp = must_change_password_client.get("/change-password")
        assert resp.status_code == 200


class TestStaffRequiredHappyPath:
    def test_staff_passes_through(self, staff_client, mocker):
        # Route /data-management gọi db_data.get_level_codes() và có thể
        # cả get_import_preview() nếu ?preview= có mặt — mock get_level_codes
        # để test chỉ tập trung vào decorator, không phụ thuộc network.
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern", "Fresher"],
        )
        resp = staff_client.get("/data-management")
        assert resp.status_code == 200

    def test_admin_also_passes_through(self, flask_app, admin_user, mocker):
        from tests.conftest import _login_client

        mocker.patch("app.backend_auth.get_me", return_value={
            "ss_user_id": admin_user.id, "email": admin_user.email,
            "full_name": admin_user.full_name, "role": "admin",
            "must_change_password": False, "is_active": True,
        })
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        admin_client = _login_client(flask_app, admin_user)
        resp = admin_client.get("/data-management")
        assert resp.status_code == 200
