"""Lớp 3 cho blueprints/my_stuff.py.

test_staff_cannot_access_saved_jobs_page là test regression cho bug thật
đã xảy ra (08/2026): route GET /saved-jobs thiếu check current_user.is_staff
— khác 4 route còn lại trong cùng blueprint (job_toggle_save,
job_toggle_save_json, job_apply, job_withdraw đều chặn staff, my_applications
cũng redirect staff). Hậu quả: 1 tài khoản vừa được nâng role từ 'user' lên
'ss_team' (còn dữ liệu saved_jobs cũ từ lúc còn là học viên) vẫn xem được
trang này nếu gõ thẳng URL, dù sidebar đã ẩn link — không đồng nhất với
my_applications() đã chặn đúng cách.
"""

from backend_auth import BackendAuthError


class TestSavedJobsPage:
    def test_staff_cannot_access_saved_jobs_page(self, staff_client, mocker):
        """Regression: staff gõ thẳng URL /saved-jobs phải bị redirect,
        không được xem lại danh sách job đã lưu từ trước khi lên role."""
        list_saved_mock = mocker.patch(
            "blueprints.my_stuff.backend_auth.list_my_saved_jobs"
        )
        resp = staff_client.get("/saved-jobs", follow_redirects=False)
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
        resp = student_client.get("/saved-jobs")
        assert resp.status_code == 200

    def test_student_backend_error_flashes_and_renders_empty(self, student_client, mocker):
        mocker.patch(
            "blueprints.my_stuff.backend_auth.list_my_saved_jobs",
            side_effect=BackendAuthError("lỗi backend", status_code=500),
        )
        resp = student_client.get("/saved-jobs")
        assert resp.status_code == 200
