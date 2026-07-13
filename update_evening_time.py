"""
update_evening_time.py – Cập nhật giờ bắt đầu buổi tối từ 19:00 → 19:30 trong DB.
Chạy 1 lần sau khi deploy.
"""
import database as db
import sqlite3
from config import DATABASE_PATH

db.init_db()

conn = sqlite3.connect(DATABASE_PATH)
conn.row_factory = sqlite3.Row

# Đếm trước
count = conn.execute(
    "SELECT COUNT(*) FROM schedule_events WHERE session='toi' AND start_time='19:00'"
).fetchone()[0]
print(f"Tìm thấy {count} events tối với start_time=19:00")

# Cập nhật
conn.execute(
    "UPDATE schedule_events SET start_time='19:30', end_time='21:30', updated_at=datetime('now') "
    "WHERE session='toi' AND start_time='19:00'"
)
conn.commit()

after = conn.execute(
    "SELECT COUNT(*) FROM schedule_events WHERE session='toi' AND start_time='19:30'"
).fetchone()[0]
print(f"✅ Đã cập nhật {after} events → 19:30 – 21:30")

conn.close()
