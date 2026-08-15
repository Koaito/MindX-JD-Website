# MindX Career Hub — Job Board + Contact Database

Website nội bộ cho team Student Success: gộp 2 đề bài (job board Intern/Fresher + database
contact HR/doanh nghiệp) thành 1 hệ thống Flask duy nhất, phong cách giống trang jobs.neu.edu.vn.

## Cài đặt & chạy

```bash
pip install -r requirements.txt
python app.py
```

Mở trình duyệt tại: http://127.0.0.1:5000

Lần chạy đầu tiên, hệ thống tự tạo file `mindx.db` (SQLite) và seed sẵn:
- 8 job mẫu (Code / Data Analysis / Business Analysis, Hà Nội & TP.HCM)
- 7 contact mẫu (HR/Recruiter tại các công ty tương ứng)

Muốn tạo lại dữ liệu mẫu từ đầu: xóa file `mindx.db` rồi chạy lại `python app.py`.

## Cấu trúc

```
app.py              # Flask app: models, seed data, routes
templates/           # Giao diện (Jinja2)
static/style.css      # Toàn bộ style
mindx.db              # Database SQLite (tự tạo khi chạy lần đầu, không có sẵn trong repo)
```

## Bổ sung dữ liệu

- **Qua giao diện**: nút "＋ Thêm job" / "＋ Thêm contact" ở sidebar → điền form → Lưu.
- **Qua code**: sửa hàm `seed_data()` trong `app.py` để thêm dữ liệu mẫu ban đầu (chỉ chạy khi
  database đang trống).
- **Import Excel/CSV**: chưa làm ở bản này (nằm trong "Chức năng nâng cao" của đề bài) — có thể
  bổ sung sau bằng cách đọc file CSV/XLSX (pandas) rồi insert vào model `Job` / `Contact` trong
  `app.py`.

## Các trang chính

| Trang | Route | Ai được vào |
|---|---|---|
| Danh sách job | `/jobs` | Mọi người |
| Chi tiết job | `/jobs/<id>` | Mọi người (nút quản lý/ứng viên chỉ staff thấy) |
| Ứng tuyển job | `/jobs/<id>/apply` (POST) | Học viên đã đăng nhập |
| Lưu / bỏ lưu job | `/jobs/<id>/save` (POST) | Học viên đã đăng nhập |
| Job đã lưu | `/saved-jobs` | Học viên đã đăng nhập |
| Đã ứng tuyển | `/my-applications` | Học viên đã đăng nhập |
| Thêm job | `/jobs/add` | Chỉ staff |
| Danh sách contact | `/contacts` | Chỉ staff |
| Thêm contact | `/contacts/add` | Chỉ staff |
| Dashboard | `/dashboard` | Chỉ staff |

## Phân quyền tài khoản

Hệ thống có 2 loại tài khoản, dùng chung 1 trang đăng nhập (`/login`):

### 1. Team SS (role = `staff`) — toàn quyền
3 tài khoản cố định được seed sẵn (đổi mật khẩu trước khi dùng thật):

| Họ tên | Email | Mật khẩu |
|---|---|---|
| Duy Phạm | `duy.pham@ss.mindx.edu.vn` | `duy.pham` |
| Phong Lê | `phong.le@ss.mindx.edu.vn` | `phong.le` |
| Quản lý hệ thống | `staff.quanly@ss.mindx.edu.vn` | `staff.quanly` |

Đăng nhập bằng 1 trong 3 tài khoản này sẽ vào được toàn bộ chức năng: thêm/sửa/xóa job, thêm/sửa/xóa
contact, xem Dashboard, và xem danh sách học viên đã ứng tuyển từng job. Không thể tự đăng ký tài
khoản staff qua form `/register` — chỉ 3 tài khoản này (hoặc tài khoản được seed thêm trong
`seed_data()` với `role="staff"`) có quyền này.

### 2. Học viên (role = `student`) — chỉ xem + ứng tuyển
Ai cũng có thể tự đăng ký ở `/register` (mặc định `role="student"`). Tài khoản học viên:
- Xem danh sách job, xem chi tiết job.
- **Ứng tuyển** (📨) — ghi nhận vào hệ thống, team SS thấy trong trang chi tiết job.
- **Lưu job** (🔖) — lưu vào mục "Job đã lưu" để xem lại sau.
- Xem lại các job mình đã ứng tuyển ở "Đã ứng tuyển".
- **Không** thấy nút thêm/sửa/xóa job, **không** vào được `/contacts` hoặc `/dashboard` — cố truy
  cập trực tiếp URL sẽ bị chuyển hướng về trang job kèm cảnh báo.

### 3. Người dùng chưa đăng nhập
Chỉ xem được danh sách/chi tiết job. Bấm "Lưu job" hoặc "Ứng tuyển" sẽ được đưa sang trang đăng
nhập/đăng ký.

Tài khoản demo học viên vẫn còn: `demo@student.mindx.edu.vn` / `mindx123`.

## Ghi chú

- Mật khẩu được băm (hash) bằng Werkzeug trước khi lưu, không lưu plaintext.
- Mỗi job có `is_duplicate_candidate` (kiểm tra trùng theo cùng công ty + cùng vị trí), hiển thị
  ở trang chi tiết — đáp ứng yêu cầu "phát hiện job trùng lặp" trong đề bài.
- Dữ liệu mẫu chỉ mang tính minh họa (tên công ty thật nhưng thông tin liên hệ là ví dụ do AI tạo),
  cần thay bằng dữ liệu thật khi triển khai.
- Bản demo dùng session cookie mặc định của Flask — nếu deploy thật (không chỉ chạy local), nên
  đổi `SECRET_KEY` trong `app.py` sang một giá trị bí mật riêng, và đổi mật khẩu 3 tài khoản staff.
