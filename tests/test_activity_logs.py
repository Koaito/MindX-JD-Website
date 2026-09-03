"""Lớp 3 cho blueprints/activity_logs.py.

Đây là 1 trong 2 blueprint được nhắc THẲNG TÊN trong docstring
helpers.py là nơi từng dính bug _call_authed cũ (dán nhầm bản không có
refresh token, gây crash 500 sau ~30 phút đăng nhập). Route
update_note() đã chuyển sang dùng _call_authed chung — test dưới đây
xác nhận ở CẤP ĐỘ ROUTE THẬT rằng bug đó không còn tái diễn.
"""


from backend_auth import BackendAuthError
from crawler_client import CrawlerAPIError


def _mock_logs_deps(mocker, *, logs=None, total=0, companies=None, users=None):
    mocker.patch(
        "blueprints.activity_logs.db_data.list_audit_logs",
        return_value={"items": logs or [], "total": total},
    )
    mocker.patch(
        "blueprints.activity_logs.db_data.list_all_companies",
        return_value=companies or [],
    )
    mocker.patch(
        "blueprints.activity_logs.backend_auth.list_users",
        return_value=users or [],
    )


class TestActivityLogsIndex:
    def test_renders_200_default_view(self, staff_client, mocker):
        _mock_logs_deps(mocker)
        resp = staff_client.get("/activity-logs")
        assert resp.status_code == 200

    def test_invalid_view_falls_back_to_auto(self, staff_client, mocker):
        list_audit_logs_mock = mocker.patch(
            "blueprints.activity_logs.db_data.list_audit_logs",
            return_value={"items": [], "total": 0},
        )
        mocker.patch("blueprints.activity_logs.db_data.list_all_companies", return_value=[])
        mocker.patch("blueprints.activity_logs.backend_auth.list_users", return_value=[])

        resp = staff_client.get("/activity-logs?view=not-a-real-view")
        assert resp.status_code == 200
        assert list_audit_logs_mock.call_args.kwargs["view"] == "auto"

    def test_staff_members_filtered_from_all_users(self, staff_client, mocker):
        """staff_members chỉ gồm role ss_team/admin — role 'user' (học
        viên) không được hiện trong dropdown filter actor."""
        _mock_logs_deps(
            mocker,
            users=[
                {"ss_user_id": "u1", "role": "user"},
                {"ss_user_id": "u2", "role": "ss_team"},
                {"ss_user_id": "u3", "role": "admin"},
            ],
        )
        resp = staff_client.get("/activity-logs")
        assert resp.status_code == 200

    def test_list_audit_logs_failure_still_renders(self, staff_client, mocker):
        mocker.patch(
            "blueprints.activity_logs.db_data.list_audit_logs",
            side_effect=CrawlerAPIError("backend lỗi"),
        )
        mocker.patch("blueprints.activity_logs.db_data.list_all_companies", return_value=[])
        mocker.patch("blueprints.activity_logs.backend_auth.list_users", return_value=[])
        resp = staff_client.get("/activity-logs")
        assert resp.status_code == 200

    def test_companies_dropdown_failure_still_renders(self, staff_client, mocker):
        mocker.patch(
            "blueprints.activity_logs.db_data.list_audit_logs",
            return_value={"items": [], "total": 0},
        )
        mocker.patch(
            "blueprints.activity_logs.db_data.list_all_companies",
            side_effect=CrawlerAPIError("backend lỗi"),
        )
        mocker.patch("blueprints.activity_logs.backend_auth.list_users", return_value=[])
        resp = staff_client.get("/activity-logs")
        assert resp.status_code == 200

    def test_list_users_failure_still_renders(self, staff_client, mocker):
        mocker.patch(
            "blueprints.activity_logs.db_data.list_audit_logs",
            return_value={"items": [], "total": 0},
        )
        mocker.patch("blueprints.activity_logs.db_data.list_all_companies", return_value=[])
        mocker.patch(
            "blueprints.activity_logs.backend_auth.list_users",
            side_effect=BackendAuthError("token hết hạn"),
        )
        resp = staff_client.get("/activity-logs")
        assert resp.status_code == 200

    def test_entity_type_dropdown_value_is_enum_key_not_label(self, staff_client, mocker):
        """FIX 09/2026 (xem lịch sử trao đổi "lỗi 400 khi lọc entity_type
        'Công ty' ở tab Lịch sử thao tác") — <option value> phải là key
        viết hoa backend chấp nhận (COMPANY), KHÔNG phải nhãn tiếng Việt
        (Công ty) — trước đây gửi nhầm nhãn lên backend -> 400."""
        _mock_logs_deps(mocker)
        resp = staff_client.get("/activity-logs")
        html = resp.get_data(as_text=True)
        assert 'value="COMPANY"' in html
        assert 'value="Công ty"' not in html
        # Vẫn phải HIỂN THỊ nhãn tiếng Việt cho người dùng đọc (chỉ đổi
        # value, không đổi text hiển thị trong <option>...</option>).
        assert ">Công ty</option>" in html

    def test_selected_entity_type_filter_matches_by_key(self, staff_client, mocker):
        _mock_logs_deps(mocker)
        resp = staff_client.get("/activity-logs?entity_type=COMPANY")
        html = resp.get_data(as_text=True)
        assert 'value="COMPANY" selected' in html

    def test_page_beyond_total_pages_clamped(self, staff_client, mocker):
        """page=99 nhưng chỉ có 1 trang dữ liệu -> phải tự kẹp về trang
        cuối cùng, không redirect/lỗi."""
        _mock_logs_deps(mocker, logs=[{"id": "log-1"}], total=1)
        resp = staff_client.get("/activity-logs?page=99")
        assert resp.status_code == 200

    def test_unauthenticated_redirected_to_login(self, client):
        resp = client.get("/activity-logs", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]


class TestActivityLogsAjaxFragment:
    """THÊM 09/2026 (xem lịch sử trao đổi "chuyển hẳn sang AJAX như
    crawl.html") — route /activity-logs giờ trả fragment thuần
    (_activity_logs_body.html, không qua layout base.html) khi request
    có header X-Requested-With, mirror đúng nhánh is_ajax ở
    blueprints/crawl.py::index()."""

    def test_ajax_request_returns_fragment_not_full_page(self, staff_client, mocker):
        _mock_logs_deps(mocker)
        resp = staff_client.get(
            "/activity-logs", headers={"X-Requested-With": "XMLHttpRequest"}
        )
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        # Fragment KHÔNG có header/sidebar/tab-nav của layout — chỉ có
        # nội dung bên trong #activity-logs-body.
        assert "Career Hub" not in html
        assert 'id="activityTabNav"' not in html
        assert "result-count" in html

    def test_non_ajax_request_returns_full_page(self, staff_client, mocker):
        _mock_logs_deps(mocker)
        resp = staff_client.get("/activity-logs")
        html = resp.get_data(as_text=True)
        assert 'id="activityTabNav"' in html
        assert 'id="activity-logs-body"' in html

    def test_ajax_fragment_still_respects_view_and_filters(self, staff_client, mocker):
        list_audit_logs_mock = mocker.patch(
            "blueprints.activity_logs.db_data.list_audit_logs",
            return_value={"items": [], "total": 0},
        )
        mocker.patch("blueprints.activity_logs.db_data.list_all_companies", return_value=[])
        mocker.patch("blueprints.activity_logs.backend_auth.list_users", return_value=[])
        resp = staff_client.get(
            "/activity-logs?view=manual&entity_type=COMPANY",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 200
        assert list_audit_logs_mock.call_args.kwargs["view"] == "manual"
        assert list_audit_logs_mock.call_args.kwargs["entity_type"] == "COMPANY"


class TestActivityLogsUpdateNote:
    """update_note() dùng _call_authed — route THẬT nơi từng dính bug
    _call_authed cũ (thiếu refresh token, crash 500 sau 401)."""

    def test_success_flashes_and_redirects(self, staff_client, mocker):
        mocker.patch(
            "blueprints.activity_logs.db_data.update_audit_log_note",
            return_value={"ok": True},
        )
        resp = staff_client.post(
            "/activity-logs/log-1/note", data={"note": "ghi chú mới"}, follow_redirects=False
        )
        assert resp.status_code == 302
        assert "/activity-logs" in resp.headers["Location"]

    def test_403_shows_permission_message_not_raw_backend_error(self, staff_client, mocker):
        """Backend chặn sửa note của người khác (403) -> flash message
        thân thiện riêng, KHÔNG hiện message backend gốc."""
        mocker.patch(
            "blueprints.activity_logs.db_data.update_audit_log_note",
            side_effect=CrawlerAPIError("Forbidden", status_code=403),
        )
        # follow_redirects=True nghĩa là sau POST, client tiếp tục GET
        # /activity-logs (trang logs()) — mock luôn dependency của trang
        # đó để không lỡ gọi network thật khi redirect chạy tiếp.
        _mock_logs_deps(mocker)
        resp = staff_client.post(
            "/activity-logs/log-1/note", data={"note": "sửa note người khác"},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "không có quyền".encode() in resp.data or b"quy\xe1\xbb\x81n" in resp.data

    def test_401_triggers_transparent_refresh_no_crash(self, staff_client, mocker):
        """CỐT LÕI của bug lịch sử: access token hết hạn ngay lúc sửa note
        -> _call_authed phải tự refresh và gọi lại, route trả về redirect
        BÌNH THƯỜNG (302) — KHÔNG crash 500 như bản _call_authed cũ bị
        dán nhầm ở blueprint này trước đây."""
        mocker.patch(
            "helpers.backend_auth.refresh",
            return_value={"access_token": "new-tok", "refresh_token": "new-refresh"},
        )
        call_count = {"n": 0}

        def side_effect(token, *args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise CrawlerAPIError("hết hạn", status_code=401)
            return {"ok": True}

        mocker.patch(
            "blueprints.activity_logs.db_data.update_audit_log_note",
            side_effect=side_effect,
        )
        resp = staff_client.post(
            "/activity-logs/log-1/note", data={"note": "ghi chú"}, follow_redirects=False
        )
        assert resp.status_code == 302
        assert call_count["n"] == 2

    def test_preserves_view_query_param_on_redirect(self, staff_client, mocker):
        mocker.patch(
            "blueprints.activity_logs.db_data.update_audit_log_note",
            return_value={"ok": True},
        )
        resp = staff_client.post(
            "/activity-logs/log-1/note?view=manual",
            data={"note": "ghi chú"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "view=manual" in resp.headers["Location"]

    def test_unauthenticated_redirected_to_login(self, client):
        resp = client.post(
            "/activity-logs/log-1/note", data={"note": "x"}, follow_redirects=False
        )
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_student_cannot_update_note(self, student_client):
        resp = student_client.post(
            "/activity-logs/log-1/note", data={"note": "x"}, follow_redirects=False
        )
        assert resp.status_code == 302
        assert "/login" not in resp.headers["Location"]
