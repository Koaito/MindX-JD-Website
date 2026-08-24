"""Audit logs — "Lịch sử thao tác" (thêm 08/2026, xem
sql/migration_add_audit_logs.sql phía backend). 2 view auto/manual
trên CÙNG 1 endpoint GET /audit-logs, khác nhau ở query param `view`
— KHÔNG phải 2 route riêng, mirror đúng thiết kế backend."""

from .base import _request

ACTION_TYPE_MAP = {
    "CREATE_JOB": "Thêm JD", "UPDATE_JOB": "Sửa JD", "DELETE_JOB": "Xoá JD",
    "CREATE_COMPANY": "Thêm công ty", "UPDATE_COMPANY": "Sửa công ty", "DELETE_COMPANY": "Xoá công ty",
    "CREATE_CONTACT": "Thêm người liên hệ", "UPDATE_CONTACT": "Sửa người liên hệ",
    "DELETE_CONTACT": "Xoá người liên hệ", "ASSIGN_CONTACT": "Gán người phụ trách",
    "APPLY_JOB": "Ứng viên nộp CV", "WITHDRAW_JOB_APPLICATION": "Ứng viên huỷ ứng tuyển",
}
ENTITY_TYPE_MAP = {"JOB": "JD", "COMPANY": "Công ty", "CONTACT": "Người liên hệ", "APPLICATION": "Đơn ứng tuyển"}


def _normalize_audit_log(raw: dict) -> dict:
    return {
        "id": raw.get("log_id"),
        "actor_id": raw.get("actor_id"),
        # actor_name None -> "Hệ thống (tự động)" thay vì để trống —
        # actor_id NULL nghĩa là thao tác tự động, KHÔNG phải lỗi thiếu
        # dữ liệu (xem docstring db.log_action() phía backend).
        "actor_name": raw.get("actor_name") or "Hệ thống (tự động)",
        "action_type": raw.get("action_type") or "",
        "action_label": ACTION_TYPE_MAP.get(raw.get("action_type"), raw.get("action_type") or ""),
        "entity_type": raw.get("entity_type") or "",
        "entity_label_type": ENTITY_TYPE_MAP.get(raw.get("entity_type"), raw.get("entity_type") or ""),
        "entity_id": raw.get("entity_id"),
        "entity_label": raw.get("entity_label") or "",
        "company_id": raw.get("company_id"),
        "company_name": raw.get("company_name") or "",
        "changes": raw.get("changes") or {},
        "is_manual_log": raw.get("is_manual_log", False),
        "note_required": raw.get("note_required", False),
        "note": raw.get("note") or "",
        "note_updated_by": raw.get("note_updated_by"),
        "note_updated_at": raw.get("note_updated_at"),
        "created_at": raw.get("created_at"),
    }


def list_audit_logs(access_token, *, view="auto", entity_type="", company_id="", actor_id="",
                     action_type="", pending_note=None, limit=50, offset=0) -> dict:
    """GET /audit-logs — trả {"items": [...], "total": int}.

    BẮT BUỘC truyền access_token thật — route backend yêu cầu
    require_role("ss_team") qua chính JWT trong Authorization header
    (KHÔNG chỉ check API key như GET /jobs, /companies công khai), xem
    api/deps.py::require_role backend. Gọi qua _call_authed() ở app.py
    để tự refresh nếu access_token hết hạn giữa chừng, giống mọi hàm
    cần access_token khác trong package này."""
    params = {"view": view, "limit": limit, "offset": offset}
    if entity_type:
        params["entity_type"] = entity_type
    if company_id:
        params["company_id"] = company_id
    if actor_id:
        params["actor_id"] = actor_id
    if action_type:
        params["action_type"] = action_type
    if pending_note is not None:
        params["pending_note"] = "true" if pending_note else "false"
    data = _request("GET", "/audit-logs", access_token=access_token, params=params) or {}
    items = [_normalize_audit_log(r) for r in data.get("items", [])]
    return {"items": items, "total": data.get("total", 0)}


def update_audit_log_note(access_token, log_id, note) -> dict:
    """PATCH /audit-logs/{log_id}/note — CHỈ actor GỐC của log (người
    thực hiện thao tác đó) mới gọi được, backend trả 403 nếu người
    khác gọi (xem api/routers/audit_logs.py::update_note backend) —
    app.py nên ẨN nút sửa note nếu current_user khác actor_id, nhưng
    vẫn phải bắt CrawlerAPIError(403) ở đây phòng người dùng cố tình
    gọi thẳng URL."""
    raw = _request("PATCH", f"/audit-logs/{log_id}/note", access_token=access_token, json={"note": note})
    return _normalize_audit_log(raw)
