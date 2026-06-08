# 🤖 VinhUni Schedule Telegram Bot

Bot Telegram tự động **đồng bộ lịch học** từ hệ thống VinhUni, gửi **nhắc nhở 24h trước** mỗi buổi học, và đẩy lên **Google Calendar**. Hỗ trợ deploy trên **Coolify** qua Docker.
Bot chạy theo mô hình **cá nhân**: chỉ owner mới dùng được lệnh và nhận thông báo.

---

## ✨ Tính năng

| Tính năng | Mô tả |
|---|---|
| 🔄 **Tự động đồng bộ** | Fetch lịch học lúc **0h, 7h, 12h, 17h** hàng ngày |
| 🆕 **Phát hiện thay đổi** | So sánh từng buổi học, thông báo ngay khi lịch mới/thay đổi |
| ⏰ **Nhắc nhở tự động** | Gửi nhắc nhở **24h trước** mỗi buổi học |
| 🔗 **Link Teams** | Hiển thị link Teams trong thông báo |
| 📅 **Google Calendar** | Đồng bộ lên Google Calendar (tuỳ chọn) |
| 🐳 **Docker ready** | Deploy dễ dàng trên Coolify/VPS |

---

## 🚀 Cài đặt nhanh

### 1. Clone & cấu hình

```bash
git clone <repo-url>
cd telegram-schedule-bot
cp .env.example .env
```

Chỉnh sửa `.env`:
```env
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_OWNER_USERNAME=your_telegram_username
CLASS_IDS=TA01.NVSPTH.QY01,TA01-NVSPGVTHCS.THPT-QY01
```

`TELEGRAM_OWNER_USERNAME` là tuỳ chọn nhưng nên đặt trên server. Nếu để trống, người đầu tiên nhắn `/start` cho bot sẽ trở thành owner.

### 2. Chạy với Docker Compose

```bash
docker compose up -d
docker compose logs -f
```

---

## 📱 Lệnh Telegram

| Lệnh | Mô tả |
|---|---|
| `/start` | Khởi động & xem hướng dẫn |
| `/lich` | Lịch học 7 ngày tới |
| `/lich_thang` | Lịch học tháng này |
| `/hom_nay` | Lịch học hôm nay |
| `/ngay_mai` | Lịch học ngày mai |
| `/sync` | Đồng bộ lịch ngay lập tức |
| `/status` | Trạng thái bot & thống kê |
| `/dang_ky` | Đăng ký nhận thông báo |
| `/huy` | Hủy nhận thông báo |
| `/wc` | Lịch World Cup 2026 hôm nay |
| `/wc live` | Trận World Cup đang diễn ra |
| `/wc bang` | Bảng xếp hạng World Cup |
| `/wchelp` | Trợ giúp module World Cup |

---

## ⚽ World Cup 2026

Module World Cup dùng ESPN public endpoints nên không cần token riêng. Các lệnh `/wc`, `/wc live`, `/wc ket_qua`, `/wc DD-MM`, `/wc <đội>` và `/wc bang` hoạt động qua cùng bot cá nhân.

Tất cả lịch và lệnh theo ngày đều dùng ngày giờ Việt Nam. Ví dụ trận khai mạc diễn ra 19:00 UTC ngày 11/06/2026 sẽ hiển thị là 02:00 ngày 12/06/2026 theo giờ Việt Nam, và nằm trong `/wc 12-06`.

```env
WC_ENABLED=true
WC_DAILY_NOTIFY_HOUR=0
WC_LIVE_CHECK_MINUTES=60
```

## ⏰ Giờ học mặc định

| Buổi | Giờ bắt đầu | Kết thúc |
|---|---|---|
| ☀️ Sáng | 08:00 | 10:00 |
| 🌤 Chiều | 14:00 | 16:00 |
| 🌙 Tối | 19:00 | 21:00 |

*(Thời gian mặc định nếu API không trả về giờ cụ thể)*

---

## 📅 Google Calendar (tuỳ chọn)

### Bước 1: Tạo credentials

1. Vào [Google Cloud Console](https://console.cloud.google.com/)
2. Tạo project mới → Enable **Google Calendar API**
3. Tạo **OAuth 2.0 Client ID** (Desktop App)
4. Tải file `credentials.json`

### Bước 2: Đặt credentials

```bash
mkdir credentials
cp credentials.json credentials/
```

### Bước 3: Lần đầu xác thực (chạy local)

```bash
pip install -r requirements.txt
GOOGLE_CALENDAR_ENABLED=true python -c "from calendar_sync import _get_calendar_service; _get_calendar_service()"
```

Trình duyệt sẽ mở → đăng nhập Google → file `data/token.json` được tạo.

### Bước 4: Bật trong `.env`

```env
GOOGLE_CALENDAR_ENABLED=true
```

---

## 🐳 Deploy lên Coolify

### Phương án 1: GitHub repo (khuyến nghị)

1. Push code lên GitHub (đảm bảo `.gitignore` loại bỏ `.env`, `credentials/`, `data/`)
2. Vào Coolify → **New Resource** → **Application**
3. Chọn GitHub repo → Build Pack: **Dockerfile**
4. Tab **Environment Variables** → thêm tất cả biến từ `.env.example`
5. Tab **Storages** → thêm persistent volume: `/app/data`
6. **Deploy**
7. Mở Telegram, nhắn `/start` cho bot để claim owner nếu DB chưa có owner

Biến bắt buộc trên Coolify:

```env
TELEGRAM_BOT_TOKEN=123456789:AA...
CLASS_IDS=TA01.NVSPTH.QY01,TA01-NVSPGVTHCS.THPT-QY01
DATABASE_PATH=/app/data/schedule.db
TIMEZONE=Asia/Ho_Chi_Minh
```

Biến khuyến nghị cho bot cá nhân:

```env
TELEGRAM_OWNER_USERNAME=username_cua_ban
```

Nếu log báo `Telegram bot token invalid`, kiểm tra lại tên biến là `TELEGRAM_BOT_TOKEN` và giá trị token lấy trực tiếp từ @BotFather, không để `your_bot_token_here`.

### Phương án 2: Docker image trực tiếp

```bash
# Build
docker build -t vinhuni-bot .

# Run
docker run -d \
  --name vinhuni-bot \
  --restart unless-stopped \
  -e TELEGRAM_BOT_TOKEN=xxx \
  -e TELEGRAM_OWNER_USERNAME=your_telegram_username \
  -e CLASS_IDS=TA01.NVSPTH.QY01 \
  -v $(pwd)/data:/app/data \
  vinhuni-bot
```

---

## 📁 Cấu trúc project

```
telegram/
├── main.py            # Entry point, scheduler
├── handlers.py        # Telegram command handlers
├── api_client.py      # Fetch & parse lịch học từ API
├── sync_service.py    # Orchestrate sync + notify
├── database.py        # SQLite storage
├── notifier.py        # Format tin nhắn Telegram
├── calendar_sync.py   # Google Calendar integration
├── config.py          # Cấu hình từ env vars
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

---

## 🔧 Biến môi trường

| Biến | Mặc định | Mô tả |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | *bắt buộc* | Token từ @BotFather |
| `TELEGRAM_OWNER_USERNAME` | trống | Username được phép claim bot; để trống thì user đầu tiên `/start` sẽ claim |
| `CLASS_IDS` | `TA01.NVSPTH.QY01,...` | Danh sách lớp học |
| `SYNC_HOURS` | `0,7,12,17` | Giờ đồng bộ hàng ngày |
| `NOTIFY_BEFORE_HOURS` | `24` | Nhắc trước N giờ |
| `TIMEZONE` | `Asia/Ho_Chi_Minh` | Múi giờ |
| `WC_ENABLED` | `true` | Bật module World Cup 2026 |
| `WC_DAILY_NOTIFY_HOUR` | `0` | Giờ gửi lịch trận hằng ngày |
| `WC_LIVE_CHECK_MINUTES` | `60` | Chu kỳ kiểm tra kết quả live; `0` để tắt |
| `GOOGLE_CALENDAR_ENABLED` | `false` | Bật Google Calendar |
| `GOOGLE_CALENDAR_ID` | `primary` | ID calendar đích |
| `LOG_LEVEL` | `INFO` | Mức log |
