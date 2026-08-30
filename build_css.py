"""Build script — nối public/css/*.css thành 1 file public/style.css thật.

VẤN ĐỀ: public/style.css trước đây dùng @import url(...) để gộp 19 file
con. Browser phải tải xong style.css, PARSE nó, mới biết bên trong có
@import gì — rồi mới bắt đầu tải từng file con, phần lớn theo kiểu nối
đuôi nhau (waterfall) chứ không song song thật sự như <link> riêng lẻ.
Với 19 file, khoản này cộng dồn thành hàng trăm ms tới vài giây round-trip
mạng dù mọi file đều đã cache (304) — xem điều tra /profile load chậm.

GIẢI PHÁP: gộp thật ở build-time thành 1 file duy nhất, browser chỉ tải
1 request CSS. Nhưng KHÔNG xoá 19 file nguồn trong public/css/ — vẫn viết
và sửa CSS ở đó như cũ (mỗi file 1 khu vực UI, đúng convention đã ghi
trong public/style.css cũ). File build ra chỉ là bản build, không phải
nơi để sửa tay.

DEBUG: mỗi khối trong file build ra có comment ranh giới
`/* ==== css/NN-ten-file.css ==== */` ngay phía trên, kèm số dòng bắt
đầu trong file gốc. Mở DevTools thấy lỗi ở dòng X trong file build ra,
cuộn lên tìm comment ranh giới gần nhất phía trên là biết ngay đang ở
file nguồn nào — rồi mở đúng file đó trong public/css/ để sửa, không
sửa trực tiếp vào file build ra (sẽ bị ghi đè ở lần build sau).

CHẠY LÚC NÀO: gọi 1 lần lúc build/deploy (xem vercel.json — buildCommand),
KHÔNG chạy mỗi request lúc app đang serve — filesystem trên Vercel là
read-only lúc runtime nên không thể build lúc đó, và dù được thì cũng
không nên tốn công build lại mỗi lần có người vào trang.

Chạy tay lúc dev: `python build_css.py`
"""

import os

CSS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public", "css")
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public", "style.css")

# Thứ tự PHẢI giữ đúng như bản @import cũ — CSS cascade phụ thuộc thứ tự,
# đổi thứ tự ở đây = đổi luôn cách các rule đè lên nhau lúc render.
# Mô tả ngắn bên cạnh copy nguyên từ comment trong style.css cũ.
BUILD_ORDER = [
    ("00-tokens.css", "CSS variables, reset, body, .shell"),
    ("01-sidebar.css", "Left nav sidebar (all pages)"),
    ("02-auth.css", "Login/register/forgot/verify pages"),
    ("03-layout.css", ".content wrapper, page header, buttons, filter bar"),
    ("04-job-cards.css", 'Job "ticket" cards + grid (index/saved/my-applications)'),
    ("05-contact-table.css", "Companies/contacts table"),
    ("06-detail-page.css", "Job/company detail page layout"),
    ("07-forms.css", "Add/edit job/company/contact forms"),
    ("08-dashboard.css", "/bao-cao dashboard: KPI cards + charts"),
    ("09-misc-toasts.css", "Empty states, flash messages, toasts"),
    ("10-pagination-responsive.css", "Pagination + the shared @media breakpoint"),
    ("11-student-activity.css", "/student-activity: theo dõi học viên lưu/ứng tuyển JD"),
    ("12-activity-logs.css", "/activity-logs: lịch sử thao tác audit log"),
    ("13-data-management.css", "/data-management: xuất/nhập hàng loạt Job/Company/Contact"),
    ("14-email-templates.css", 'Popup chọn/soạn mẫu email liên hệ doanh nghiệp (nút "Mẫu email" ở bảng contact)'),
    ("15-crawl.css", "/crawl: trang crawl dữ liệu (chỉ admin)"),
    ("16-email-template-manager.css", "/contacts?tab=quan-ly: quản lý mẫu email (list + form CRUD)"),
    ("17-error-pages.css", "Trang lỗi tuỳ chỉnh (400/403/404/500) — xem @app.errorhandler trong app.py"),
    ("18-messages.css", "/messages: inbox + khung chat + badge unread sidebar (thêm 08/2026)"),
]

HEADER = """/* ==========================================================================
   MindX Career Hub — stylesheet (FILE BUILD RA — KHÔNG SỬA TRỰC TIẾP)
   ==========================================================================
   File này được sinh tự động bởi build_css.py, nối public/css/*.css lại
   thành 1 request CSS duy nhất (thay vì 19 request @import tuần tự —
   xem docstring build_css.py để biết lý do).

   MUỐN SỬA CSS? Sửa đúng file nguồn trong public/css/NN-ten-file.css,
   rồi chạy `python build_css.py` lại (hoặc để build tự chạy lúc deploy —
   xem vercel.json). Sửa trực tiếp vào file này sẽ MẤT khi build lại.

   DEBUG: mỗi khối bên dưới có comment ranh giới ghi rõ file nguồn +
   dòng bắt đầu trong file đó — dùng để tra ngược khi DevTools chỉ ra
   lỗi ở 1 dòng cụ thể trong file này.
   ========================================================================== */

"""


def build():
    if not os.path.isdir(CSS_DIR):
        raise SystemExit(f"Không tìm thấy thư mục CSS nguồn: {CSS_DIR}")

    on_disk = {f for f in os.listdir(CSS_DIR) if f.endswith(".css")}
    listed = {name for name, _ in BUILD_ORDER}

    missing = listed - on_disk
    if missing:
        raise SystemExit(
            f"BUILD_ORDER liệt kê file không tồn tại trong public/css/: {sorted(missing)}"
        )

    # File mới thêm vào public/css/ nhưng quên đăng ký vào BUILD_ORDER ở
    # trên — chặn build luôn thay vì âm thầm bỏ sót, để không lặp lại
    # kiểu lỗi "quên update danh sách" từng xảy ra với bản @import cũ.
    unlisted = on_disk - listed
    if unlisted:
        raise SystemExit(
            f"Có file .css mới trong public/css/ chưa được thêm vào "
            f"BUILD_ORDER trong build_css.py: {sorted(unlisted)}\n"
            f"Thêm vào đúng vị trí phù hợp trong BUILD_ORDER rồi build lại."
        )

    chunks = [HEADER]
    for filename, description in BUILD_ORDER:
        path = os.path.join(CSS_DIR, filename)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        chunks.append(f"/* ==== css/{filename} ==== */\n")
        chunks.append(f"/* {description} */\n")
        chunks.append(content.rstrip("\n"))
        chunks.append("\n\n")

    with open(OUTPUT_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(chunks))

    total_bytes = os.path.getsize(OUTPUT_PATH)
    print(f"Đã build {len(BUILD_ORDER)} file -> {OUTPUT_PATH} ({total_bytes:,} bytes)")


if __name__ == "__main__":
    build()
