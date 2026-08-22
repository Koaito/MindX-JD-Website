"""Data Management blueprint - import/export functionality"""

import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, jsonify, abort
from utils.decorators import staff_required
import crawler_client as db_data
from crawler_client import CrawlerAPIError
from helpers import _auth_tokens_from_session, _call_authed

data_mgmt_bp = Blueprint("data_mgmt", __name__)


@data_mgmt_bp.route("/data-management")
@staff_required
def index():
    """Trang chọn entity (Job/Company/Contact) + tab Export/Import.

    Query params:
      entity: "job" | "company" | "contact" (mặc định "job")
      tab: "export" | "import" (mặc định "export")
      preview: preview_id — nếu có, load lại preview đã tạo
    """
    entity_type = request.args.get("entity", "job")
    if entity_type not in db_data.IMPORT_EXPORT_ENTITY_TYPES:
        entity_type = "job"
    tab = request.args.get("tab", "export")
    if tab not in ("export", "import"):
        tab = "export"

    access_token, _ = _auth_tokens_from_session()
    preview = None
    preview_id = request.args.get("preview", "")
    if preview_id:
        try:
            preview = db_data.get_import_preview(access_token, entity_type, preview_id)
            if preview is None:
                flash("Bản xem trước đã hết hạn hoặc không tồn tại — vui lòng tải file lên lại.", "error")
        except CrawlerAPIError as exc:
            flash(str(exc), "error")

    return render_template(
        "data_management.html",
        entity_type=entity_type,
        entity_types=db_data.IMPORT_EXPORT_ENTITY_TYPES,
        entity_labels=db_data.IMPORT_EXPORT_ENTITY_LABELS,
        tab=tab,
        preview=preview,
        preview_id=preview_id,
    )


@data_mgmt_bp.route("/data-management/export/<string:entity_type>")
@staff_required
def export(entity_type):
    """Tải file export — gọi trực tiếp bằng GET (link <a>)"""
    if entity_type not in db_data.IMPORT_EXPORT_ENTITY_TYPES:
        abort(404)
    file_format = request.args.get("format", "xlsx")
    if file_format not in ("xlsx", "csv"):
        file_format = "xlsx"

    access_token, _ = _auth_tokens_from_session()
    try:
        content, filename, content_type = _call_authed(
            db_data.export_entity, entity_type, file_format
        )
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        return redirect(url_for("data_mgmt.index", entity=entity_type, tab="export"))

    return Response(
        content,
        mimetype=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@data_mgmt_bp.route("/data-management/import/<string:entity_type>/preview", methods=["POST"])
@staff_required
def import_preview(entity_type):
    """Bước 1: nhận file upload -> gọi backend preview -> redirect sang
    tab import kèm ?preview=<preview_id> để render bảng preview."""
    if entity_type not in db_data.IMPORT_EXPORT_ENTITY_TYPES:
        abort(404)

    file_storage = request.files.get("file")
    if not file_storage or not file_storage.filename:
        flash("Vui lòng chọn file CSV/XLSX để tải lên.", "error")
        return redirect(url_for("data_mgmt.index", entity=entity_type, tab="import"))

    try:
        preview = _call_authed(db_data.import_preview, entity_type, file_storage)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        return redirect(url_for("data_mgmt.index", entity=entity_type, tab="import"))

    flash(
        f"Đã đọc {preview['total_rows']} dòng — {preview['new_count']} dòng mới, "
        f"{preview['conflict_count']} trùng, {preview['conflict_inactive_count']} trùng bản ghi "
        f"ngừng hoạt động, {preview['error_count']} lỗi.",
        "success",
    )
    return redirect(url_for(
        "data_mgmt.index", entity=entity_type, tab="import", preview=preview["preview_id"]
    ))


@data_mgmt_bp.route("/data-management/import/<string:entity_type>/company-suggestions")
@staff_required
def company_suggestions(entity_type):
    """AJAX endpoint — trả JSON danh sách company gợi ý cho 1 dòng cụ thể"""
    if entity_type not in db_data.IMPORT_EXPORT_ENTITY_TYPES:
        abort(404)
    preview_id = request.args.get("preview_id", "")
    try:
        row_index = int(request.args.get("row_index", ""))
    except (TypeError, ValueError):
        return jsonify({"error": "row_index không hợp lệ"}), 400

    access_token, _ = _auth_tokens_from_session()
    try:
        suggestions = db_data.get_company_suggestions(access_token, entity_type, preview_id, row_index)
        return jsonify({"suggestions": suggestions})
    except CrawlerAPIError as exc:
        return jsonify({"error": str(exc)}), (exc.status_code or 500)


@data_mgmt_bp.route("/data-management/import/<string:entity_type>/confirm", methods=["POST"])
@staff_required
def import_confirm(entity_type):
    """Bước 2: nhận resolution map + import_note -> gọi backend confirm"""
    if entity_type not in db_data.IMPORT_EXPORT_ENTITY_TYPES:
        abort(404)

    preview_id = request.form.get("preview_id", "")
    import_note = request.form.get("import_note", "").strip()
    resolutions_raw = request.form.get("resolutions", "[]")

    if not import_note:
        flash("Vui lòng nhập ghi chú (import note) trước khi xác nhận.", "error")
        return redirect(url_for("data_mgmt.index", entity=entity_type, tab="import", preview=preview_id))

    try:
        resolutions = json.loads(resolutions_raw)
    except (TypeError, ValueError):
        flash("Dữ liệu lựa chọn từng dòng bị lỗi định dạng — vui lòng thử lại.", "error")
        return redirect(url_for("data_mgmt.index", entity=entity_type, tab="import", preview=preview_id))

    try:
        result = _call_authed(db_data.import_confirm, entity_type, preview_id, resolutions, import_note)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        return redirect(url_for("data_mgmt.index", entity=entity_type, tab="import", preview=preview_id))

    # Lưu ý: backend (ImportConfirmResult) gộp chung "reactivate" vào
    # "updated", không trả đếm riêng — result["reactivated"] hiện luôn =
    # 0 phía crawler_client.py (xem docstring import_confirm() ở đó),
    # nên KHÔNG hiện dòng "Kích hoạt lại: 0" gây hiểu nhầm là không có
    # dòng nào được kích hoạt lại; số kích hoạt lại (nếu có) đã nằm
    # trong "Cập nhật" ở trên.
    msg = (
        f"Import hoàn tất — Tạo mới: {result['created']}, Cập nhật: {result['updated']}, "
        f"Bỏ qua: {result['skipped']}."
    )
    if result["errors"]:
        msg += f" ({len(result['errors'])} dòng lỗi, xem chi tiết bên dưới.)"
        flash(msg, "error")
    else:
        flash(msg, "success")

    return redirect(url_for("data_mgmt.index", entity=entity_type, tab="export"))
