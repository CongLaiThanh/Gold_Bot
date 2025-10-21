import os
import re
import datetime
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# =============== CONFIG ===============
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

INTERVAL_SECONDS = 4*60*60  # 4 giờ


try:
    TZ_VN = ZoneInfo("Asia/Ho_Chi_Minh")
except Exception:
    TZ_VN = datetime.timezone(datetime.timedelta(hours=7))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

NUM_RE = re.compile(r"\d{1,3}\.\d{3}")  # bắt số kiểu 150.500, 148.000,...

def vn_now():
    return datetime.datetime.now(TZ_VN).strftime("%d/%m %H:%M")

def _fmt(val):
    if not val:
        return "—"
    return val.replace(",", ".")

# =============== LẤY ĐÚNG GIÁ TỪ THẺ "CARD" ===============
TITLE_RE = re.compile(r"^gi(a|á)\s*v(a|à)ng", re.I)

def _is_heading(tag):
    """Xác định các thẻ tiêu đề lớn như 'Giá vàng Miếng SJC', 'Giá vàng Nhẫn'."""
    if not getattr(tag, "name", None):
        return False
    if tag.name in ["h1", "h2", "h3"]:
        return bool(TITLE_RE.search(tag.get_text(strip=True)))
    return False

def _find_heading(soup, keywords):
    kws = [k.lower() for k in keywords]
    for tag in soup.find_all(_is_heading):
        t = tag.get_text(strip=True).lower()
        if any(k in t for k in kws):
            return tag
    return None

def _pick_numbers_between_headings(soup, keywords):
    """Tìm giá mua/bán giữa các tiêu đề (đúng từng card)."""
    head = _find_heading(soup, keywords)
    if not head:
        return None, None

    nums = []
    for el in head.next_elements:
        # Nếu gặp heading khác → dừng vì đã hết card
        if getattr(el, "name", None) and _is_heading(el) and el is not head:
            break
        text = getattr(el, "get_text", lambda *_: str(el))(" ", strip=True)
        found = NUM_RE.findall(text)
        if found:
            nums.extend(found)
            if len(nums) >= 2:
                return nums[0], nums[1]
    return None, None

# Fallback nếu card không lấy được
def _find_table_row(soup, keywords):
    for tr in soup.find_all("tr"):
        t = tr.get_text(" ", strip=True).lower()
        if any(k in t for k in keywords):
            nums = NUM_RE.findall(t)
            if len(nums) >= 2:
                return nums[0], nums[1]
    return None, None

async def fetch_giavang():
    async with httpx.AsyncClient(headers=HEADERS, timeout=20) as client:
        r = await client.get("https://giavang.org/")
        r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # Lấy Miếng SJC
    sjc_b, sjc_s = _pick_numbers_between_headings(soup, ["miếng sjc", "mieng sjc"])
    # Lấy Nhẫn SJC (tách riêng, không bị nhầm với Miếng)
    ring_b, ring_s = _pick_numbers_between_headings(soup, ["nhẫn sjc", "nhan sjc"])

    if not sjc_b:
        sjc_b, sjc_s = _find_table_row(soup, ["sjc"])
    if not ring_b:
        ring_b, ring_s = _find_table_row(soup, ["nhẫn", "nhan", "9999"])

    return {"sjc": (sjc_b, sjc_s), "ring": (ring_b, ring_s)}

def build_msg(data):
    sjc_b, sjc_s = data["sjc"]
    ring_b, ring_s = data["ring"]
    return (
        f"💰 Gold 5m Update — {vn_now()}\n"
        f"• Nguồn: giavang.org\n\n"
        f"🧈 SJC:    Mua {_fmt(sjc_b)} | Bán {_fmt(sjc_s)}\n"
        f"🟡 Nhẫn 9999:   Mua {_fmt(ring_b)} | Bán {_fmt(ring_s)}\n"
        f"🧑‍💻Người lập trình: Thanos Huang"
    )

# =============== BOT HANDLER ===============
async def job_send(ctx: ContextTypes.DEFAULT_TYPE):
    try:
        data = await fetch_giavang()
        await ctx.bot.send_message(TELEGRAM_CHAT_ID, build_msg(data))
    except Exception as e:
        print("[ERROR]", e)

async def cmd_start(update: Update, ctx):
    await update.message.reply_text("Bot vàng đang hoạt động!\n/now để xem giá ngay, /id để lấy chat_id của bạn.")

async def cmd_now(update: Update, ctx):
    data = await fetch_giavang()
    await update.message.reply_text(build_msg(data))

async def cmd_id(update: Update, ctx):
    await update.message.reply_text(f"Chat ID: {update.effective_chat.id}")

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("now", cmd_now))
    app.add_handler(CommandHandler("id", cmd_id))

    app.job_queue.run_repeating(job_send, interval=INTERVAL_SECONDS, first=5)

    print("✅ Bot Gold đang chạy...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
