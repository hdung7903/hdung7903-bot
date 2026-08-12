"""
test_reschedule.py – Test toàn diện cho việc phát hiện đổi lịch,
reset reminder, và format thông báo rõ ràng.

Chạy: python test_reschedule.py
"""
import os, sys, tempfile, json, textwrap
from datetime import datetime, timedelta, timezone

# ── Setup env trước khi import bất kỳ module nào ──────────────────────────────
tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp_db.close()
os.environ.setdefault("DATABASE_PATH", tmp_db.name)
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
os.environ.setdefault("NOTIFY_BEFORE_HOURS", "24")

# ── Import sau khi set env ─────────────────────────────────────────────────────
import database as db
import notifier

# ── Helpers ────────────────────────────────────────────────────────────────────
PASS = "✅ PASS"
FAIL = "❌ FAIL"
results: list[tuple[str, bool, str]] = []

def check(name: str, condition: bool, detail: str = ""):
    icon = PASS if condition else FAIL
    results.append((name, condition, detail))
    print(f"  {icon}  {name}" + (f"\n       {detail}" if detail and not condition else ""))

def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

def make_event(event_id="ev1", date="2026-08-01", session="sang",
               subject="PP Giảng dạy Môn Tin", teacher="GV A",
               start_time="08:00", end_time="10:00", link="") -> dict:
    return {
        "id": event_id, "legacy_ids": [], "class_id": "TEST-CLASS",
        "subject": subject, "teacher": teacher, "room": "",
        "session": session, "date": date,
        "start_time": start_time, "end_time": end_time,
        "link": link, "is_approximate": False,
        "date_range_end": None, "time_raw": "", "raw_data": {},
    }

# ══════════════════════════════════════════════════════════════════════════════
section("1. DB – upsert_event trả về đúng kiểu")
# ══════════════════════════════════════════════════════════════════════════════
db.init_db()

ev1 = make_event()
is_new, changes = db.upsert_event(ev1)
check("Lần đầu insert: is_new=True", is_new is True, f"is_new={is_new}")
check("Lần đầu insert: changes={{}}", changes == {}, f"changes={changes}")

is_new2, changes2 = db.upsert_event(ev1)
check("Insert lại y chang: is_new=False", is_new2 is False, f"is_new2={is_new2}")
check("Insert lại y chang: changes={{}}", changes2 == {}, f"changes2={changes2}")

# ══════════════════════════════════════════════════════════════════════════════
section("2. DB – Phát hiện đổi ngày")
# ══════════════════════════════════════════════════════════════════════════════
ev1_moved = make_event(date="2026-08-05")  # đổi ngày
is_new3, changes3 = db.upsert_event(ev1_moved)
check("Đổi ngày: is_new=False", is_new3 is False, f"is_new3={is_new3}")
check("Đổi ngày: changes['date'] tồn tại", "date" in changes3, f"changes3={changes3}")
check("Đổi ngày: old_val đúng", changes3.get("date", ("?",))[0] == "2026-08-01",
      f"old={changes3.get('date')}")
check("Đổi ngày: new_val đúng", changes3.get("date", (None,"?"))[1] == "2026-08-05",
      f"new={changes3.get('date')}")

# ══════════════════════════════════════════════════════════════════════════════
section("3. DB – Reminder bị reset khi đổi ngày")
# ══════════════════════════════════════════════════════════════════════════════
# Mark reminder đã gửi
db.mark_notification_sent("ev1", "reminder")
check("Mark sent: is_notification_sent=True",
      db.is_notification_sent("ev1", "reminder"))

# Đổi ngày lần 2 → phải reset reminder
ev1_moved2 = make_event(date="2026-08-10")
db.upsert_event(ev1_moved2)
check("Sau đổi ngày: reminder bị RESET (is_notification_sent=False)",
      not db.is_notification_sent("ev1", "reminder"),
      "BUG: reminder vẫn còn → bot sẽ KHÔNG nhắc buổi mới!")

# ══════════════════════════════════════════════════════════════════════════════
section("4. DB – Đổi giờ/giảng viên KHÔNG reset reminder")
# ══════════════════════════════════════════════════════════════════════════════
ev2 = make_event(event_id="ev2", date="2026-08-15")
db.upsert_event(ev2)
db.mark_notification_sent("ev2", "reminder")

ev2_teacher_change = make_event(event_id="ev2", date="2026-08-15", teacher="GV B")
db.upsert_event(ev2_teacher_change)
check("Đổi giảng viên: reminder KHÔNG bị reset",
      db.is_notification_sent("ev2", "reminder"),
      "Reminder bị xóa sai khi chỉ đổi giảng viên")

ev2_link_change = make_event(event_id="ev2", date="2026-08-15",
                              teacher="GV B", link="https://teams.microsoft.com/new")
db.upsert_event(ev2_link_change)
check("Đổi link Teams: reminder KHÔNG bị reset",
      db.is_notification_sent("ev2", "reminder"),
      "Reminder bị xóa sai khi chỉ đổi link")

# ══════════════════════════════════════════════════════════════════════════════
section("5. DB – Đổi buổi (sáng→tối) RESET reminder")
# ══════════════════════════════════════════════════════════════════════════════
ev3 = make_event(event_id="ev3", date="2026-08-20", session="sang")
db.upsert_event(ev3)
db.mark_notification_sent("ev3", "reminder")

ev3_session = make_event(event_id="ev3", date="2026-08-20", session="toi")
db.upsert_event(ev3_session)
check("Đổi buổi sang→tối: reminder bị RESET",
      not db.is_notification_sent("ev3", "reminder"),
      "BUG: reminder vẫn còn sau khi đổi buổi!")

# ══════════════════════════════════════════════════════════════════════════════
section("6. Notifier – build_changed_event_message format đúng")
# ══════════════════════════════════════════════════════════════════════════════
ev_sample = make_event(date="2026-08-05", session="sang")
changes_date = {"date": ("2026-08-01", "2026-08-05")}
msg_reschedule = notifier.build_changed_event_message(ev_sample, changes_date)

check("Thông báo đổi ngày có ⚠️",    "⚠️" in msg_reschedule,
      f"msg={msg_reschedule[:100]}")
check("Thông báo đổi ngày có 'ĐỔI NGÀY'", "ĐỔI NGÀY" in msg_reschedule,
      f"msg={msg_reschedule[:100]}")
check("Thông báo đổi ngày chứa ngày cũ (01/08)",
      "01/08" in msg_reschedule, f"msg={msg_reschedule[:200]}")
check("Thông báo đổi ngày chứa ngày mới (05/08)",
      "05/08" in msg_reschedule, f"msg={msg_reschedule[:200]}")

changes_link = {"link": ("https://old.link", "https://new.link")}
msg_link = notifier.build_changed_event_message(ev_sample, changes_link)
check("Đổi link: tiêu đề là ✏️ (không phải ⚠️)", "✏️" in msg_link and "⚠️" not in msg_link,
      f"msg={msg_link[:100]}")

# ══════════════════════════════════════════════════════════════════════════════
section("7. Notifier – build_sync_notification với changed_events dạng tuple")
# ══════════════════════════════════════════════════════════════════════════════
ev_changed = make_event(date="2026-08-05")
changed_list = [(ev_changed, {"date": ("2026-08-01", "2026-08-05")})]
sync_msg = notifier.build_sync_notification([], changed_list, total=10)

check("Sync msg có ⚠️ khi có đổi ngày",  "⚠️" in sync_msg,
      f"sync_msg={sync_msg[:150]}")
check("Sync msg có 'Bị ĐỔI'", "Bị ĐỔI" in sync_msg,
      f"sync_msg={sync_msg[:150]}")
check("Sync msg không crash khi changed_events=[]",
      notifier.build_sync_notification([], [], total=5) is not None)

no_change_msg = notifier.build_sync_notification([], [], total=5)
check("Không có thay đổi: hiển thị 'như cũ'", "như cũ" in no_change_msg)

# ══════════════════════════════════════════════════════════════════════════════
section("8. Notifier – get_events_needing_reminder chỉ lấy buổi CHƯA sent")
# ══════════════════════════════════════════════════════════════════════════════
VN_TZ = timezone(timedelta(hours=7))
now_vn = datetime.now(VN_TZ)
tomorrow = (now_vn + timedelta(days=1)).strftime("%Y-%m-%d")

# Event ngày mai chưa sent
ev_remind = make_event(event_id="ev_remind_test", date=tomorrow, session="sang",
                       subject="Test Remind Subject", start_time="08:00", end_time="10:00")
db.upsert_event(ev_remind)

reminders = notifier.get_events_needing_reminder()
ids = [e["id"] for e, _ in reminders]
check("Event ngày mai chưa sent → có trong danh sách nhắc",
      "ev_remind_test" in ids,
      f"ids={ids}")

# Mark sent → không được nhắc nữa
db.mark_notification_sent("ev_remind_test", "reminder")
reminders2 = notifier.get_events_needing_reminder()
ids2 = [e["id"] for e, _ in reminders2]
check("Sau mark_sent → KHÔNG còn trong danh sách nhắc",
      "ev_remind_test" not in ids2,
      f"ids2={ids2}")

# ══════════════════════════════════════════════════════════════════════════════
section("9. Flow end-to-end: đổi ngày → reminder được gửi lại")
# ══════════════════════════════════════════════════════════════════════════════
ev_flow = make_event(event_id="ev_flow", date=tomorrow, session="sang",
                     subject="Flow Test", start_time="08:00", end_time="10:00")
db.upsert_event(ev_flow)
db.mark_notification_sent("ev_flow", "reminder")

# Lịch đổi → ngày mai + 1
day_after = (now_vn + timedelta(days=2)).strftime("%Y-%m-%d")
ev_flow_moved = make_event(event_id="ev_flow", date=day_after, session="sang",
                           subject="Flow Test", start_time="08:00", end_time="10:00")
_, ch = db.upsert_event(ev_flow_moved)
check("Đổi ngày flow: changes có 'date'", "date" in ch)
check("Sau đổi ngày: is_notification_sent=False (đã reset)",
      not db.is_notification_sent("ev_flow", "reminder"),
      "BUG CRITICAL: reminder không reset → sẽ miss buổi học!")

# ══════════════════════════════════════════════════════════════════════════════
section("10. Reconcile – API xóa lịch phải được thông báo")
# ══════════════════════════════════════════════════════════════════════════════
ev_removed = make_event(event_id="ev_removed", date="2026-08-30", subject="Buổi bị hủy")
db.upsert_event(ev_removed)
deleted_events = db.reconcile_stale_events_for_class("TEST-CLASS", set())
check("Event không còn trong API bị xóa khỏi DB", len(deleted_events) > 0)
check("Thông báo sync nêu rõ lịch bị hủy/xóa",
      "Lịch đã bị hủy/xóa" in notifier.build_sync_notification([], [], 0, deleted_events=deleted_events))

# ══════════════════════════════════════════════════════════════════════════════
section("11. API lỗi một phần – không báo lịch như cũ")
# ══════════════════════════════════════════════════════════════════════════════
partial_failure_msg = notifier.build_sync_notification(
    [], [], 10, failed_classes={"TEST-CLASS"}
)
check("API lỗi một phần có cảnh báo", "Đồng bộ chưa hoàn tất" in partial_failure_msg)
check("API lỗi một phần không nói lịch như cũ", "Lịch học như cũ" not in partial_failure_msg)

# ══════════════════════════════════════════════════════════════════════════════
# Kết quả tổng hợp
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*60}")
total  = len(results)
passed = sum(1 for _, ok, _ in results if ok)
failed = total - passed

print(f"  KẾT QUẢ: {passed}/{total} tests passed", end="")
if failed:
    print(f"  ←  {failed} FAILED ⚠️")
    print("\n  FAILED TESTS:")
    for name, ok, detail in results:
        if not ok:
            print(f"    ❌ {name}")
            if detail:
                print(f"       {detail}")
else:
    print("  🎉 Tất cả tests PASS!")
print('='*60)

# Cleanup
try:
    os.unlink(tmp_db.name)
except Exception:
    pass

sys.exit(0 if failed == 0 else 1)
