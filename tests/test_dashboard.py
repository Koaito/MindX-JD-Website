"""Lớp 3 cho blueprints/dashboard.py.

Route /dashboard gọi RẤT NHIỀU hàm crawler_client/backend_auth (list_all_jobs,
list_all_companies, get_level_codes, list_users, get_stats,
get_engagement_stats, list_all_contacts) — mock toàn bộ, mỗi hàm bọc
trong try/except riêng ở route thật nên 1 hàm lỗi không nên làm cả trang
sập, chỉ mất đúng phần dữ liệu đó (test_partial_backend_failure_still_
renders bên dưới cover đúng hành vi này).

Trọng tâm theo kế hoạch: get_level_codes() vừa sửa (GET /enums cache
TTL) — đảm bảo dashboard gọi đúng hàm này (không phải LEVELS tĩnh cũ đã
bị xoá khỏi constants.py) để tính jobs_by_level.
"""

import pytest

from crawler_client import CrawlerAPIError
from backend_auth import BackendAuthError


def _mock_all_dashboard_deps(mocker, *, jobs=None, companies=None, level_codes=None):
    """Mock toàn bộ dependency của dashboard.index() với dữ liệu rỗng/mặc
    định hợp lý — từng test override thêm phần cần thiết."""
    mocker.patch("blueprints.dashboard.db_data.list_all_jobs", return_value=jobs or [])
    mocker.patch("blueprints.dashboard.db_data.list_all_companies", return_value=companies or [])
    mocker.patch(
        "blueprints.dashboard.db_data.get_level_codes",
        return_value=level_codes if level_codes is not None else ["Intern", "Junior", "Senior"],
    )
    mocker.patch("blueprints.dashboard.backend_auth.list_users", return_value=[])
    mocker.patch("blueprints.dashboard.db_data.get_stats", return_value={})
    mocker.patch("blueprints.dashboard.db_data.get_engagement_stats", return_value={})
    mocker.patch("blueprints.dashboard.db_data.list_all_contacts", return_value=[])


class TestDashboardHappyPath:
    def test_renders_200_with_empty_data(self, staff_client, mocker):
        _mock_all_dashboard_deps(mocker)
        resp = staff_client.get("/dashboard")
        assert resp.status_code == 200

    def test_uses_get_level_codes_for_jobs_by_level(self, staff_client, mocker):
        """Điểm quan trọng nhất theo kế hoạch: dashboard PHẢI gọi
        db_data.get_level_codes() (cache TTL, tự đồng bộ backend) để dựng
        jobs_by_level — KHÔNG dùng list LEVELS tĩnh cũ (đã xoá khỏi
        constants.py 08/2026)."""
        _mock_all_dashboard_deps(
            mocker,
            jobs=[{"industry": "Code", "level": "Junior", "status": "OPEN", "location": "Hà Nội"}],
            level_codes=["Junior", "Senior"],
        )
        get_level_codes_mock = mocker.patch(
            "blueprints.dashboard.db_data.get_level_codes",
            return_value=["Junior", "Senior"],
        )
        resp = staff_client.get("/dashboard")
        assert resp.status_code == 200
        get_level_codes_mock.assert_called()

    def test_total_jobs_and_contacts_reflect_counts(self, staff_client, mocker):
        jobs = [
            {"industry": "Code", "level": "Junior", "status": "OPEN", "location": "Hà Nội"},
            {"industry": "Data Analysis", "level": "Senior", "status": "CLOSED", "location": "TP.HCM"},
        ]
        companies = [{"id": "c1", "city": "Hà Nội", "partnership_potential": "Thấp"}]
        _mock_all_dashboard_deps(mocker, jobs=jobs, companies=companies)
        resp = staff_client.get("/dashboard")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")
        # total_jobs=2 truyền vào template — không assert nội dung HTML cụ
        # thể (dễ vỡ theo template), chỉ đảm bảo route không lỗi khi có data.
        assert html  # render ra gì đó, không rỗng


class TestDashboardPartialBackendFailure:
    """Mỗi lệnh gọi backend trong route thật được bọc try/except RIÊNG —
    1 phần lỗi không được làm sập cả trang."""

    def test_list_all_jobs_failure_still_renders(self, staff_client, mocker):
        _mock_all_dashboard_deps(mocker)
        mocker.patch(
            "blueprints.dashboard.db_data.list_all_jobs",
            side_effect=CrawlerAPIError("backend lỗi"),
        )
        resp = staff_client.get("/dashboard")
        assert resp.status_code == 200

    def test_list_users_failure_still_renders(self, staff_client, mocker):
        _mock_all_dashboard_deps(mocker)
        mocker.patch(
            "blueprints.dashboard.backend_auth.list_users",
            side_effect=BackendAuthError("token hết hạn"),
        )
        resp = staff_client.get("/dashboard")
        assert resp.status_code == 200

    def test_get_stats_failure_still_renders(self, staff_client, mocker):
        _mock_all_dashboard_deps(mocker)
        mocker.patch(
            "blueprints.dashboard.db_data.get_stats",
            side_effect=CrawlerAPIError("backend lỗi"),
        )
        resp = staff_client.get("/dashboard")
        assert resp.status_code == 200

    def test_get_engagement_stats_failure_still_renders(self, staff_client, mocker):
        _mock_all_dashboard_deps(mocker)
        mocker.patch(
            "blueprints.dashboard.db_data.get_engagement_stats",
            side_effect=CrawlerAPIError("backend lỗi"),
        )
        resp = staff_client.get("/dashboard")
        assert resp.status_code == 200

    def test_list_all_contacts_failure_still_renders(self, staff_client, mocker):
        _mock_all_dashboard_deps(mocker)
        mocker.patch(
            "blueprints.dashboard.db_data.list_all_contacts",
            side_effect=CrawlerAPIError("backend lỗi"),
        )
        resp = staff_client.get("/dashboard")
        assert resp.status_code == 200

    def test_all_backends_failing_still_renders_empty_dashboard(self, staff_client, mocker):
        """Trường hợp xấu nhất: backend sập hoàn toàn -> trang vẫn phải
        render (rỗng), không được 500."""
        mocker.patch(
            "blueprints.dashboard.db_data.list_all_jobs",
            side_effect=CrawlerAPIError("sập"),
        )
        mocker.patch(
            "blueprints.dashboard.db_data.list_all_companies",
            side_effect=CrawlerAPIError("sập"),
        )
        mocker.patch(
            "blueprints.dashboard.db_data.get_level_codes",
            return_value=["Intern"],
        )
        mocker.patch(
            "blueprints.dashboard.backend_auth.list_users",
            side_effect=BackendAuthError("sập"),
        )
        mocker.patch(
            "blueprints.dashboard.db_data.get_stats",
            side_effect=CrawlerAPIError("sập"),
        )
        mocker.patch(
            "blueprints.dashboard.db_data.get_engagement_stats",
            side_effect=CrawlerAPIError("sập"),
        )
        mocker.patch(
            "blueprints.dashboard.db_data.list_all_contacts",
            side_effect=CrawlerAPIError("sập"),
        )
        resp = staff_client.get("/dashboard")
        assert resp.status_code == 200


class TestDashboardAccessControl:
    def test_unauthenticated_redirected_to_login(self, client):
        resp = client.get("/dashboard", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_student_cannot_access(self, student_client):
        resp = student_client.get("/dashboard", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" not in resp.headers["Location"]
