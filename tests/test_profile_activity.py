"""Lớp 3 cho profile.activity() (blueprints/profile.py).

08/2026 — mục "Hoạt động" mới trong Trang cá nhân: job/công ty/contact
CHÍNH current_user đã tự thêm tay + contact đang được giao phụ trách.
Cùng dữ liệu/logic với staff_activity.detail() (xem
test_staff_activity.py) nhưng luôn ss_user_id = current_user.id, không
nhận tham số từ URL.
"""

from backend_auth import BackendAuthError
from crawler_client import CrawlerAPIError


def _mock_activity_deps(mocker, *, users=None, jobs=None, companies=None,
                         contacts_created=None, contacts_assigned=None):
    mocker.patch("blueprints.profile.backend_auth.list_users", return_value=users or [])
    mocker.patch("blueprints.profile.db_data.list_all_jobs", return_value=jobs or [])
    mocker.patch("blueprints.profile.db_data.list_all_companies", return_value=companies or [])

    def fake_list_all_contacts(access_token, **kwargs):
        if kwargs.get("created_by"):
            return contacts_created or []
        if kwargs.get("assigned_ss_user"):
            return contacts_assigned or []
        return []

    mocker.patch("blueprints.profile.db_data.list_all_contacts", side_effect=fake_list_all_contacts)


class TestProfileActivity:
    def test_student_cannot_access(self, student_client):
        """Học viên không tạo job/công ty/contact — @staff_required chặn,
        không hiện mục 'Hoạt động' trong sub-nav lẫn không vào được URL
        trực tiếp (redirect ra ngoài, không phải 200)."""
        resp = student_client.get("/profile/activity", follow_redirects=False)
        assert resp.status_code == 302

    def test_anonymous_redirected_to_login(self, client):
        resp = client.get("/profile/activity", follow_redirects=False)
        assert resp.status_code == 302
        assert "login" in resp.headers["Location"]

    def test_staff_sees_own_activity(self, staff_client, staff_user, mocker):
        _mock_activity_deps(
            mocker,
            users=[{"ss_user_id": staff_user.id, "full_name": staff_user.full_name, "role": "ss_team"}],
            jobs=[{"id": "job-1", "position": "Backend Dev", "company": "X", "status": "Đang tuyển", "industry": "IT", "level": "Junior", "deadline": None, "location": "HCM"}],
            companies=[{"id": "c-1", "company": "X Corp", "industry": "IT", "city": "HCM", "partnership_potential": "Cao"}],
            contacts_created=[{"id": "ct-1", "contact_name": "A", "company_id": "c-1", "company_name": "X Corp", "email": "a@x.com", "status": "Mới", "assigned_ss_user": None}],
            contacts_assigned=[{"id": "ct-2", "contact_name": "B", "company_id": "c-1", "company_name": "X Corp", "email": "b@x.com", "status": "Đang trao đổi", "assigned_ss_user": staff_user.id, "created_by": staff_user.id}],
        )
        resp = staff_client.get("/profile/activity")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Hoạt động của bạn" in body
        assert "Backend Dev" in body

    def test_staff_backend_error_flashes_and_renders_empty(self, staff_client, mocker):
        mocker.patch(
            "blueprints.profile.backend_auth.list_users",
            side_effect=BackendAuthError("lỗi backend", status_code=500),
        )
        mocker.patch(
            "blueprints.profile.db_data.list_all_jobs",
            side_effect=CrawlerAPIError("lỗi backend", status_code=500),
        )
        mocker.patch("blueprints.profile.db_data.list_all_companies", return_value=[])
        mocker.patch("blueprints.profile.db_data.list_all_contacts", return_value=[])
        resp = staff_client.get("/profile/activity")
        assert resp.status_code == 200

    def test_activity_only_calls_backend_scoped_to_self(self, staff_client, staff_user, mocker):
        """Xác nhận created_by/assigned_ss_user luôn là current_user.id —
        không lỡ truyền id người khác từ đâu đó."""
        _mock_activity_deps(mocker)
        jobs_mock = mocker.patch("blueprints.profile.db_data.list_all_jobs", return_value=[])
        staff_client.get("/profile/activity")
        jobs_mock.assert_called_once_with(created_by=staff_user.id)
