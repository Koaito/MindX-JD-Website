"""Test cho blueprints/contacts.py::index() — THÊM 09/2026 (trước đây
chưa có file test riêng cho route này). Trọng tâm: hành vi AJAX fragment
vừa thêm (xem lịch sử trao đổi "chuyển hẳn sang AJAX như crawl.html/
activity_logs") — route giờ trả fragment thuần khi có header
X-Requested-With, trang đầy đủ khi load bình thường, mirror đúng
blueprints/activity_logs.py::logs()."""

import pytest


def _mock_contact_list_deps(mocker, contacts=None, companies=None, users=None):
    mocker.patch("blueprints.contacts.db_data.list_all_contacts", return_value=contacts or [])
    mocker.patch("blueprints.contacts.db_data.list_all_companies", return_value=companies or [])
    mocker.patch("blueprints.contacts.backend_auth.list_users", return_value=users or [])


def _mock_email_template_deps(mocker, templates=None):
    mocker.patch("blueprints.contacts.db_data.list_email_templates", return_value=templates or [])
    mocker.patch("blueprints.contacts.db_data.get_placeholder_help", return_value={})


class TestContactsIndexFullPage:
    def test_default_tab_renders_200(self, staff_client, mocker):
        _mock_contact_list_deps(mocker)
        resp = staff_client.get("/contacts")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'id="contactsTabNav"' in html
        assert 'id="contacts-body"' in html

    def test_quan_ly_tab_renders_200(self, staff_client, mocker):
        _mock_email_template_deps(mocker)
        resp = staff_client.get("/contacts?tab=quan-ly")
        assert resp.status_code == 200
        assert "Quản lý mẫu email" in resp.get_data(as_text=True)

    def test_invalid_tab_falls_back_to_danh_sach(self, staff_client, mocker):
        _mock_contact_list_deps(mocker)
        resp = staff_client.get("/contacts?tab=khong-ton-tai")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "＋ Thêm người liên hệ" in html  # nút này chỉ hiện ở tab danh-sach

    def test_unauthenticated_redirected_to_login(self, client):
        resp = client.get("/contacts", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]


class TestContactsAjaxFragment:
    def test_ajax_request_returns_fragment_not_full_page(self, staff_client, mocker):
        _mock_contact_list_deps(mocker)
        resp = staff_client.get("/contacts", headers={"X-Requested-With": "XMLHttpRequest"})
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Career Hub" not in html
        assert 'id="contactsTabNav"' not in html
        assert "result-count" in html

    def test_non_ajax_request_returns_full_page(self, staff_client, mocker):
        _mock_contact_list_deps(mocker)
        resp = staff_client.get("/contacts")
        html = resp.get_data(as_text=True)
        assert 'id="contactsTabNav"' in html

    def test_ajax_fragment_still_respects_filters(self, staff_client, mocker):
        list_contacts_mock = mocker.patch(
            "blueprints.contacts.db_data.list_all_contacts", return_value=[]
        )
        mocker.patch("blueprints.contacts.db_data.list_all_companies", return_value=[])
        mocker.patch("blueprints.contacts.backend_auth.list_users", return_value=[])
        resp = staff_client.get(
            "/contacts?q=an&company_id=c1",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 200
        assert list_contacts_mock.call_args.kwargs["search"] == "an"
        assert list_contacts_mock.call_args.kwargs["company_id"] == "c1"

    def test_ajax_quan_ly_returns_email_template_fragment(self, staff_client, mocker):
        _mock_email_template_deps(mocker, templates=[
            {"id": "t1", "title": "Mẫu 1", "display_order": 0, "body": "xin chào",
             "description": "", "recommended_for": []},
        ])
        resp = staff_client.get(
            "/contacts?tab=quan-ly", headers={"X-Requested-With": "XMLHttpRequest"}
        )
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Career Hub" not in html
        assert "Mẫu 1" in html


class TestContactsAjaxNavMarkerClass:
    """Xác nhận đúng những link nào được đánh dấu 'ajax-nav' (cùng
    trang, an toàn để chặn AJAX) và link 'Sửa' contact (route KHÁC hẳn,
    contacts.edit) KHÔNG bị đánh dấu nhầm — xem docstring script cuối
    contacts.html để biết vì sao 2 nhóm link này không thể dùng chung
    class '.btn-text'."""

    def test_clear_filter_link_has_ajax_nav_class(self, staff_client, mocker):
        _mock_contact_list_deps(mocker)
        resp = staff_client.get("/contacts?q=an")
        html = resp.get_data(as_text=True)
        assert 'class="btn btn-text ajax-nav"' in html
        assert "Xóa lọc" in html

    def test_edit_contact_link_does_not_have_ajax_nav_class(self, staff_client, mocker):
        _mock_contact_list_deps(mocker, contacts=[{
            "id": "ct1", "contact_name": "Nguyễn Văn An", "company_id": "co1",
            "company_name": "FPT Software", "title": None, "email": "an@fpt.com",
            "phone": None, "source": None, "last_contacted": None,
            "status_raw": "UNCONTACTED", "status": "Chưa liên hệ", "assigned_ss_user": None,
        }])
        resp = staff_client.get("/contacts")
        html = resp.get_data(as_text=True)
        assert '<a class="btn btn-text" href="/companies/co1/contacts/ct1/edit">Sửa</a>' in html

    def test_email_template_edit_and_cancel_links_have_ajax_nav_class(self, staff_client, mocker):
        _mock_email_template_deps(mocker, templates=[
            {"id": "t1", "title": "Mẫu 1", "display_order": 0, "body": "xin chào",
             "description": "", "recommended_for": []},
        ])
        resp = staff_client.get("/contacts?tab=quan-ly")
        html = resp.get_data(as_text=True)
        assert 'class="btn btn-text ajax-nav" href="/contacts?tab=quan-ly&amp;edit=t1#et-manager-form"' in html \
            or 'ajax-nav" href="/contacts?tab=quan-ly&edit=t1#et-manager-form"' in html
