"""
Thay thế cho thư viện python-dotenv — tự đọc file .env, không phụ thuộc
gói ngoài. Lý do đổi: python-dotenv (bản đang ghim trong requirements.txt)
không cài/chạy được trên Python 3.14 ở máy 1 số bạn trong team. Chỉ cần
đọc file KEY=VALUE đơn giản nên tự viết ~30 dòng để bỏ hẳn dependency đó,
không cần đợi bản python-dotenv mới hỗ trợ 3.14.

Hỗ trợ đúng những gì .env của project này cần:
  - dòng trống, dòng bắt đầu bằng "#" -> bỏ qua (comment)
  - KEY=VALUE (khoảng trắng quanh dấu "=" được bỏ qua)
  - VALUE có thể để trong dấu "..." hoặc '...' -> tự bỏ dấu ngoặc
  - không ghi đè biến môi trường đã có sẵn (giống hành vi mặc định của
    python-dotenv: os.environ có trước thì ưu tiên hơn giá trị trong .env)
"""

import os


def load_env_file(path=".env"):
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()

            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]

            if key and key not in os.environ:
                os.environ[key] = value
