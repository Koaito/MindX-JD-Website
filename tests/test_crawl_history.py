"""Test tab 'history' (mục sidebar thứ 4 "Lịch sử vận hành", thêm
08/2026) — blueprints/crawl.py::index() + blueprints/crawl_history.py.

Trọng tâm test: cơ chế REFRESH-ONCE khi 1 request cần gọi backend
NHIỀU lần (bảng lịch sử crawl, list_users, bảng lịch sử bảo trì, poll
đang chạy crawl theo từng nguồn, poll đang chạy bảo trì). Đây là bug
đã sửa: backend_auth.refresh() XOAY VÒNG refresh_token, nên nếu mỗi
lệnh tự refresh riêng (dùng refresh_token cũ đọc từ session lúc đầu),
lệnh thứ 2 trở đi sẽ dùng refresh_token ĐÃ BỊ XOAY (vô hiệu) → backend
coi là reuse → thu hồi session → bị kick, xem docstring
_history_tab_context() (blueprints/crawl_history.py) để biết đầy đủ.

PATCH PATH: mock thẳng vào blueprints.crawl_history.db_data/
backend_auth (nơi _history_tab_context() thật sự đang chạy, từ
08/2026 tách file — xem docstring đầu blueprints/crawl_history.py).
Riêng _source_active_state vẫn patch tại blueprints.crawl — đó là nơi
hàm ĐƯỢC ĐỊNH NGHĨA thật, crawl_history.py chỉ import trễ (bên trong
hàm) một tham chiếu tới nó, không có bản sao riêng."""

import pytest

from crawler_client import CrawlerAPIError
from backend_auth import BackendAuthError


def _make_backend_user(**overrides):
    from tests.conftest import _make_backend_user as make
    return make(**overrides)


@pytest.fixture()
def admin_client(flask_app, mocker):
    """Test client đã login role admin — cần cho @admin_required trên
    /crawl (khác staff_client trong conftest.py, mặc định ss_team)."""
    from tests.conftest import _login_client

    admin_user = _make_backend_user(ss_user_id="admin-001", email="admin@example.com", role="admin")
    mocker.patch("app.backend_auth.get_me", return_value={
        "ss_user_id": admin_user.id, "email": admin_user.email,
        "full_name": admin_user.full_name, "role": admin_user.role,
        "must_change_password": admin_user.must_change_password,
        "is_active": True,
    })
    return _login_client(flask_app, admin_user)


def _empty_maintenance_runs(*args, **kwargs):
    return {"items": [], "total": 0}


def _empty_crawl_runs(*args, **kwargs):
    return {"items": [], "total": 0}


@pytest.fixture(autouse=True)
def _default_mocks(mocker):
    """Mock tối thiểu để mọi test trong file này render được trang mà
    không thật sự gọi mạng — mỗi test override lại field cần thiết."""
    mocker.patch("blueprints.crawl_history.db_data.get_sources", return_value={
        "topcv": {"it": "CNTT"}, "vietnamworks": {"it": "CNTT"}, "careerviet": {"it": "CNTT"},
    })
    mocker.patch("blueprints.crawl_history.db_data.list_crawl_runs", side_effect=_empty_crawl_runs)
    mocker.patch("blueprints.crawl_history.backend_auth.list_users", return_value=[])
    mocker.patch("blueprints.crawl_history.db_data.list_maintenance_runs", side_effect=_empty_maintenance_runs)
    mocker.patch("blueprints.crawl._source_active_state", return_value=("topcv", None, None, None))


class TestOtherTabsStillRenderAfterHistorySplit:
    """Bug thật đã bắt được lúc làm tab 'history': khi tách Khu C ra
    khỏi tab 'crawl'/'maintenance', quên trả lại status_labels cho tab
    'maintenance' (JS Khu B vẫn cần biến này để build STATUS_LABELS) —
    khiến CẢ TRANG CRASH 500 (Undefined không serialize được qua
    |tojson), không chỉ mất style. Test này ở ĐÂY (cùng file với tab
    history) để nhắc: mỗi lần đổi context 1 tab, PHẢI quét lại toàn bộ
    biến Jinja mà 3 tab còn lại dùng, không chỉ tab đang sửa."""

    def test_crawl_tab_still_renders_200(self, admin_client):
        resp = admin_client.get("/crawl?tab=crawl")
        assert resp.status_code == 200

    def test_maintenance_tab_still_renders_200(self, admin_client, mocker):
        mocker.patch("blueprints.crawl_maintenance._active_maintenance_runs", return_value={})
        mocker.patch("blueprints.crawl_maintenance._call_authed",
                      return_value={j["job_type"]: None for j in
                                    __import__("crawler_client").maintenance.MAINTENANCE_JOBS})
        resp = admin_client.get("/crawl?tab=maintenance")
        assert resp.status_code == 200

    def test_status_tab_still_renders_200(self, admin_client):
        resp = admin_client.get("/crawl?tab=status")
        assert resp.status_code == 200


class TestHistoryTabRenders:
    def test_renders_200_empty_state(self, admin_client):
        resp = admin_client.get("/crawl?tab=history")
        assert resp.status_code == 200
        assert "Lịch sử crawl".encode() in resp.data
        assert "Lịch sử bảo trì".encode() in resp.data

    def test_sidebar_still_highlights_van_hanh_du_lieu(self, admin_client):
        """Điểm 3 đã rà: tab 'history' PHẢI cùng endpoint crawl.index —
        không tách Blueprint riêng — để base.html highlight đúng mục
        sidebar "Vận hành dữ liệu" (request.endpoint.startswith('crawl.'))."""
        resp = admin_client.get("/crawl?tab=history")
        assert resp.status_code == 200
        assert b'class="active"' in resp.data or b"active" in resp.data

    def test_tab_nav_has_4th_item(self, admin_client):
        resp = admin_client.get("/crawl?tab=history")
        assert "Lịch sử vận hành".encode() in resp.data

    def test_lede_text_differs_for_history_tab(self, admin_client):
        """ĐÃ ĐỔI (08/2026, xem lịch sử trao đổi "gộp lại cả 4 tab client-
        side sau sơ suất revert"): crawl.html giờ render CẢ 4 TAB cùng
        lúc trong 1 response nên không còn 1 lede-text RIÊNG theo từng
        tab (không thể hiện 4 mô tả khác nhau cùng lúc một cách hợp lý)
        — page-head giờ dùng 1 mô tả CHUNG cho cả 4 tab. Test đổi sang
        xác nhận đúng việc đó: cả 4 tab (kể cả history) cùng có mặt
        trong 1 response, thay vì so khớp lede-text theo tab."""
        resp = admin_client.get("/crawl?tab=history")
        html = resp.get_data(as_text=True)
        assert 'data-tab="crawl"' in html
        assert 'data-tab="status"' in html
        assert 'data-tab="maintenance"' in html
        assert 'data-tab="history"' in html


class TestHistoryTabPagination:
    def test_crawl_table_uses_crawl_page_param(self, admin_client, mocker):
        captured = {}

        def fake_list_crawl_runs(token, **kwargs):
            captured.update(kwargs)
            return {"items": [], "total": 20}

        mocker.patch("blueprints.crawl_history.db_data.list_crawl_runs", side_effect=fake_list_crawl_runs)
        resp = admin_client.get("/crawl?tab=history&crawl_page=2")
        assert resp.status_code == 200
        assert captured["offset"] == 6  # (page 2 - 1) * per_page 6
        assert captured["limit"] == 6

    def test_maintenance_table_uses_maint_page_param(self, admin_client, mocker):
        calls = []

        def fake_list_maint_runs(token, **kwargs):
            calls.append(kwargs)
            return {"items": [], "total": 20}

        mocker.patch("blueprints.crawl_history.db_data.list_maintenance_runs", side_effect=fake_list_maint_runs)
        resp = admin_client.get("/crawl?tab=history&maint_page=3")
        assert resp.status_code == 200
        # db_data.list_maintenance_runs() bị gọi 2 LẦN trong 1 request:
        # (1) bảng lịch sử bảo trì (limit=maint_per_page=6, có offset
        # theo maint_page) và (2) bên trong _active_maintenance_runs_raw()
        # (poll widget "đang chạy", limit=10 cố định, KHÔNG liên quan
        # phân trang — xem docstring _active_maintenance_runs_raw()).
        # Lọc đúng lời gọi (1) để kiểm tra offset/limit phân trang.
        history_call = next(c for c in calls if "offset" in c)
        assert history_call["offset"] == 12  # (page 3 - 1) * per_page 6
        assert history_call["limit"] == 6

    def test_per_page_is_6_not_30(self, admin_client, mocker):
        """Yêu cầu cụ thể: "mỗi trang 6 cái log" — khác per_page=30 lúc
        2 bảng còn nằm trong tab crawl/maintenance."""
        captured_crawl = {}
        maint_calls = []
        mocker.patch(
            "blueprints.crawl_history.db_data.list_crawl_runs",
            side_effect=lambda token, **kw: (captured_crawl.update(kw), {"items": [], "total": 0})[1],
        )
        mocker.patch(
            "blueprints.crawl_history.db_data.list_maintenance_runs",
            side_effect=lambda token, **kw: (maint_calls.append(kw), {"items": [], "total": 0})[1],
        )
        admin_client.get("/crawl?tab=history")
        assert captured_crawl["limit"] == 6
        # Lọc đúng lời gọi CHO BẢNG LỊCH SỬ (có "offset") — lời gọi còn
        # lại (limit=10, không có "offset") là poll widget "đang chạy",
        # không thuộc phạm vi yêu cầu phân trang. Xem
        # test_maintenance_table_uses_maint_page_param phía trên.
        history_call = next(c for c in maint_calls if "offset" in c)
        assert history_call["limit"] == 6

    def test_crawl_pagination_link_preserves_maint_page(self, admin_client, mocker):
        """Bấm phân trang bảng crawl KHÔNG được làm mất trang đang xem
        của bảng bảo trì (2 param độc lập, xem docstring
        _history_tab_context())."""
        mocker.patch(
            "blueprints.crawl_history.db_data.list_crawl_runs",
            # total > per_page(6) VÀ có items thật — backend thật không
            # bao giờ trả total=20 kèm items=[] trừ khi trang vượt quá
            # tổng số; ở đây mô phỏng trang 1 có 6/20 kết quả để bảng
            # (và do đó khối phân trang lồng bên trong {% if crawl_runs %})
            # thực sự render.
            return_value={"items": [{"run_id": f"r{i}", "source": "topcv",
                                      "category": "it", "status": "done",
                                      "status_label": "Hoàn tất", "status_badge": "badge-success",
                                      "triggered_by_name": "Admin", "started_at": "2026-08-31T10:00:00",
                                      "stat_items": []} for i in range(6)],
                           "total": 20},
        )
        # maint_page=3 phải là trang HỢP LỆ thật (total đủ lớn) — nếu
        # không, code tự clamp về trang 1 (đúng hành vi, xem
        # test_clear_filter_link_keeps_other_table_page) và assertion
        # bên dưới sẽ sai vì lý do khác với điều test này nhắm tới.
        mocker.patch(
            "blueprints.crawl_history.db_data.list_maintenance_runs",
            return_value={"items": [{"run_id": "m1", "job_type": "backfill_company_profiles",
                                      "job_label": "Vá hồ sơ công ty", "status": "done",
                                      "status_label": "Hoàn tất", "status_badge": "badge-success",
                                      "triggered_by_name": "Admin", "started_at": "2026-08-31T10:00:00",
                                      "stat_items": []} for _ in range(6)],
                           "total": 20},
        )
        resp = admin_client.get("/crawl?tab=history&maint_page=3")
        assert resp.status_code == 200
        assert b"maint_page=3" in resp.data


class TestHistoryTabRefreshOnce:
    """Trọng tâm: rà điểm 2 — 1 request tới tab 'history' phải chỉ
    refresh token ĐÚNG 1 LẦN dù cần gọi backend nhiều lần, không để mỗi
    lệnh tự refresh riêng (mỗi refresh xoay vòng refresh_token, refresh
    nhiều lần trong 1 request = dùng refresh_token đã bị vô hiệu =
    reuse detected = bị kick)."""

    def test_401_on_first_call_triggers_single_refresh_then_succeeds(self, admin_client, mocker):
        mocker.patch(
            "blueprints.crawl_history.backend_auth.refresh",
            return_value={"access_token": "new-tok", "refresh_token": "new-refresh"},
        )
        refresh_call_count = {"n": 0}

        def fake_refresh(refresh_token):
            refresh_call_count["n"] += 1
            return {"access_token": "new-tok", "refresh_token": "new-refresh"}

        mocker.patch("blueprints.crawl_history.backend_auth.refresh", side_effect=fake_refresh)

        call_count = {"n": 0}

        def flaky_list_crawl_runs(token, **kwargs):
            call_count["n"] += 1
            if token == "fake-access-token":
                raise CrawlerAPIError("hết hạn", status_code=401)
            return {"items": [], "total": 0}

        mocker.patch("blueprints.crawl_history.db_data.list_crawl_runs", side_effect=flaky_list_crawl_runs)

        resp = admin_client.get("/crawl?tab=history")
        assert resp.status_code == 200
        # refresh() CHỈ được gọi đúng 1 lần cho toàn bộ wave (không phải
        # 1 lần / lệnh backend bên trong wave).
        assert refresh_call_count["n"] == 1

    def test_401_partway_through_wave_does_not_call_refresh_twice(self, admin_client, mocker):
        """Case CỐT LÕI của bug: 401 xảy ra ở lệnh THỨ 2 trong wave
        (không phải lệnh đầu) — vẫn phải chỉ refresh 1 lần, KHÔNG để
        lệnh đầu (đã thành công) và lệnh thứ 2 (401) mỗi cái tự refresh
        riêng nếu code viết sai (ví dụ lỡ bọc try/except quanh từng
        lệnh thay vì quanh cả wave)."""
        refresh_call_count = {"n": 0}

        def fake_refresh(refresh_token):
            refresh_call_count["n"] += 1
            return {"access_token": "new-tok", "refresh_token": "new-refresh"}

        mocker.patch("blueprints.crawl_history.backend_auth.refresh", side_effect=fake_refresh)

        # list_crawl_runs (lệnh 1) LUÔN thành công. list_users (lệnh 2)
        # 401 ở lần gọi ĐẦU (token cũ), thành công ở lần gọi SAU (token mới).
        mocker.patch("blueprints.crawl_history.db_data.list_crawl_runs", return_value={"items": [], "total": 0})

        def flaky_list_users(token):
            if token == "fake-access-token":
                raise BackendAuthError("hết hạn", status_code=401)
            return [{"ss_user_id": "admin-001", "full_name": "Admin", "role": "admin"}]

        mocker.patch("blueprints.crawl_history.backend_auth.list_users", side_effect=flaky_list_users)

        resp = admin_client.get("/crawl?tab=history")
        assert resp.status_code == 200
        assert refresh_call_count["n"] == 1

    def test_refresh_failure_flashes_error_not_crash(self, admin_client, mocker):
        mocker.patch("blueprints.crawl_history.db_data.list_crawl_runs",
                     side_effect=CrawlerAPIError("hết hạn", status_code=401))
        mocker.patch("blueprints.crawl_history.backend_auth.refresh",
                     side_effect=BackendAuthError("refresh token cũng hết hạn", status_code=401))
        resp = admin_client.get("/crawl?tab=history")
        # KHÔNG crash (500) — trang vẫn render, chỉ rỗng + flash lỗi.
        assert resp.status_code == 200


class TestHistoryTabActiveWidgets:
    """Rà lựa chọn đã chốt: tab 'history' hiện widget "Đang chạy" cho
    CẢ crawl lẫn bảo trì cùng lúc (khác 2 tab kia chỉ hiện job của tab
    đang xem) — widget TĨNH, không polling."""

    def test_shows_active_crawl_widget_when_running(self, admin_client, mocker):
        mocker.patch(
            "blueprints.crawl._source_active_state",
            return_value=("topcv", {
                "run_id": "run-1", "status": "running", "category": "it",
                "triggered_by_name": "Admin A", "started_at": "2026-08-31T10:00:00",
            }, None, None),
        )
        resp = admin_client.get("/crawl?tab=history")
        assert resp.status_code == 200
        assert "Crawl đang chạy".encode() in resp.data
        assert "Admin A".encode() in resp.data

    def test_shows_active_maintenance_widget_when_running(self, admin_client, mocker):
        mocker.patch(
            "blueprints.crawl_maintenance._active_maintenance_runs_raw",
            return_value={
                "backfill_company_profiles": {
                    "run_id": "run-2", "status": "running",
                    "triggered_by_name": "Admin B", "started_at": "2026-08-31T10:00:00",
                }
            },
        )
        resp = admin_client.get("/crawl?tab=history")
        assert resp.status_code == 200
        assert "Bảo trì đang chạy".encode() in resp.data
        assert "Admin B".encode() in resp.data

    def test_no_widget_shown_when_nothing_running(self, admin_client):
        resp = admin_client.get("/crawl?tab=history")
        assert resp.status_code == 200
        assert "Crawl đang chạy".encode() not in resp.data
        assert "Bảo trì đang chạy".encode() not in resp.data


class TestHistoryTabFilters:
    def test_crawl_filter_by_source(self, admin_client, mocker):
        captured = {}
        mocker.patch(
            "blueprints.crawl_history.db_data.list_crawl_runs",
            side_effect=lambda token, **kw: (captured.update(kw), {"items": [], "total": 0})[1],
        )
        resp = admin_client.get("/crawl?tab=history&source=topcv")
        assert resp.status_code == 200
        assert captured["source"] == "topcv"

    def test_maintenance_filter_by_job_type(self, admin_client, mocker):
        captured = {}
        mocker.patch(
            "blueprints.crawl_history.db_data.list_maintenance_runs",
            side_effect=lambda token, **kw: (captured.update(kw), {"items": [], "total": 0})[1],
        )
        resp = admin_client.get("/crawl?tab=history&m_job_type=backfill_company_profiles")
        assert resp.status_code == 200
        assert captured["job_type"] == "backfill_company_profiles"

    def test_clear_filter_link_keeps_other_table_page(self, admin_client, mocker):
        mocker.patch(
            "blueprints.crawl_history.db_data.list_crawl_runs",
            return_value={"items": [], "total": 0},
        )
        # total đủ lớn để maint_page=2 là trang HỢP LỆ thật (total=0 mà
        # maint_page=2 là trang không tồn tại — code tự clamp về trang
        # 1, đúng hành vi mong muốn nhưng khiến test này không còn kiểm
        # tra đúng thứ nó nhắm tới; total=20 tránh nhầm 2 việc).
        mocker.patch(
            "blueprints.crawl_history.db_data.list_maintenance_runs",
            return_value={"items": [{"run_id": "m1", "job_type": "backfill_company_profiles",
                                      "job_label": "Vá hồ sơ công ty", "status": "done",
                                      "status_label": "Hoàn tất", "status_badge": "badge-success",
                                      "triggered_by_name": "Admin", "started_at": "2026-08-31T10:00:00",
                                      "stat_items": []} for _ in range(6)],
                           "total": 20},
        )
        resp = admin_client.get("/crawl?tab=history&source=topcv&maint_page=2")
        assert resp.status_code == 200
        # "Xóa lọc" của bảng crawl phải giữ maint_page=2
        assert b"maint_page=2" in resp.data
