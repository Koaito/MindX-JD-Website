"""Lớp 3 cho blueprints/my_stuff.py.

test_staff_cannot_access_saved_jobs_page là test regression cho bug thật
đã xảy ra (08/2026): route GET /profile/saved-jobs thiếu check
current_user.is_staff — khác 4 route còn lại trong cùng blueprint
(job_toggle_save, job_toggle_save_json, job_apply, job_withdraw đều chặn
staff, my_applications cũng redirect staff). Hậu quả: 1 tài khoản vừa
được nâng role từ 'user' lên 'ss_team' (còn dữ liệu saved_jobs cũ từ lúc
còn là học viên) vẫn xem được trang này nếu gõ thẳng URL, dù sidebar đã
ẩn link — không đồng nhất với my_applications() đã chặn đúng cách.

08/2026 (đợt 2): URL thật của trang này dời từ /saved-jobs sang
/profile/saved-jobs (vào sub-nav trang cá nhân, xem blueprints/profile.py
và _profile_subnav.html) — /saved-jobs cũ giờ chỉ còn redirect 302, xem
TestSavedJobsLegacyRedirect bên dưới.
"""

from backend_auth import BackendAuthError


class TestSavedJobsPage:
    def test_staff_cannot_access_saved_jobs_page(self, staff_client, mocker):
        """Regression: staff gõ thẳng URL /profile/saved-jobs phải bị
        redirect, không được xem lại danh sách job đã lưu từ trước khi
        lên role."""
        list_saved_mock = mocker.patch(
            "blueprints.my_stuff.backend_auth.list_my_saved_jobs"
        )
        resp = staff_client.get("/profile/saved-jobs", follow_redirects=False)
        assert resp.status_code == 302
        assert "/dashboard" in resp.headers["Location"] or resp.headers[
            "Location"
        ].endswith("/")
        # Không được gọi xuống backend để lấy dữ liệu đã lưu cho staff.
        list_saved_mock.assert_not_called()

    def test_student_sees_saved_jobs_list(self, student_client, mocker):
        mocker.patch(
            "blueprints.my_stuff.backend_auth.list_my_saved_jobs",
            return_value=[{"job_id": "job-1"}],
        )
        mocker.patch(
            "blueprints.my_stuff.db_data.get_job",
            return_value={"id": "job-1", "job_id": "job-1", "title": "Backend Intern"},
        )
        resp = student_client.get("/profile/saved-jobs")
        assert resp.status_code == 200

    def test_student_backend_error_flashes_and_renders_empty(self, student_client, mocker):
        mocker.patch(
            "blueprints.my_stuff.backend_auth.list_my_saved_jobs",
            side_effect=BackendAuthError("lỗi backend", status_code=500),
        )
        resp = student_client.get("/profile/saved-jobs")
        assert resp.status_code == 200


class TestSavedJobsLegacyRedirect:
    """08/2026 — /saved-jobs cũ phải redirect sang /profile/saved-jobs
    mới, giữ nguyên cho cả staff lẫn học viên (không tự chặn staff ở
    route legacy — việc chặn staff đã nằm ở route thật phía sau)."""

    def test_legacy_url_redirects_to_profile_path(self, student_client):
        resp = student_client.get("/saved-jobs", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/profile/saved-jobs")

    def test_legacy_url_redirects_for_staff_too(self, staff_client):
        resp = staff_client.get("/saved-jobs", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/profile/saved-jobs")


class TestMyApplicationsLegacyRedirect:
    """08/2026 — /my-applications cũ phải redirect sang
    /profile/applications mới."""

    def test_legacy_url_redirects_to_profile_path(self, student_client):
        resp = student_client.get("/my-applications", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/profile/applications")
