"""
import_manual_schedule.py – Import lịch học thủ công vào DB.

Chạy 1 lần: python import_manual_schedule.py
Sau đó có thể chạy lại để update nếu lịch thay đổi (upsert an toàn).
"""
import json
import logging
import sys

logging.basicConfig(
    format="%(levelname)-8s | %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

MANUAL_DATA = [
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "Công tác tổ chức lớp học, hướng dẫn học online và tự học trên hệ thống LMS",
        "teacher": "Lê Văn Dương",
        "time": "Tối 08,05/05/2026 (Thứ 6)",   # Sửa typo "05//2026" → "05/05/2026"
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "A2. Giáo dục học",
        "teacher": "TS. Bùi Thị Thùy Dương, ĐT: 0989761109",
        "time": "Tối 26,27/5/2026 (Thứ 3, Thứ 4)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "A1. Tâm lý học Giáo dục",
        "teacher": "TS. Phạm Thị Yến, ĐT: 0869227972",
        "time": "Tối 04,05/06/2026 (Thứ 5, Thứ 6)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "A3. Lý luận dạy học",
        "teacher": "ThS. Nguyễn Trung Kiền, ĐT: 0918634904",
        "time": "Tối 16,17/06/2026 (Thứ 3, Thứ 4)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "A4. Đánh giá trong giáo dục",
        "teacher": "TS. Nguyễn Thị Quỳnh Anh, ĐT: 0967586668",
        "time": "Tối 22,23/06/2026 (Thứ 2, Thứ 3)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "A5. Quản lý Nhà nước trong giáo dục",
        "teacher": "TS. Nguyễn Thị Thu Hằng, ĐT: 0915537188",
        "time": "Tối 05,06/07/2026 (Chủ nhật, Thứ 2)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "A6. Giao tiếp sư phạm",
        "teacher": "TS. Phạm Thị Yến, ĐT: 0869227972",
        "time": "Tối 12,13/07/2026 (Chủ nhật, Thứ 2)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "A7. Rèn luyện Nghiệp vụ sư phạm (HD: 01/7/2026)",
        "teacher": "TS. Nguyễn Thị Việt Hà, ĐT: 0989256276",
        "time": "Từ 015-20/07/2026",   # typo "015" → sẽ được xử lý
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "A12. Ứng dụng CNTT trong dạy học",
        "teacher": "TS. Võ Đức Quang, ĐT: 0989891418",
        "time": "Tối 21,22/07/2026 (Thứ 3, Thứ 4)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "B1/C1. Phương pháp dạy học môn Toán, Lý, Hóa, Sinh ở trường THCS / THPT",
        "teacher": "TS. Lê Văn Vinh, ĐT: 0969575498",
        "time": "Tối 26,27/07/2026 (Chủ nhật, Thứ 2)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "B1/C1. Phương pháp dạy học môn Ngữ văn/ Lịch sử / Địa lý ở trường THCS / THPT",
        "teacher": "TS. Ngô Thị Quỳnh Nga, ĐT: 0944368767",
        "time": "Tối 29,30/07/2026 (Thứ 2, Thứ 3)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "B1/C1. Phương pháp dạy học môn Tiếng Anh ở trường THCS / THPT",
        "teacher": "ThS. Lê Thị Thanh Bình, ĐT: 0917368737",
        "time": "Tối 02,03/08/2026 (Chủ nhật, Thứ 2)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "B1/C1. Phương pháp dạy học môn Tin học ở trường THCS / THPT",
        "teacher": "TS. Trần Thị Kim Oanh, ĐT: 0912488055",
        "time": "Tối 05,06/08/2026 (Thứ 4, Thứ 5)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "B1/C1. Phương pháp dạy học môn GDCD/ GD Kinh tế Pháp luật ở trường THCS / THPT",
        "teacher": "GV. TS. Bùi Thị Cần, ĐT: 0916811309",
        "time": "Tối 09,10/08/2026 (Chủ nhật, Thứ 2)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "B1/C1. Phương pháp dạy học môn GDTC ở trường THCS / THPT",
        "teacher": "TS. Võ Văn Đăng, ĐT: 0966780793",
        "time": "Tối 12,13/08/2026 (Thứ 4, Thứ 5)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "B2/C2. Xây dựng kế hoạch dạy học môn Toán, Lý, Hóa, Sinh ở trường THCS / THPT",
        "teacher": "TS. Lê Văn Vinh, ĐT: 0969575498",
        "time": "Tối 16,17/08/2026 (Chủ nhật, Thứ 2)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "B2/C2. Xây dựng kế hoạch dạy học môn Ngữ văn/ Lịch sử / Địa lý ở trường THCS / THPT",
        "teacher": "TS. Ngô Thị Quỳnh Nga, ĐT: 0944368767",
        "time": "Tối 19,20/08/2026 (Thứ 4, Thứ 5)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "B2/C2. Xây dựng kế hoạch dạy học môn Tiếng Anh ở trường THCS / THPT",
        "teacher": "ThS. Lê Thị Thanh Bình, ĐT: 0917368737",
        "time": "Tối 23,24/08/2026 (Chủ nhật, Thứ 2)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "B2/C2. Xây dựng kế hoạch dạy học môn Tin học ở trường THCS / THPT",
        "teacher": "ThS. Trần Lê Hà, ĐT: 0964804807",
        "time": "Tối 26,27/08/2026 (Thứ 4, Thứ 5)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "B2/C2. Xây dựng kế hoạch dạy học môn GDCD / GD Kinh tế Pháp luật ở trường THCS / THPT",
        "teacher": "TS Bùi Thị Cần, ĐT: 0916811309",
        "time": "Tối 30,31/08/2026 (Chủ nhật, Thứ 2)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "B2/C2. Xây dựng kế hoạch dạy học môn GDTC ở trường THCS / THPT",
        "teacher": "TS. Võ Văn Đăng, ĐT: 0966780793",
        "time": "Tối 09,10/09/2026 (Thứ 4, Thứ 5)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "B3/C3. Tổ chức dạy học môn Toán, Lý, Hóa, Sinh ở trường THCS / THPT",
        "teacher": "TS. Lê Văn Vinh, ĐT: 0969575498",
        "time": "Tối 13,14/09/2026 (Chủ nhật, Thứ 2)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "B3/C3. Tổ chức dạy học môn Ngữ văn/ Lịch sử/Địa lý ở trường THCS / THPT",
        "teacher": "TS. Nguyễn Thị Việt Hà, ĐT: 0989256276",
        "time": "Tối 16,17/09/2026 (Thứ 4, Thứ 5)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "B3/C3. Tổ chức dạy học môn Tiếng Anh ở trường THCS / THPT",
        "teacher": "ThS. Lê Thị Thanh Bình, ĐT: 0917368737",
        "time": "Tối 20,21/09/2026 (Chủ nhật, Thứ 2)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "B3/C3. Tổ chức dạy học môn Tin học ở trường THCS / THPT",
        "teacher": "ThS. Trần Lê Hà, ĐT: 0964804807",
        "time": "Tối 23,24/09/2026 (Thứ 4, Thứ 5)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "B3/C3. Tổ chức dạy học môn GDCD / GD Kinh tế Pháp luật ở trường THCS / THPT",
        "teacher": "TS. Bùi Thị Cần, ĐT: 0916811309",
        "time": "Tối 27,28/09/2026 (Chủ nhật, Thứ 2)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "B3/C3. Tổ chức dạy học môn GDTC ở trường THCS / THPT",
        "teacher": "TS. Võ Văn Đăng, ĐT: 0966780793",
        "time": "Tối 30/9 và 01/10/2026 (Thứ 4, Thứ 5)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "B4/C4. Thực hành dạy học môn ..... cấp THCS / THPT tại trường sư phạm",
        "teacher": "Giảng viên theo nhóm chuyên môn đánh giá",
        "time": "Từ 05-12/10/2026",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "B9/C9. Tổ chức hoạt động trải nghiệm, hướng nghiệp ở trường THCS",
        "teacher": "TS. Trần Thị Gái, ĐT: 0936280986",
        "time": "Tối 18,19/10/2026 (Chủ nhật, Thứ 2)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "Học và hoàn thành bài tập trên LMS, kiểm tra đánh giá các học phần",
        "teacher": "Theo kế hoạch",
        "time": "Tháng 10,11/2026",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "B5. Hướng dẫn làm kế hoạch và thực hành tại trường phổ thông",
        "teacher": "TS. Nguyễn Thị Việt Hà, ĐT: 0989256276",
        "time": "Tối 15/11/2026 (Chủ nhật)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "B5. Thực hành kỹ năng giáo dục ở trường THCS",
        "teacher": "TTBDNVSP, các trường THCS/THPT",
        "time": "Từ 16/11/2026 đến 20/12/2026",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "B6. Hướng dẫn công tác, thực tập 1,2 tại trường THCS/THPT",
        "teacher": "TS. Nguyễn Thanh Mỹ",
        "time": "Tối 26/12/2026 (Thứ 7)",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "B6. Thực tập sư phạm 1 ở Trường THCS/THPT",
        "teacher": "TTBDNVSP, các trường THCS/THPT",
        "time": "Từ 28/12/2026 đến 30/01/2027",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "B7. Thực tập sư phạm 2 ở Trường THCS/THPT",
        "teacher": "TTBDNVSP, các trường THCS/THPT",
        "time": "Từ 22/02/2027 đến 27/03/2027",
    },
    {
        "link": "https://teams.microsoft.com/meet/48777793098884?p=6rdZPwDv7DqXIqeTXS",
        "subject": "Thu hồ sơ thực tập",
        "teacher": "TTBDNVSP",
        "time": "Tháng 4/2027",
    },
]

CLASS_ID = "MANUAL-TA01-NVSPTH"  # ID đặc biệt cho lịch thủ công

def run():
    from api_client import parse_schedule_response, parse_time_field
    import database as db

    db.init_db()
    logger.info("DB initialized.")

    # Test parse trước khi import
    logger.info("=" * 60)
    logger.info("Preview parse kết quả:")
    problems = []
    for item in MANUAL_DATA:
        times = parse_time_field(item["time"])
        status = f"✅ {len(times)} ngày" if times else "❌ PARSE FAIL"
        logger.info("  %s | %s → %s", status, item["time"], [t["date"] for t in times])
        if not times:
            problems.append(item)

    if problems:
        logger.warning("\n⚠️  %d mục không parse được ngày:", len(problems))
        for p in problems:
            logger.warning("  - %r", p["time"])

    # Parse & upsert
    logger.info("=" * 60)
    events = parse_schedule_response(CLASS_ID, MANUAL_DATA)
    logger.info("Tổng events sau parse: %d", len(events))

    new_count = 0
    updated_count = 0
    for ev in events:
        is_new, is_changed = db.upsert_event(ev)
        if is_new:
            new_count += 1
        elif is_changed:
            updated_count += 1

    logger.info("✅ Import xong: %d mới, %d cập nhật, %d không đổi",
                new_count, updated_count, len(events) - new_count - updated_count)

    # In preview lịch đã lưu
    from notifier import build_schedule_message
    all_events = db.get_events_for_class(CLASS_ID)
    logger.info("\nPreview tin nhắn Telegram:\n%s",
                build_schedule_message(all_events, "📅 Lịch NVSP 2026-2027"))


if __name__ == "__main__":
    run()
