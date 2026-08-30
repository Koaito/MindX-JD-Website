"""Lớp 3 cho blueprints/staff_activity.py.

08/2026: /staff-activity/<id> KHÔNG còn cho xem hoạt động CHÍNH MÌNH —
gõ thẳng URL /staff-activity/<id-của-chính-mình> giờ redirect sang
profile.activity (Trang cá nhân). Xem hoạt động người KHÁC vẫn hoạt
động bình thường qua route này.
"""

from backend_auth import BackendAuthError


class TestStaffActivityDetailSelfRedirect:
    def test_viewing_own_id_redirects_to_profile_activity(self, staff_client, staff_user, mocker):
        list_users_mock = mocker.patch("blueprints.staff_activity.backend_auth.list_users")
        resp = staff_client.get(f"/staff-activity/{staff_user.id}", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/profile/activity")
        # Redirect xảy ra TRƯỚC khi gọi backend_auth.list_users — không
        # tải dữ liệu thừa cho 1 request sẽ bị chuyển hướng ngay.
        list_users_mock.assert_not_called()

    def test_viewing_other_staff_still_works(self, staff_client, mocker):
        other_id = "other-staff-999"
        mocker.patch(
            "blueprints.staff_activity.backend_auth.list_users",
            return_value=[
                {"ss_user_id": other_id, "full_name": "Người Khác", "role": "ss_team", "email": "other@x.com", "created_at": "2026-01-01T00:00:00Z"},
            ],
        )
        mocker.patch("blueprints.staff_activity.db_data.list_all_jobs", return_value=[])
        mocker.patch("blueprints.staff_activity.db_data.list_all_companies", return_value=[])
        mocker.patch("blueprints.staff_activity.db_data.list_all_contacts", return_value=[])
        resp = staff_client.get(f"/staff-activity/{other_id}")
        assert resp.status_code == 200
        assert "Người Khác" in resp.get_data(as_text=True)

    def test_viewing_nonexistent_id_still_404s(self, staff_client, mocker):
        mocker.patch("blueprints.staff_activity.backend_auth.list_users", return_value=[])
        resp = staff_client.get("/staff-activity/does-not-exist")
        assert resp.status_code == 404


class TestStaffActivityIndexOwnRowLink:
    def test_own_row_links_to_profile_activity_not_detail(self, staff_client, staff_user, mocker):
        mocker.patch(
            "blueprints.staff_activity.backend_auth.list_users",
            return_value=[
                {"ss_user_id": staff_user.id, "full_name": staff_user.full_name, "role": "ss_team", "email": staff_user.email, "created_at": "2026-01-01T00:00:00Z"},
            ],
        )
        resp = staff_client.get("/staff-activity")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Xem tại Trang cá nhân" in body
        assert f"/staff-activity/{staff_user.id}" not in body
