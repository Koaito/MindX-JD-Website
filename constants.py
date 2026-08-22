"""Hằng số dùng chung toàn app.

Trước đây các hằng số này được định nghĩa trong app.py và các blueprint
phải `from app import X` (import ngược, bên trong thân hàm) để lấy —
khiến lỗi thiếu/sai tên biến chỉ lộ ra khi có người bấm đúng route đó,
không lộ lúc khởi động app. Gom hết vào đây để:
  - app.py và blueprints/*.py đều import xuôi từ 1 nguồn duy nhất.
  - Không còn phụ thuộc vòng (blueprint phụ thuộc app.py).
"""

import crawler_client as db_data

INDUSTRIES = [
    "Code", "Data Analysis", "Data Engineer", "Data Scientist",
    "Business Analysis", "UI/UX Design",
]

LEVELS = db_data.LEVEL_CODES
LOCATIONS = ["Hà Nội", "TP.HCM", "Remote", "Hybrid"]

CITIES_VN = [
    "Hà Nội", "TP. Hồ Chí Minh", "Đà Nẵng", "Cần Thơ", "Hải Phòng",
    "An Giang", "Bà Rịa - Vũng Tàu", "Bắc Giang", "Bắc Kạn", "Bạc Liêu",
    "Bắc Ninh", "Bến Tre", "Bình Định", "Bình Dương", "Bình Phước",
    "Bình Thuận", "Cà Mau", "Cao Bằng", "Đắk Lắk", "Đắk Nông",
    "Điện Biên", "Đồng Nai", "Đồng Tháp", "Gia Lai", "Hà Giang",
    "Hà Nam", "Hà Tĩnh", "Hải Dương", "Hậu Giang", "Hòa Bình",
    "Hưng Yên", "Khánh Hòa", "Kiên Giang", "Kon Tum", "Lai Châu",
    "Lâm Đồng", "Lạng Sơn", "Lào Cai", "Long An", "Nam Định",
    "Nghệ An", "Ninh Bình", "Ninh Thuận", "Phú Thọ", "Phú Yên",
    "Quảng Bình", "Quảng Nam", "Quảng Ngãi", "Quảng Ninh", "Quảng Trị",
    "Sóc Trăng", "Sơn La", "Tây Ninh", "Thái Bình", "Thái Nguyên",
    "Thanh Hóa", "Thừa Thiên Huế", "Tiền Giang", "Trà Vinh", "Tuyên Quang",
    "Vĩnh Long", "Vĩnh Phúc", "Yên Bái",
]

JOB_STATUSES = list(db_data.JOB_STATUS_MAP.values())
WORK_TYPES = list(db_data.WORK_TYPE_MAP.values())
SALARY_TYPES = list(db_data.SALARY_TYPE_MAP.values())
SALARY_PERIODS = list(db_data.SALARY_PERIOD_MAP.values())

CONTACT_STATUSES = list(db_data.CONTACT_STATUS_MAP.values())
PARTNERSHIP_POTENTIALS = list(db_data.PARTNERSHIP_POTENTIAL_MAP.values())

JOBS_PER_PAGE = 20
COMPANIES_PER_PAGE = 20

ROLE_LABELS = {"user": "Học viên", "ss_team": "Team SS", "admin": "Admin"}
