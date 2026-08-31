"""Test cho blueprints/crawl.py — trang "Vận hành dữ liệu".

Trước 08/2026 file này chưa có test riêng nào. Thêm cùng đợt gộp 3 tab
(crawl/status/maintenance) vào 1 response duy nhất — xem docstring
crawl.py::index() để biết lý do gộp và các đánh đổi.
"""
from crawler_client import CrawlerAPIError


def _mock_all_crawl_page_deps(mocker):
    # ---- tab crawl ----
    mocker.patch("blueprints.crawl.db_data.get_sources", return_value={"topcv": {"da": "Data Analyst"}})
    mocker.patch("blueprints.crawl.db_data.list_crawl_runs", return_value={"items": [], "total": 0})
    mocker.patch("blueprints.crawl.backend_auth.list_users", return_value=[
        {"role": "admin", "ss_user_id": "a1", "full_name": "Admin One"},
    ])
    mocker.patch("blueprints.crawl.db_data.CRAWL_STATUS_LABELS", {"queued": "Đang chờ"})
    mocker.patch("blueprints.crawl.db_data.CRAWL_STAT_LABELS", [])

    # ---- tab status ----
    mocker.patch("blueprints.crawl_status.db_data.get_company_data_health", return_value={
        "company_health_rows": [], "company_health_total": 0,
        "company_no_contact_missing": 0, "company_no_contact_total": 0,
    })
    mocker.patch("blueprints.crawl_status.db_data.get_job_data_health", return_value={
        "job_health_rows": [], "job_health_total": 0,
        "expired_open_jobs": [], "job_health_by_source": [], "duplicate_job_groups": [],
    })

    # ---- tab maintenance ----
    mocker.patch("blueprints.crawl_maintenance.db_data.list_maintenance_runs", return_value={"items": [], "total": 0})
    mocker.patch("blueprints.crawl_maintenance.db_data.get_maintenance_latest_log_runs", return_value={})
    mocker.patch("blueprints.crawl_maintenance.backend_auth.list_users", return_value=[])


class TestCrawlIndexMergedTabs:
    """/crawl giờ render cả 3 tab (crawl/status/maintenance) trong 1
    response — trước đây mỗi tab là 1 request riêng theo ?tab=."""

    def test_renders_200_with_all_3_tabs_present(self, admin_client, mocker):
        _mock_all_crawl_page_deps(mocker)
        resp = admin_client.get("/crawl")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'data-tab="crawl"' in html
        assert 'data-tab="status"' in html
        assert 'data-tab="maintenance"' in html

    def test_query_param_tab_still_accepted_for_initial_active_tab(self, admin_client, mocker):
        """?tab= giờ chỉ còn ý nghĩa "tab nào active lúc mở link" (JS đọc
        lúc init) — vẫn phải trả 200 với giá trị hợp lệ, không còn quyết
        định server render nhánh nào (đã bỏ early-return)."""
        _mock_all_crawl_page_deps(mocker)
        resp = admin_client.get("/crawl?tab=maintenance")
        assert resp.status_code == 200

    def test_invalid_tab_falls_back_to_crawl(self, admin_client, mocker):
        _mock_all_crawl_page_deps(mocker)
        resp = admin_client.get("/crawl?tab=khong-ton-tai")
        assert resp.status_code == 200

    def test_status_tab_backend_failure_does_not_break_page(self, admin_client, mocker):
        """1 tab lỗi backend không được làm sập cả trang — cùng nguyên
        tắc TestDashboardPartialBackendFailure ở test_dashboard.py."""
        _mock_all_crawl_page_deps(mocker)
        mocker.patch(
            "blueprints.crawl_status.db_data.get_job_data_health",
            side_effect=CrawlerAPIError("backend lỗi"),
        )
        resp = admin_client.get("/crawl")
        assert resp.status_code == 200

    def test_maintenance_tab_backend_failure_does_not_break_page(self, admin_client, mocker):
        _mock_all_crawl_page_deps(mocker)
        mocker.patch(
            "blueprints.crawl_maintenance.db_data.list_maintenance_runs",
            side_effect=CrawlerAPIError("backend lỗi"),
        )
        resp = admin_client.get("/crawl")
        assert resp.status_code == 200

    def test_staff_without_admin_role_gets_403_or_redirect(self, staff_client, mocker):
        """admin_required phải vẫn chặn staff thường — gộp tab không
        được vô tình nới quyền truy cập."""
        _mock_all_crawl_page_deps(mocker)
        resp = staff_client.get("/crawl")
        assert resp.status_code in (302, 403)
