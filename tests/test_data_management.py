"""Lớp 3 cho blueprints/data_management.py — route-level, mock toàn bộ
crawler_client calls.

QUAN TRỌNG — mock đúng vị trí: blueprint import `crawler_client as
db_data`, nên phải patch tại "blueprints.data_management.db_data.<fn>"
(namespace nơi blueprint NHÌN THẤY tên đó), KHÔNG phải
"crawler_client.<fn>" — patch sai chỗ khiến mock coi như không tồn tại,
code thật vẫn chạy và có thể gọi ra internet thật trong lúc test.

Route được chọn theo đúng lịch sử bug thật (xem docstring các route
trong data_management.py — nơi đã sửa 3 bug gần đây về import company
suggestion/duplicate check):
  - export()
  - import_preview()
  - verify_field() — cố ý dùng _call_authed (khác company_suggestions()
    cũ), test đảm bảo route MỚI này thực sự đi qua _call_authed.
  - import_confirm()
"""

import io

import pytest

from crawler_client import CrawlerAPIError


class TestExport:
    def test_export_success_returns_file(self, staff_client, mocker):
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        # export() gọi qua _call_authed(db_data.export_entity, ...) —
        # mock tại blueprints.data_management.db_data (namespace blueprint
        # nhìn thấy), không phải crawler_client trực tiếp.
        mocker.patch(
            "blueprints.data_management.db_data.export_entity",
            return_value=(b"col1,col2\nval1,val2", "job_export.csv", "text/csv"),
        )
        resp = staff_client.get("/data-management/export/job?format=csv")
        assert resp.status_code == 200
        assert resp.data == b"col1,col2\nval1,val2"
        assert "job_export.csv" in resp.headers["Content-Disposition"]

    def test_export_invalid_entity_type_404(self, staff_client, mocker):
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        resp = staff_client.get("/data-management/export/not-a-real-entity")
        assert resp.status_code == 404

    def test_export_backend_error_flashes_and_redirects(self, staff_client, mocker):
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        mocker.patch(
            "blueprints.data_management.db_data.export_entity",
            side_effect=CrawlerAPIError("Backend lỗi 500"),
        )
        resp = staff_client.get("/data-management/export/job", follow_redirects=False)
        assert resp.status_code == 302
        assert "/data-management" in resp.headers["Location"]

    def test_export_default_format_is_xlsx(self, staff_client, mocker):
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        export_mock = mocker.patch(
            "blueprints.data_management.db_data.export_entity",
            return_value=(b"", "x.xlsx", "application/vnd.openxmlformats"),
        )
        staff_client.get("/data-management/export/company")
        # _call_authed(db_data.export_entity, entity_type, file_format) ->
        # fn gọi với (access_token, entity_type, file_format)
        _, called_entity, called_format = export_mock.call_args[0]
        assert called_entity == "company"
        assert called_format == "xlsx"


class TestImportPreview:
    def test_no_file_uploaded_flashes_error(self, staff_client, mocker):
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        resp = staff_client.post(
            "/data-management/import/job/preview", data={}, follow_redirects=False
        )
        assert resp.status_code == 302
        assert "tab=import" in resp.headers["Location"]

    def test_successful_preview_redirects_with_preview_id(self, staff_client, mocker):
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        mocker.patch(
            "blueprints.data_management.db_data.import_preview",
            return_value={
                "preview_id": "prev-123",
                "total_rows": 10,
                "new_count": 7,
                "conflict_count": 2,
                "conflict_inactive_count": 1,
            },
        )
        data = {"file": (io.BytesIO(b"fake,csv,data"), "jobs.csv")}
        resp = staff_client.post(
            "/data-management/import/job/preview",
            data=data,
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "preview=prev-123" in resp.headers["Location"]

    def test_invalid_entity_type_404(self, staff_client, mocker):
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        data = {"file": (io.BytesIO(b"x"), "x.csv")}
        resp = staff_client.post(
            "/data-management/import/not-a-real-entity/preview",
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 404


class TestVerifyField:
    """verify_field() cố ý dùng _call_authed thay vì gọi thẳng như
    company_suggestions() (bản cũ, thiếu refresh) — test đảm bảo route
    MỚI này thực sự tự refresh khi 401, không lặp lại bug cũ."""

    def test_missing_preview_id_returns_400(self, staff_client, mocker):
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        resp = staff_client.post(
            "/data-management/import/job/verify-field",
            json={"field_name": "level_code", "value": "Junior", "row_index": 0},
        )
        assert resp.status_code == 400

    def test_success_path(self, staff_client, mocker):
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        mocker.patch(
            "blueprints.data_management.db_data.get_import_preview",
            return_value={"id_field": "job_id"},
        )
        mocker.patch(
            "blueprints.data_management.db_data.verify_field",
            return_value={"ok": True, "row_index": 0},
        )
        resp = staff_client.post(
            "/data-management/import/job/verify-field",
            json={
                "preview_id": "prev-1", "field_name": "level_code",
                "value": "Junior", "row_index": 0,
            },
        )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_401_triggers_refresh_transparently(self, staff_client, mocker):
        """Đây là bài test cốt lõi của route này: access token hết hạn
        giữa chừng -> _call_authed tự refresh -> route vẫn trả 200,
        KHÔNG crash 500 như bug lịch sử của bản _call_authed cũ."""
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        mocker.patch(
            "blueprints.data_management.db_data.get_import_preview",
            return_value={"id_field": "job_id"},
        )
        mocker.patch(
            "helpers.backend_auth.refresh",
            return_value={"access_token": "new-tok", "refresh_token": "new-refresh"},
        )

        call_count = {"n": 0}

        def verify_field_side_effect(token, *args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise CrawlerAPIError("hết hạn", status_code=401)
            return {"ok": True}

        mocker.patch(
            "blueprints.data_management.db_data.verify_field",
            side_effect=verify_field_side_effect,
        )

        resp = staff_client.post(
            "/data-management/import/job/verify-field",
            json={
                "preview_id": "prev-1", "field_name": "level_code",
                "value": "Junior", "row_index": 0,
            },
        )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        assert call_count["n"] == 2


class TestImportConfirm:
    def test_missing_import_note_flashes_error(self, staff_client, mocker):
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        resp = staff_client.post(
            "/data-management/import/job/confirm",
            data={"preview_id": "prev-1", "resolutions": "[]", "import_note": ""},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "tab=import" in resp.headers["Location"]

    def test_invalid_resolutions_json_flashes_error(self, staff_client, mocker):
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        resp = staff_client.post(
            "/data-management/import/job/confirm",
            data={
                "preview_id": "prev-1", "resolutions": "{not valid json",
                "import_note": "ghi chú",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_success_redirects_to_import_tab(self, staff_client, mocker):
        # Sửa 08/2026 (staff báo bất tiện): TRƯỚC ĐÂY redirect về tab=export
        # sau khi import thành công — staff cần import nhiều lượt liên tiếp
        # phải tự bấm lại tab "Nhập dữ liệu" mỗi lần. Giờ ở lại tab=import
        # (test này ĐÃ ĐỔI assertion so với bản cũ test_success_redirects_
        # to_export_tab — đây là thay đổi hành vi CÓ CHỦ ĐÍCH, không phải
        # regression).
        mocker.patch(
            "blueprints.data_management.db_data.get_level_codes",
            return_value=["Intern"],
        )
        mocker.patch(
            "blueprints.data_management.db_data.import_confirm",
            return_value={"created": 5, "updated": 2, "skipped": 1, "errors": []},
        )
        resp = staff_client.post(
            "/data-management/import/job/confirm",
            data={
                "preview_id": "prev-1", "resolutions": "[]",
                "import_note": "import tuần này",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "tab=import" in resp.headers["Location"]
