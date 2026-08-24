"""Gợi ý tự động "Tiềm năng hợp tác" cho công ty — thêm 08/2026.

CHỈ LÀ GỢI Ý — không tự ghi đè cột partnership_potential trong DB.
`partnership_potential` vẫn là staff tự chấm tay qua dropdown ở
add_company.html (đúng thiết kế gốc, xem comment trong
sql/migration_add_partnership_potential.sql bên repo backend). Module
này chỉ tính ra 1 badge "🤖 Gợi ý: …" hiển thị CẠNH dropdown đó để
staff tham khảo, tự quyết định có chấm theo hay không.

Vì chỉ là gợi ý hiển thị ở frontend, tính on-the-fly mỗi lần load
trang edit company (không lưu thêm cột DB nào, không cần migration).
Input là dữ liệu ĐÃ có sẵn trong tay Flask app lúc render trang
(company đã kèm `jobs`, cộng thêm contacts lấy riêng) — không gọi
thêm request nào ngoài những gì trang edit vốn đã cần.
"""

from constants import INDUSTRIES

# Level "mới ra trường" — khớp level_group 'Entry Level' bên backend
# (sql/schema.sql: Intern/Fresher/Junior). Hard-code ở đây vì
# level_group không có trong job đã normalize (crawler_client chỉ trả
# level_code) — 3 giá trị này ổn định, ít đổi hơn nhiều so với việc gọi
# thêm 1 API chỉ để tra level_group.
_ENTRY_LEVELS = {"Intern", "Fresher", "Junior"}

_RESPONDED_STATUSES = {"RESPONDED", "IN_PARTNERSHIP"}

_HN_HCM = {"Hà Nội", "TP. Hồ Chí Minh"}

# Ngưỡng quy đổi tổng điểm (0-5) -> mức gợi ý. Đặt tên hằng thay vì số
# ma thuật rải rác, dễ chỉnh nếu sau này thấy ngưỡng chưa hợp lý.
_HIGH_THRESHOLD = 4
_MEDIUM_THRESHOLD = 2


def suggest_partnership_potential(company: dict, contacts: list) -> dict:
    """Tính điểm gợi ý tiềm năng hợp tác từ dữ liệu công ty + contact.

    company: dict đã chuẩn hoá qua crawler_client._normalize_company()
             (cần .jobs, .city, .company_size) — .jobs là None nếu công
             ty MỚI THÊM (chưa lưu), khi đó coi như danh sách rỗng.
    contacts: list dict đã chuẩn hoá qua _normalize_contact() (cần
              .status_raw) — truyền [] nếu công ty chưa có contact nào.

    Trả về:
      {
        "level": "HIGH" | "MEDIUM" | "LOW",
        "score": int,          # điểm đạt được, 0-5
        "max_score": 5,
        "reasons": [str, ...], # các tiêu chí ĐÃ đạt, hiển thị dạng tooltip
      }
    """
    jobs = company.get("jobs") or []
    reasons = []

    has_open_entry_job = any(
        j.get("status_raw") == "OPEN" and j.get("level") in _ENTRY_LEVELS
        for j in jobs
    )
    if has_open_entry_job:
        reasons.append("Đang có job Intern/Fresher/Junior còn tuyển (OPEN)")

    matches_target_industry = any(j.get("industry") in INDUSTRIES for j in jobs)
    if matches_target_industry:
        reasons.append("Có job thuộc đúng nhóm ngành MindX đào tạo (Code/Data/BA/UI-UX)")

    is_hn_hcm = (company.get("city") or "") in _HN_HCM
    if is_hn_hcm:
        reasons.append("Trụ sở/địa điểm tại Hà Nội hoặc TP.HCM")

    has_responded = any((c.get("status_raw") or "") in _RESPONDED_STATUSES for c in contacts)
    if has_responded:
        reasons.append("Đã từng có người liên hệ phản hồi hoặc đang hợp tác")

    has_company_size = bool((company.get("company_size") or "").strip())
    if has_company_size:
        reasons.append("Đã xác định được quy mô nhân sự")

    score = sum([
        has_open_entry_job,
        matches_target_industry,
        is_hn_hcm,
        has_responded,
        has_company_size,
    ])

    if score >= _HIGH_THRESHOLD:
        level = "HIGH"
    elif score >= _MEDIUM_THRESHOLD:
        level = "MEDIUM"
    else:
        level = "LOW"

    return {"level": level, "score": score, "max_score": 5, "reasons": reasons}
