"""Lớp 3 cho blueprints/jobs.py.

File blueprint phức tạp nhất trong 10 blueprint (234 dòng). Trọng tâm:

1. detail() — route CÔNG KHAI (không @staff_required), nhưng nội dung
   trả về PHÂN NHÁNH theo 3 trường hợp: staff (thấy applicants/savers),
   student (thấy already_applied), chưa đăng nhập (không thấy gì cả).
   Sai 1 nhánh ở đây có thể lộ dữ liệu ứng viên cho người không có quyền.

2. add() — _resolve_company_id() LỒNG 1 _call_authed (tạo công ty mới)
   bên trong route cũng gọi _call_authed khác (tạo job) — 2 lệnh gọi
   backend nối tiếp nhau, dễ vỡ nếu ai đó sửa nhầm thứ tự hoặc quên
   truyền company_id vừa tạo.

3. update_status()/delete() — "xoá" job thực ra là PATCH status=CLOSED
   (soft delete, không xoá thật) — test xác nhận đúng hành vi này.
"""

import pytest

from backend_auth import BackendAuthError
from crawler_client import CrawlerAPIError

# ---------------------------------------------------------------------------
# index() — danh sách job, route công khai
# ---------------------------------------------------------------------------

class TestJobsIndex:
    def test_renders_200_default_status_filter(self, client, mocker):
        """Không truyền ?status -> mặc định lọc 'Đang tuyển', KHÔNG phải
        rỗng (tức KHÔNG hiện job đã đóng theo mặc định)."""
        count_mock = mocker.patch("blueprints.jobs.db_data.count_jobs", return_value=0)
        mocker.patch("blueprints.jobs.db_data.list_jobs", return_value=[])
        mocker.patch("blueprints.jobs.db_data.get_level_codes", return_value=["Intern"])

        resp = client.get("/jobs")
        assert resp.status_code == 200
        assert count_mock.call_args.kwargs["status"] == "Đang tuyển"

    def test_status_all_clears_filter(self, client, mocker):
        count_mock = mocker.patch("blueprints.jobs.db_data.count_jobs", return_value=0)
        mocker.patch("blueprints.jobs.db_data.list_jobs", return_value=[])
        mocker.patch("blueprints.jobs.db_data.get_level_codes", return_value=["Intern"])

        resp = client.get("/jobs?status=ALL")
        assert resp.status_code == 200
        assert count_mock.call_args.kwargs["status"] == ""

    def test_backend_failure_still_renders_empty_list(self, client, mocker):
        mocker.patch(
            "blueprints.jobs.db_data.count_jobs", side_effect=CrawlerAPIError("backend lỗi")
        )
        mocker.patch("blueprints.jobs.db_data.get_level_codes", return_value=["Intern"])
        resp = client.get("/jobs")
        assert resp.status_code == 200

    def test_root_url_also_serves_jobs_index(self, client, mocker):
        """Route "/" alias tới cùng view jobs.index — trang chủ chính là
        danh sách job."""
        mocker.patch("blueprints.jobs.db_data.count_jobs", return_value=0)
        mocker.patch("blueprints.jobs.db_data.list_jobs", return_value=[])
        mocker.patch("blueprints.jobs.db_data.get_level_codes", return_value=["Intern"])
        resp = client.get("/")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# detail() — phân nhánh theo role, route công khai
# ---------------------------------------------------------------------------

class TestJobsDetail:
    JOB = {
        "id": "job-1", "position": "Backend Dev", "company": "ACME",
        "status": "Đang tuyển",
    }

    def test_job_not_found_404(self, client, mocker):
        mocker.patch("blueprints.jobs.db_data.get_job", return_value=None)
        resp = client.get("/jobs/does-not-exist")
        assert resp.status_code == 404

    def test_backend_error_flashes_and_redirects(self, client, mocker):
        mocker.patch(
            "blueprints.jobs.db_data.get_job", side_effect=CrawlerAPIError("backend lỗi")
        )
        resp = client.get("/jobs/job-1", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].rstrip("/") in ("/jobs", "")

    def test_anonymous_visitor_sees_no_applicants_or_savers(self, client, mocker):
        """Chưa đăng nhập -> KHÔNG được thấy applicants/savers (dữ liệu
        cá nhân học viên khác), already_applied luôn False."""
        mocker.patch("blueprints.jobs.db_data.get_job", return_value=dict(self.JOB))
        mocker.patch("blueprints.jobs.db_data.is_duplicate_candidate", return_value=False)
        applicants_mock = mocker.patch("blueprints.jobs.backend_auth.list_job_applicants")
        resp = client.get("/jobs/job-1")
        assert resp.status_code == 200
        applicants_mock.assert_not_called()

    def test_staff_sees_applicants_and_savers(self, staff_client, mocker):
        mocker.patch("blueprints.jobs.db_data.get_job", return_value=dict(self.JOB))
        mocker.patch("blueprints.jobs.db_data.is_duplicate_candidate", return_value=False)
        mocker.patch(
            "blueprints.jobs.backend_auth.list_job_applicants",
            return_value=[{
                "application_id": "app-1", "job_id": "job-1", "note": None,
                "applied_at": "2026-08-01", "full_name": "Nguyen Van A",
                "email": "a@example.com",
            }],
        )
        mocker.patch(
            "blueprints.jobs.backend_auth.list_job_savers",
            return_value=[{
                "saved_job_id": "sv-1", "job_id": "job-1", "created_at": "2026-08-02",
                "full_name": "Tran Thi B", "email": "b@example.com",
            }],
        )
        resp = staff_client.get("/jobs/job-1")
        assert resp.status_code == 200

    def test_staff_applicants_fetch_failure_does_not_crash_page(self, staff_client, mocker):
        mocker.patch("blueprints.jobs.db_data.get_job", return_value=dict(self.JOB))
        mocker.patch("blueprints.jobs.db_data.is_duplicate_candidate", return_value=False)
        mocker.patch(
            "blueprints.jobs.backend_auth.list_job_applicants",
            side_effect=BackendAuthError("lỗi"),
        )
        mocker.patch("blueprints.jobs.backend_auth.list_job_savers", return_value=[])
        resp = staff_client.get("/jobs/job-1")
        assert resp.status_code == 200

    def test_student_sees_already_applied_true(self, student_client, mocker):
        mocker.patch("blueprints.jobs.db_data.get_job", return_value=dict(self.JOB))
        mocker.patch("blueprints.jobs.db_data.is_duplicate_candidate", return_value=False)
        mocker.patch(
            "blueprints.jobs.backend_auth.list_my_applications",
            return_value=[{"job_id": "job-1"}, {"job_id": "job-other"}],
        )
        # Student KHÔNG được gọi list_job_applicants (chỉ staff mới có quyền)
        applicants_mock = mocker.patch("blueprints.jobs.backend_auth.list_job_applicants")
        resp = student_client.get("/jobs/job-1")
        assert resp.status_code == 200
        applicants_mock.assert_not_called()

    def test_student_not_applied_sees_already_applied_false(self, student_client, mocker):
        mocker.patch("blueprints.jobs.db_data.get_job", return_value=dict(self.JOB))
        mocker.patch("blueprints.jobs.db_data.is_duplicate_candidate", return_value=False)
        mocker.patch(
            "blueprints.jobs.backend_auth.list_my_applications",
            return_value=[{"job_id": "job-other"}],
        )
        resp = student_client.get("/jobs/job-1")
        assert resp.status_code == 200

    def test_is_duplicate_candidate_failure_defaults_false(self, client, mocker):
        mocker.patch("blueprints.jobs.db_data.get_job", return_value=dict(self.JOB))
        mocker.patch(
            "blueprints.jobs.db_data.is_duplicate_candidate",
            side_effect=CrawlerAPIError("lỗi"),
        )
        resp = client.get("/jobs/job-1")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# _resolve_company_id — LỒNG _call_authed bên trong route add() cũng
# dùng _call_authed khác.
# ---------------------------------------------------------------------------

class TestResolveCompanyId:
    def test_existing_company_mode_returns_id_directly(self, flask_app):
        from blueprints.jobs import _resolve_company_id
        with flask_app.test_request_context():
            result = _resolve_company_id({"company_mode": "existing", "company_id": "c-1"})
            assert result == "c-1"

    def test_existing_mode_missing_company_id_raises(self, flask_app):
        from blueprints.jobs import _resolve_company_id
        with flask_app.test_request_context(), pytest.raises(CrawlerAPIError):
            _resolve_company_id({"company_mode": "existing", "company_id": ""})

    def test_new_company_mode_missing_name_raises(self, flask_app):
        from blueprints.jobs import _resolve_company_id
        with flask_app.test_request_context(), pytest.raises(CrawlerAPIError):
            _resolve_company_id({"company_mode": "new", "new_company_name": ""})

    def test_new_company_mode_creates_and_returns_new_id(self, flask_app, mocker):
        from blueprints.jobs import _resolve_company_id
        with flask_app.test_request_context():
            from flask import session
            session["access_token"] = "tok"
            session["refresh_token"] = "refresh"
            mocker.patch(
                "blueprints.jobs.db_data.create_company",
                return_value={"id": "new-company-99"},
            )
            result = _resolve_company_id({
                "company_mode": "new", "new_company_name": "Cong Ty Moi",
            })
            assert result == "new-company-99"


class TestJobsAdd:
    def test_get_redirects_to_add_hub(self, staff_client):
        """ĐÃ ĐỔI (08/2026, xem lịch sử trao đổi "phương án A+"): GET
        /jobs/add giờ redirect sang trang gộp /them-moi?tab=job — route
        này chỉ còn xử lý POST. Xem tests/test_add_hub.py cho phần
        render form thật (đã chuyển sang add_hub.html)."""
        resp = staff_client.get("/jobs/add", follow_redirects=False)
        assert resp.status_code == 302
        assert "/them-moi" in resp.headers["Location"]
        assert "tab=job" in resp.headers["Location"]

    def test_post_existing_company_success(self, staff_client, mocker):
        mocker.patch(
            "blueprints.jobs.db_data.create_job",
            return_value={"id": "job-99", "position": "Backend Dev", "company": "ACME"},
        )
        resp = staff_client.post(
            "/jobs/add",
            data={"company_mode": "existing", "company_id": "c-1", "position": "Backend Dev"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/jobs" in resp.headers["Location"]

    def test_post_new_company_creates_company_then_job(self, staff_client, mocker):
        """2 lệnh gọi backend nối tiếp: tạo company mới -> lấy id -> tạo
        job với đúng id vừa tạo. Test đảm bảo thứ tự và dữ liệu truyền
        đúng, không bị đảo lộn."""
        create_company_mock = mocker.patch(
            "blueprints.jobs.db_data.create_company",
            return_value={"id": "brand-new-company-id"},
        )
        create_job_mock = mocker.patch(
            "blueprints.jobs.db_data.create_job",
            return_value={"id": "job-1", "position": "Dev", "company": "Cong Ty Moi"},
        )
        resp = staff_client.post(
            "/jobs/add",
            data={
                "company_mode": "new", "new_company_name": "Cong Ty Moi",
                "position": "Dev",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        create_company_mock.assert_called_once()
        # create_job phải nhận đúng company_id vừa được create_company trả về
        _, _, called_company_id = create_job_mock.call_args[0]
        assert called_company_id == "brand-new-company-id"

    def test_post_missing_company_selection_rerenders_form_with_error(self, staff_client, mocker):
        # _add_hub_context() sống trong blueprints/add_hub.py (không phải
        # blueprints/jobs.py nữa) — xem docstring jobs.add() (08/2026).
        mocker.patch("blueprints.add_hub.db_data.list_all_companies", return_value=[])
        mocker.patch("blueprints.add_hub.db_data.get_level_codes", return_value=["Intern"])
        resp = staff_client.post(
            "/jobs/add",
            data={"company_mode": "existing", "company_id": "", "position": "Dev"},
        )
        assert resp.status_code == 200  # rerender add_hub.html, KHÔNG redirect
        html = resp.get_data(as_text=True)
        assert 'data-tab="job"' in html  # vẫn còn nguyên shell 3 tab, không văng ra trang riêng

    def test_unauthenticated_redirected_to_login(self, client):
        resp = client.get("/jobs/add", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_student_cannot_access(self, student_client):
        resp = student_client.get("/jobs/add", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" not in resp.headers["Location"]


# ---------------------------------------------------------------------------
# update_status() / delete() — "xoá" job = soft delete qua PATCH status
# ---------------------------------------------------------------------------

class TestJobsUpdateStatus:
    def test_job_not_found_404(self, staff_client, mocker):
        mocker.patch("blueprints.jobs.db_data.get_job", return_value=None)
        resp = staff_client.post("/jobs/does-not-exist/status", data={"status": "CLOSED"})
        assert resp.status_code == 404

    def test_success_redirects_to_detail(self, staff_client, mocker):
        mocker.patch(
            "blueprints.jobs.db_data.get_job",
            return_value={"id": "job-1", "status": "Đang tuyển"},
        )
        mocker.patch("blueprints.jobs.db_data.update_job_status", return_value={})
        resp = staff_client.post(
            "/jobs/job-1/status", data={"status": "CLOSED"}, follow_redirects=False
        )
        assert resp.status_code == 302
        assert "/jobs/job-1" in resp.headers["Location"]


class TestJobsDelete:
    def test_delete_is_soft_delete_via_closed_status(self, staff_client, mocker):
        """'Xoá' job KHÔNG gọi API xoá thật — chỉ PATCH status=CLOSED
        (job.py không có DELETE thật, xem crawler_client.py docstring)."""
        mocker.patch(
            "blueprints.jobs.db_data.get_job",
            return_value={"id": "job-1", "status": "Đang tuyển"},
        )
        update_status_mock = mocker.patch(
            "blueprints.jobs.db_data.update_job_status", return_value={}
        )
        resp = staff_client.post("/jobs/job-1/delete", follow_redirects=False)
        assert resp.status_code == 302
        assert "/jobs" in resp.headers["Location"]
        # _call_authed(fn, job_id, "CLOSED", note) -> fn(access_token,
        # job_id, "CLOSED", note): index 0 = access_token, 1 = job_id,
        # 2 = status. Xác nhận status="CLOSED" — KHÔNG có hàm delete_job
        # nào được gọi (không tồn tại ở crawler_client.py, job không có
        # DELETE thật).
        called_args = update_status_mock.call_args[0]
        assert called_args[1] == "job-1"
        assert called_args[2] == "CLOSED"

    def test_job_not_found_404(self, staff_client, mocker):
        mocker.patch("blueprints.jobs.db_data.get_job", return_value=None)
        resp = staff_client.post("/jobs/does-not-exist/delete")
        assert resp.status_code == 404

    def test_backend_failure_redirects_to_detail_not_index(self, staff_client, mocker):
        """Khác success case (redirect về index) — lỗi thì phải redirect
        về lại trang chi tiết job đó để user thấy flash message."""
        mocker.patch(
            "blueprints.jobs.db_data.get_job",
            return_value={"id": "job-1", "status": "Đang tuyển"},
        )
        mocker.patch(
            "blueprints.jobs.db_data.update_job_status",
            side_effect=CrawlerAPIError("backend lỗi"),
        )
        resp = staff_client.post("/jobs/job-1/delete", follow_redirects=False)
        assert resp.status_code == 302
        assert "/jobs/job-1" in resp.headers["Location"]
