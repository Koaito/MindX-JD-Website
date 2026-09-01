"""Test cho blueprints/add_hub.py — trang gộp "Thêm mới" (/them-moi, 3
tab Job/Công ty/Người liên hệ, 08/2026, xem lịch sử trao đổi "phương
án A+").

Cũng bổ sung test cho companies.add()/contacts.add_any() — 2 route
này TRƯỚC ĐÂY CHƯA CÓ TEST NÀO trong repo (chỉ jobs.add() có, xem
test_jobs.py::TestJobsAdd) dù cùng thuộc nhóm 3 route bị đổi ở đợt
này."""
from crawler_client import CrawlerAPIError


def _mock_all_add_hub_deps(mocker):
    mocker.patch("blueprints.add_hub.db_data.list_all_companies", return_value=[
        {"id": "c-1", "company": "ACME"},
    ])
    mocker.patch("blueprints.add_hub.db_data.get_level_codes", return_value=["Intern", "Fresher"])


class TestAddHubIndex:
    def test_renders_200_with_all_3_tabs_present(self, staff_client, mocker):
        _mock_all_add_hub_deps(mocker)
        resp = staff_client.get("/them-moi")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'data-tab="job"' in html
        assert 'data-tab="company"' in html
        assert 'data-tab="contact"' in html

    def test_query_param_tab_accepted_for_initial_active_tab(self, staff_client, mocker):
        _mock_all_add_hub_deps(mocker)
        resp = staff_client.get("/them-moi?tab=contact")
        assert resp.status_code == 200

    def test_invalid_tab_falls_back_to_job(self, staff_client, mocker):
        _mock_all_add_hub_deps(mocker)
        resp = staff_client.get("/them-moi?tab=khong-ton-tai")
        assert resp.status_code == 200

    def test_unauthenticated_redirected_to_login(self, client):
        resp = client.get("/them-moi", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_student_cannot_access(self, student_client):
        resp = student_client.get("/them-moi", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" not in resp.headers["Location"]

    def test_company_list_fetched_once_shared_by_job_and_contact_tab(self, staff_client, mocker):
        """Bài học data_management.py — company list dùng chung cho tab
        job + tab contact, KHÔNG được gọi lại 2 lần cho 1 request."""
        mock_list = mocker.patch("blueprints.add_hub.db_data.list_all_companies", return_value=[])
        mocker.patch("blueprints.add_hub.db_data.get_level_codes", return_value=[])
        staff_client.get("/them-moi")
        assert mock_list.call_count == 1


class TestCompaniesAdd:
    """companies.add() — chưa từng có test nào trước 08/2026."""

    def test_get_redirects_to_add_hub(self, staff_client):
        resp = staff_client.get("/companies/add", follow_redirects=False)
        assert resp.status_code == 302
        assert "/them-moi" in resp.headers["Location"]
        assert "tab=company" in resp.headers["Location"]

    def test_post_success_redirects_to_detail(self, staff_client, mocker):
        mocker.patch(
            "blueprints.companies.db_data.create_company",
            return_value={"id": "co-1", "company": "Cong Ty Moi"},
        )
        resp = staff_client.post(
            "/companies/add",
            data={"company": "Cong Ty Moi"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/companies/co-1" in resp.headers["Location"]

    def test_post_error_rerenders_add_hub_shell_with_data_kept(self, staff_client, mocker):
        mocker.patch(
            "blueprints.companies.db_data.create_company",
            side_effect=CrawlerAPIError("Tên công ty đã tồn tại."),
        )
        mocker.patch("blueprints.add_hub.db_data.list_all_companies", return_value=[])
        mocker.patch("blueprints.add_hub.db_data.get_level_codes", return_value=[])
        resp = staff_client.post("/companies/add", data={"company": "Trung"})
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'data-tab="company"' in html
        assert 'value="Trung"' in html  # dữ liệu đã nhập không bị mất

    def test_unauthenticated_redirected_to_login(self, client):
        resp = client.get("/companies/add", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]


class TestContactsAddAny:
    """contacts.add_any() — chưa từng có test nào trước 08/2026."""

    def test_get_redirects_to_add_hub(self, staff_client):
        resp = staff_client.get("/contacts/add", follow_redirects=False)
        assert resp.status_code == 302
        assert "/them-moi" in resp.headers["Location"]
        assert "tab=contact" in resp.headers["Location"]

    def test_post_missing_company_id_rerenders_with_error(self, staff_client, mocker):
        mocker.patch("blueprints.add_hub.db_data.list_all_companies", return_value=[])
        mocker.patch("blueprints.add_hub.db_data.get_level_codes", return_value=[])
        resp = staff_client.post("/contacts/add", data={"contact_name": "A"})
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'data-tab="contact"' in html

    def test_post_success_redirects_to_contacts_index(self, staff_client, mocker):
        mocker.patch("blueprints.contacts.db_data.create_contact", return_value={"id": "ct-1"})
        resp = staff_client.post(
            "/contacts/add",
            data={"company_id": "c-1", "contact_name": "Nguyen Van A"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/contacts")

    def test_post_backend_error_rerenders_add_hub_shell(self, staff_client, mocker):
        mocker.patch(
            "blueprints.contacts.db_data.create_contact",
            side_effect=CrawlerAPIError("Lỗi backend."),
        )
        mocker.patch("blueprints.add_hub.db_data.list_all_companies", return_value=[])
        mocker.patch("blueprints.add_hub.db_data.get_level_codes", return_value=[])
        resp = staff_client.post(
            "/contacts/add",
            data={"company_id": "c-1", "contact_name": "Nguyen Van A"},
        )
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'data-tab="contact"' in html

    def test_unauthenticated_redirected_to_login(self, client):
        resp = client.get("/contacts/add", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]
