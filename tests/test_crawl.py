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

    def test_staff_can_view_crawl_page(self, staff_client, mocker):
        """SỬA 09/2026 (khôi phục ss_team xem được, xem docstring đầu
        blueprints/crawl.py) — index() giờ @staff_required, không còn
        @admin_required như bản trước. ss_team xem được cả 3 tab, chỉ
        không thấy nút bấm chạy (kiểm tra riêng ở test_crawl_maintenance.py
        + template test bên dưới)."""
        _mock_all_crawl_page_deps(mocker)
        resp = staff_client.get("/crawl")
        assert resp.status_code == 200

    def test_staff_does_not_see_trigger_form(self, staff_client, mocker):
        """Template phải tự ẩn form kích hoạt cho non-admin — nếu không
        ẩn, ss_team thấy nút bấm nhưng bấm vào bị chặn ở route (xem 2
        test bên dưới), trải nghiệm còn tệ hơn không thấy mục này."""
        _mock_all_crawl_page_deps(mocker)
        resp = staff_client.get("/crawl")
        html = resp.get_data(as_text=True)
        assert 'action="/crawl/batch/trigger"' not in html

    def test_staff_blocked_from_trigger_batch(self, staff_client, mocker):
        """Route BẤM CHẠY vẫn @admin_required dù index() đã mở cho
        ss_team — ss_team xem được nhưng không chạy được job."""
        _mock_all_crawl_page_deps(mocker)
        resp = staff_client.post("/crawl/batch/trigger", data={"source": "topcv"})
        assert resp.status_code in (302, 403)

    def test_staff_blocked_from_maintenance_trigger(self, staff_client, mocker):
        _mock_all_crawl_page_deps(mocker)
        resp = staff_client.post("/crawl/maintenance/check_expired/trigger", data={})
        assert resp.status_code in (302, 403, 404)


class TestCrossTabLiveWidget:
    """KHÔI PHỤC 09/2026 (xem lịch sử trao đổi "đồng bộ widget đang
    chạy") — mỗi tab (crawl/maintenance/status) phải tự hiện thêm dữ
    liệu của LOẠI CÒN THIẾU, không chỉ đúng loại của chính nó. Smoke
    test, không kiểm tra hết mọi nhánh JS — chỉ xác nhận đúng dữ liệu
    chéo có mặt trong HTML trả về (data-kind/nhãn), không lẫn lộn 2
    loại, không Jinja/Python lỗi."""

    _RUNNING_CRAWL = {
        "run_id": "run-crawl-1", "source": "topcv", "status": "running",
        "category": "da", "triggered_by_name": "Admin One", "started_at": "2026-09-01T10:00:00",
    }
    _RUNNING_MAINT = {
        "run_id": "run-maint-1", "job_type": "check_expired", "status": "running",
        "triggered_by_name": "Admin One", "started_at": "2026-09-01T10:05:00",
    }

    def test_crawl_tab_shows_cross_maintenance_running(self, admin_client, mocker):
        _mock_all_crawl_page_deps(mocker)
        mocker.patch(
            "blueprints.crawl_maintenance.db_data.list_maintenance_runs",
            return_value={"items": [self._RUNNING_MAINT], "total": 1},
        )
        resp = admin_client.get("/crawl?tab=crawl")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'data-kind="maintenance"' in html
        assert "crawl-cross-running-zone" in html

    def test_maintenance_tab_shows_cross_crawl_running(self, admin_client, mocker):
        _mock_all_crawl_page_deps(mocker)
        mocker.patch(
            "blueprints.crawl.db_data.list_crawl_runs",
            return_value={"items": [self._RUNNING_CRAWL], "total": 1},
        )
        resp = admin_client.get("/crawl?tab=maintenance")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'data-kind="crawl"' in html
        assert "maint-cross-running-zone" in html

    def test_status_tab_shows_both_types_running(self, admin_client, mocker):
        _mock_all_crawl_page_deps(mocker)
        mocker.patch(
            "blueprints.crawl.db_data.list_crawl_runs",
            return_value={"items": [self._RUNNING_CRAWL], "total": 1},
        )
        mocker.patch(
            "blueprints.crawl_maintenance.db_data.list_maintenance_runs",
            return_value={"items": [self._RUNNING_MAINT], "total": 1},
        )
        resp = admin_client.get("/crawl?tab=status")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'data-kind="crawl"' in html
        assert 'data-kind="maintenance"' in html
        assert "status-live-widget" in html

    def test_status_tab_widget_absent_when_nothing_running(self, admin_client, mocker):
        _mock_all_crawl_page_deps(mocker)
        resp = admin_client.get("/crawl?tab=status")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "status-live-widget" not in html
