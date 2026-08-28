"""Helper dùng CHUNG cho tab "Tình trạng dữ liệu" (/crawl?tab=status) —
đếm số record thiếu (rỗng) từng field trên 1 tập dữ liệu đã chuẩn hoá
(company hoặc job). Tách file riêng (không để thẳng trong companies.py)
vì từ 08/2026 CẢ company (companies.py) lẫn job (jobs.py) đều cần cùng
1 logic đếm này — tránh lặp code 2 chỗ, mirror cách base.py tách phần
lõi dùng chung khỏi từng domain.

KHÔNG gọi API ở đây — nhận sẵn list record đã _normalize_company()/
_normalize_job(), tính on-the-fly (không lưu DB, không cache), giống
nguyên tắc các hàm _companies_*/_jd_* ở blueprints/dashboard.py."""


def count_missing_fields(items, field_specs):
    """items: list dict đã chuẩn hoá (company hoặc job).
    field_specs: list các tuple, mỗi phần tử là 1 trong 2 dạng:
      (key, label) — mặc định "thiếu" = falsy tại items[i][key] (rỗng/
      None/0/False đều tính là thiếu — khớp cách _normalize_company()/
      _normalize_job() đã quy None -> "" nên chỉ cần check falsy).
      (key, label, predicate) — dùng khi "thiếu" không đơn giản là 1
      field rỗng (vd job "thiếu lương" nghĩa là CẢ salary_min LẪN
      salary_max đều rỗng, xem JOB_HEALTH_FIELDS ở jobs.py). predicate
      nhận 1 item, trả True nếu item đó tính là "thiếu" field này.

    Trả về list dict theo ĐÚNG thứ tự field_specs (không tự sort theo %
    thiếu) để UI ổn định qua nhiều lần load.
    """
    total = len(items)
    rows = []
    for spec in field_specs:
        if len(spec) == 3:
            key, label, predicate = spec
        else:
            key, label = spec
            predicate = lambda item, k=key: not item.get(k)
        missing = sum(1 for item in items if predicate(item))
        pct_missing = round(missing / total * 100) if total else 0
        rows.append({
            "field": key,
            "label": label,
            "missing": missing,
            "total": total,
            "pct_missing": pct_missing,
        })
    return rows
