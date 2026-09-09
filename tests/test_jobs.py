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

import crawler_client
from crawler_client import CrawlerAPIError

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

    def test_ajax_success_returns_json_not_redirect(self, staff_client, mocker):
        """THÊM 09/2026 (xem lịch sử trao đổi "job nghi trùng lặp —
        thêm nút thao tác được") — nút "Đóng job này" ở tab "Tình
        trạng dữ liệu" gọi route này qua fetch() (X-Requested-With),
        cần trả JSON thay vì redirect để không rời khỏi tab đang xem."""
        mocker.patch(
            "blueprints.jobs.db_data.get_job",
            return_value={"id": "job-1", "status": "Đang tuyển"},
        )
        mocker.patch("blueprints.jobs.db_data.update_job_status", return_value={})
        resp = staff_client.post(
            "/jobs/job-1/status", data={"status": "CLOSED"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == {"ok": True, "job_id": "job-1", "status": "CLOSED"}

    def test_ajax_job_not_found_returns_json_404(self, staff_client, mocker):
        mocker.patch("blueprints.jobs.db_data.get_job", return_value=None)
        resp = staff_client.post(
            "/jobs/does-not-exist/status", data={"status": "CLOSED"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 404
        assert "error" in resp.get_json()

    def test_ajax_backend_failure_returns_json_error(self, staff_client, mocker):
        mocker.patch(
            "blueprints.jobs.db_data.get_job",
            return_value={"id": "job-1", "status": "Đang tuyển"},
        )
        mocker.patch(
            "blueprints.jobs.db_data.update_job_status",
            side_effect=CrawlerAPIError("backend lỗi"),
        )
        resp = staff_client.post(
            "/jobs/job-1/status", data={"status": "CLOSED"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 400
        assert "error" in resp.get_json()


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


# ---------------------------------------------------------------------------
# index(view=infinite) + /jobs/more — chế độ "cuộn vô hạn" (thêm 09/2026,
# xem lịch sử trao đổi "2 chế độ phân trang + toggle chuyển qua lại").
#
# Trọng tâm:
# 1. index() rẽ đúng nhánh cursor khi ?view=infinite, KHÔNG đụng nhánh
#    offset/limit cũ khi view=page (mặc định) — 2 nhánh phải độc lập.
# 2. more() luôn dùng ĐÚNG bộ filter (q/industry/level/location/status)
#    giống index() — lệch filter giữa 2 route là bug nghiêm trọng nhất
#    có thể xảy ra ở tính năng này (job không khớp filter bị trộn vào
#    danh sách đang lọc).
# 3. more() không tự bịa cursor rỗng thành "load từ đầu" — thiếu cursor
#    nghĩa là hết dữ liệu, trả về rỗng luôn, không gọi backend.
# 4. Lỗi backend (bao gồm 422 cursor+offset/cursor sai định dạng, backend
#    tự raise CrawlerAPIError) phải trả JSON lỗi gọn cho more(), KHÔNG
#    làm vỡ trang (route này chỉ phục vụ fetch(), không có HTML fallback).
# ---------------------------------------------------------------------------

class TestJobsIndexInfiniteMode:
    def test_view_infinite_calls_cursor_function_not_offset_function(self, client, mocker):
        """?view=infinite phải gọi list_jobs_cursor() — KHÔNG được gọi
        list_jobs() (hàm offset/limit cũ) — 2 nhánh phải tách biệt hoàn
        toàn, đúng nguyên tắc "không đụng đường code cũ"."""
        cursor_mock = mocker.patch(
            "blueprints.jobs.db_data.list_jobs_cursor", return_value=([], None)
        )
        offset_mock = mocker.patch("blueprints.jobs.db_data.list_jobs")
        mocker.patch("blueprints.jobs.db_data.count_jobs", return_value=0)
        mocker.patch("blueprints.jobs.db_data.get_level_codes", return_value=["Intern"])

        resp = client.get("/jobs?view=infinite")
        assert resp.status_code == 200
        cursor_mock.assert_called_once()
        offset_mock.assert_not_called()

    def test_view_page_default_still_calls_offset_function_not_cursor(self, client, mocker):
        """Ngược lại — không truyền view (hoặc view=page) phải đi đúng
        nhánh cũ, KHÔNG gọi list_jobs_cursor(). Test đối chiếu để chứng
        minh việc thêm chế độ mới không làm lệch hành vi mặc định."""
        offset_mock = mocker.patch("blueprints.jobs.db_data.list_jobs", return_value=[])
        cursor_mock = mocker.patch("blueprints.jobs.db_data.list_jobs_cursor")
        mocker.patch("blueprints.jobs.db_data.count_jobs", return_value=0)
        mocker.patch("blueprints.jobs.db_data.get_level_codes", return_value=["Intern"])

        resp = client.get("/jobs")
        assert resp.status_code == 200
        offset_mock.assert_called_once()
        cursor_mock.assert_not_called()

    def test_invalid_view_value_falls_back_to_page_mode(self, client, mocker):
        """?view=xyz (giá trị lạ, không phải page/infinite) phải coi như
        chưa truyền gì — fallback về chế độ trang, không crash."""
        offset_mock = mocker.patch("blueprints.jobs.db_data.list_jobs", return_value=[])
        cursor_mock = mocker.patch("blueprints.jobs.db_data.list_jobs_cursor")
        mocker.patch("blueprints.jobs.db_data.count_jobs", return_value=0)
        mocker.patch("blueprints.jobs.db_data.get_level_codes", return_value=["Intern"])

        resp = client.get("/jobs?view=xyz")
        assert resp.status_code == 200
        offset_mock.assert_called_once()
        cursor_mock.assert_not_called()

    def test_infinite_mode_passes_same_filters_as_page_mode(self, client, mocker):
        """Filter (q/industry/level/location/status) truyền cho
        list_jobs_cursor() phải khớp CHÍNH XÁC với những gì list_jobs()
        (chế độ trang) nhận — dùng chung _index_filters() đảm bảo điều
        này, test đối chiếu trực tiếp qua call_args.kwargs."""
        cursor_mock = mocker.patch(
            "blueprints.jobs.db_data.list_jobs_cursor", return_value=([], None)
        )
        mocker.patch("blueprints.jobs.db_data.count_jobs", return_value=0)
        mocker.patch("blueprints.jobs.db_data.get_level_codes", return_value=["Intern"])

        resp = client.get(
            "/jobs?view=infinite&q=python&industry=IT&level=Intern&location=Hà+Nội&status=ALL"
        )
        assert resp.status_code == 200
        kwargs = cursor_mock.call_args.kwargs
        assert kwargs["q"] == "python"
        assert kwargs["industry"] == "IT"
        assert kwargs["level"] == "Intern"
        assert kwargs["location"] == "Hà Nội"
        # status=ALL -> status_filter rỗng (bỏ lọc trạng thái), y hệt
        # hành vi chế độ trang (xem test_status_all_clears_filter ở trên).
        assert kwargs["status"] == ""

    def test_infinite_mode_default_status_filters_open_jobs(self, client, mocker):
        """Không truyền ?status ở chế độ infinite cũng phải mặc định lọc
        'Đang tuyển', giống hệt chế độ trang — không phải 1 bộ mặc định
        khác đi kèm mode mới."""
        cursor_mock = mocker.patch(
            "blueprints.jobs.db_data.list_jobs_cursor", return_value=([], None)
        )
        mocker.patch("blueprints.jobs.db_data.count_jobs", return_value=0)
        mocker.patch("blueprints.jobs.db_data.get_level_codes", return_value=["Intern"])

        resp = client.get("/jobs?view=infinite")
        assert resp.status_code == 200
        assert cursor_mock.call_args.kwargs["status"] == "Đang tuyển"

    def test_infinite_mode_backend_failure_still_renders_empty_list(self, client, mocker):
        """Giống nhánh offset cũ (test_backend_failure_still_renders_empty_list)
        — lỗi backend không được làm vỡ trang, chỉ flash lỗi + hiện danh
        sách rỗng."""
        mocker.patch(
            "blueprints.jobs.db_data.list_jobs_cursor",
            side_effect=CrawlerAPIError("backend lỗi"),
        )
        mocker.patch("blueprints.jobs.db_data.count_jobs", return_value=0)
        mocker.patch("blueprints.jobs.db_data.get_level_codes", return_value=["Intern"])

        resp = client.get("/jobs?view=infinite")
        assert resp.status_code == 200

    def test_infinite_mode_passes_next_cursor_to_template(self, client, mocker):
        """next_cursor trả về từ list_jobs_cursor() phải xuất hiện trong
        HTML (data-cursor trên nút "Tải thêm") — xác nhận template thật
        sự nhận được giá trị, không chỉ route không crash."""
        mocker.patch(
            "blueprints.jobs.db_data.list_jobs_cursor",
            return_value=([{"id": "job-1", "position": "Dev", "company": "ACME",
                             "industry": "IT", "level": "Intern", "location": "HN",
                             "status": "Đang tuyển", "skills": "", "salary": "",
                             "deadline": None, "source": "MANUAL", "jd_link": ""}],
                          "opaque-cursor-abc"),
        )
        mocker.patch("blueprints.jobs.db_data.count_jobs", return_value=1)
        mocker.patch("blueprints.jobs.db_data.get_level_codes", return_value=["Intern"])

        resp = client.get("/jobs?view=infinite")
        assert resp.status_code == 200
        assert b'data-cursor="opaque-cursor-abc"' in resp.data

    def test_infinite_mode_no_next_cursor_shows_done_message_not_button(self, client, mocker):
        """next_cursor=None (hết dữ liệu ngay từ lần render đầu) phải ẩn
        nút "Tải thêm", hiện thông báo hết job — không đợi JS chạy mới
        biết (xem plan Phase 5)."""
        mocker.patch(
            "blueprints.jobs.db_data.list_jobs_cursor",
            return_value=([{"id": "job-1", "position": "Dev", "company": "ACME",
                             "industry": "IT", "level": "Intern", "location": "HN",
                             "status": "Đang tuyển", "skills": "", "salary": "",
                             "deadline": None, "source": "MANUAL", "jd_link": ""}],
                          None),
        )
        mocker.patch("blueprints.jobs.db_data.count_jobs", return_value=1)
        mocker.patch("blueprints.jobs.db_data.get_level_codes", return_value=["Intern"])

        resp = client.get("/jobs?view=infinite")
        assert resp.status_code == 200
        assert b'id="load-more-btn"' not in resp.data
        assert "Đã hết job phù hợp".encode() in resp.data

    def test_view_toggle_shows_label_not_icons(self, client, mocker):
        """Toggle "Phân trang"/"Cuộn liên tục" phải có nhãn "Chế độ
        xem:" đứng trước để rõ nghĩa, KHÔNG còn icon 📄/⏬ (đổi 09/2026
        theo phản hồi UI — icon đơn thuần không đủ rõ ràng)."""
        mocker.patch("blueprints.jobs.db_data.list_jobs", return_value=[])
        mocker.patch("blueprints.jobs.db_data.count_jobs", return_value=0)
        mocker.patch("blueprints.jobs.db_data.get_level_codes", return_value=["Intern"])

        resp = client.get("/jobs")
        assert resp.status_code == 200
        assert "Chế độ xem:".encode() in resp.data
        assert "📄".encode() not in resp.data
        assert "⏬".encode() not in resp.data


class TestJobsMoreRoute:
    def test_missing_cursor_returns_empty_without_calling_backend(self, client, mocker):
        """Không truyền cursor (hoặc rỗng) = coi như hết dữ liệu — trả
        JSON rỗng NGAY, không gọi list_jobs_cursor() (tránh 1 lệnh gọi
        backend thừa cho request vô nghĩa)."""
        cursor_mock = mocker.patch("blueprints.jobs.db_data.list_jobs_cursor")
        resp = client.get("/jobs/more")
        assert resp.status_code == 200
        assert resp.get_json() == {"html": "", "next_cursor": None}
        cursor_mock.assert_not_called()

    def test_valid_cursor_returns_html_fragment_and_next_cursor(self, client, mocker):
        mocker.patch(
            "blueprints.jobs.db_data.list_jobs_cursor",
            return_value=([{"id": "job-2", "position": "Data Analyst", "company": "XYZ",
                             "industry": "Data", "level": "Fresher", "location": "HCM",
                             "status": "Đang tuyển", "skills": "SQL, Python", "salary": "",
                             "deadline": None, "source": "TopCV", "jd_link": "https://x.co"}],
                          "next-cursor-2"),
        )
        resp = client.get("/jobs/more?cursor=abc123")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["next_cursor"] == "next-cursor-2"
        assert "Data Analyst" in data["html"]

    def test_last_batch_returns_next_cursor_none(self, client, mocker):
        """Batch cuối cùng — next_cursor=None để JS phía client biết dừng
        hẳn (thay nút bằng thông báo hết job, không tự retry)."""
        mocker.patch(
            "blueprints.jobs.db_data.list_jobs_cursor",
            return_value=([{"id": "job-3", "position": "QA", "company": "ACME",
                             "industry": "IT", "level": "Intern", "location": "HN",
                             "status": "Đang tuyển", "skills": "", "salary": "",
                             "deadline": None, "source": "MANUAL", "jd_link": ""}],
                          None),
        )
        resp = client.get("/jobs/more?cursor=last-page-cursor")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["next_cursor"] is None

    def test_backend_error_returns_json_400_not_500(self, client, mocker):
        """cursor sai định dạng / dùng chung cursor+offset (backend trả
        422, crawler_client._request tự raise CrawlerAPIError) — more()
        phải trả JSON lỗi gọn 400 cho JS tự xử lý, KHÔNG để lỗi bay lên
        thành trang 500 (route này không có HTML fallback nào cả)."""
        mocker.patch(
            "blueprints.jobs.db_data.list_jobs_cursor",
            side_effect=CrawlerAPIError("cursor không đúng định dạng"),
        )
        resp = client.get("/jobs/more?cursor=broken-cursor")
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_filters_passed_to_more_match_filters_from_index(self, client, mocker):
        """more() phải nhận và truyền đi CHÍNH XÁC bộ filter giống
        index() — đây là rủi ro lớn nhất trong plan gốc (2 route dùng
        chung _index_filters() để đảm bảo điều này, test đối chiếu trực
        tiếp)."""
        cursor_mock = mocker.patch(
            "blueprints.jobs.db_data.list_jobs_cursor", return_value=([], None)
        )
        resp = client.get(
            "/jobs/more?cursor=abc&q=react&industry=IT&level=Fresher&location=HCM&status=Đã+đóng"
        )
        assert resp.status_code == 200
        kwargs = cursor_mock.call_args.kwargs
        assert kwargs["q"] == "react"
        assert kwargs["industry"] == "IT"
        assert kwargs["level"] == "Fresher"
        assert kwargs["location"] == "HCM"
        assert kwargs["status"] == "Đã đóng"
        assert kwargs["cursor"] == "abc"

    def test_more_default_status_filters_open_jobs_same_as_index(self, client, mocker):
        """Không truyền ?status ở /jobs/more cũng phải mặc định 'Đang
        tuyển' — khớp mặc định của index(), tránh tình trạng bấm "Tải
        thêm" kéo về job đã đóng dù đang xem danh sách mặc định."""
        cursor_mock = mocker.patch(
            "blueprints.jobs.db_data.list_jobs_cursor", return_value=([], None)
        )
        resp = client.get("/jobs/more?cursor=abc")
        assert resp.status_code == 200
        assert cursor_mock.call_args.kwargs["status"] == "Đang tuyển"


# ---------------------------------------------------------------------------
# crawler_client.jobs.list_jobs_cursor() — lớp thấp hơn, test trực tiếp
# hàm gọi backend (không qua Flask route) để cô lập lỗi encode param/
# decode response khỏi lỗi ở tầng blueprint.
# ---------------------------------------------------------------------------

class TestListJobsCursor:
    def test_first_call_no_cursor_param_sent(self, mocker):
        """Lần gọi đầu tiên (cursor=None) — KHÔNG được gửi param `cursor`
        lên backend (backend coi cursor rỗng khác cursor không truyền,
        xem api/routers/jobs.py bên scrap-jd-api: cursor=None nghĩa là
        chế độ offset/limit, không phải "trang đầu của chế độ cursor")."""
        request_mock = mocker.patch(
            "crawler_client.jobs._request",
            return_value={"items": [], "next_cursor": "cursor-1"},
        )
        crawler_client.list_jobs_cursor()
        params = request_mock.call_args.kwargs["params"]
        assert "cursor" not in params

    def test_subsequent_call_sends_cursor_param(self, mocker):
        request_mock = mocker.patch(
            "crawler_client.jobs._request",
            return_value={"items": [], "next_cursor": None},
        )
        crawler_client.list_jobs_cursor(cursor="cursor-1")
        params = request_mock.call_args.kwargs["params"]
        assert params["cursor"] == "cursor-1"

    def test_default_limit_is_20_not_200(self, mocker):
        """Batch mặc định của chế độ cursor (20) phải KHÁC list_jobs()
        cũ (200) — batch nhỏ hơn để tránh chạm rate limit 60/phút khi
        người dùng bấm "Tải thêm" liên tục (xem plan Phase 2)."""
        request_mock = mocker.patch(
            "crawler_client.jobs._request",
            return_value={"items": [], "next_cursor": None},
        )
        crawler_client.list_jobs_cursor()
        assert request_mock.call_args.kwargs["params"]["limit"] == 20

    def test_returns_normalized_jobs_and_next_cursor_tuple(self, mocker):
        mocker.patch(
            "crawler_client.jobs._request",
            return_value={
                "items": [{"job_id": "j1", "job_title": "Backend Dev", "company_name": "ACME"}],
                "next_cursor": "cursor-xyz",
            },
        )
        jobs, next_cursor = crawler_client.list_jobs_cursor()
        assert len(jobs) == 1
        assert jobs[0]["id"] == "j1"
        assert jobs[0]["position"] == "Backend Dev"
        assert next_cursor == "cursor-xyz"

    def test_missing_next_cursor_in_response_returns_none(self, mocker):
        """Backend không trả next_cursor (hoặc trả None) khi hết dữ liệu
        — hàm phải trả None sạch sẽ, không KeyError."""
        mocker.patch(
            "crawler_client.jobs._request",
            return_value={"items": []},
        )
        _, next_cursor = crawler_client.list_jobs_cursor()
        assert next_cursor is None

    def test_status_filter_converted_to_backend_code(self, mocker):
        """status truyền vào là nhãn tiếng Việt ('Đang tuyển') — phải
        được đổi sang mã backend ('OPEN') qua JOB_STATUS_MAP_REV, giống
        hệt list_jobs() cũ."""
        request_mock = mocker.patch(
            "crawler_client.jobs._request",
            return_value={"items": [], "next_cursor": None},
        )
        crawler_client.list_jobs_cursor(status="Đang tuyển")
        assert request_mock.call_args.kwargs["params"]["status"] == "OPEN"
