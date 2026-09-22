import os
import json
import re
import html
import logging
import asyncio
import requests
from datetime import datetime, time, timedelta
from concurrent.futures import ThreadPoolExecutor
import pytz

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8974478810:AAEgxD-ikJrMwV_JSBJY9F45ppBhefoZjtg")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "-1003493006883")
GOOGLE_SCRIPT_URL = os.getenv(
    "GOOGLE_SCRIPT_URL",
    "https://script.google.com/macros/s/AKfycbzoS8NNwG2XyG-k6N19CHPzsZVb4mD9EJ9VFZoTxAFv_h-g2IpGNz6USFkrncQG2jmD/exec"
)

# Thread pool for blocking HTTP calls
executor = ThreadPoolExecutor(max_workers=4)

# ----------- APPS SCRIPT API (runs in thread pool) ----------- #

def _call_script(payload=None, params=None):
    """HTTP call to Apps Script. Run via executor."""
    url = GOOGLE_SCRIPT_URL
    if payload:
        resp = requests.post(url, json=payload, params=params, timeout=30)
    else:
        resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


async def call_script_async(payload=None, params=None):
    """Non-blocking wrapper."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, _call_script, payload, params)


def _parse_raw_to_records(raw_data):
    if not raw_data:
        return []
    headers = [str(h).strip() for h in raw_data[0]]
    records = []
    for row in raw_data[1:]:
        record = {}
        for i, h in enumerate(headers):
            if h:
                record[h] = row[i] if i < len(row) else ""
        records.append(record)
    return records


# ----------- HELPERS ----------- #

def find_user_id(row: dict) -> str:
    for k in ['User ID', 'UserId', 'user id', 'ID', 'id', 'Telegram ID', 'TelegramID', 'Member ID']:
        if k in row and row[k] is not None and str(row[k]).strip():
            return str(row[k]).strip()
    for k, v in row.items():
        n = re.sub(r'[^a-z0-9]', '', k.lower())
        if n in ['userid', 'id', 'telegramid'] and v is not None and str(v).strip():
            return str(v).strip()
    return ''

def find_name(row: dict) -> str:
    for k in ['Name', 'name', 'Full Name', 'fullname', 'Member Name']:
        if k in row and row[k] is not None and str(row[k]).strip():
            return str(row[k]).strip()
    return 'Unknown'

def esc(s): return html.escape(str(s or ''))


async def delete_later(bot, cid, mid, delay):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=cid, message_id=mid)
    except Exception:
        pass


# ----------- SCHEDULED JOBS ----------- #

async def job_morning(context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🌸 राधे राधे! आप सभी का स्वागत है। ☀️\n\n"
        "💚 Daily Attendance is now OPEN.\n\n"
        "⏰ Timing:\n🕕 06:00 AM – 10:00 AM (IST)\n\n"
        "📌 Mark your attendance by sending:\n👉🏻 /present\n\n"
        "📚 📚 Keep learning. Keep growing.\n✨ Have a wonderful day! 😍"
    )
    try:
        await context.bot.send_message(chat_id=CHAT_ID, text=msg)
    except Exception as e:
        logger.error(f"Morning announcement error: {e}")


def chunk_list(users, ctype):
    chunks, cur, length, cnt = [], [], 0, 1
    for u in users:
        name = esc(u.get('name') or u.get('Name') or 'Unknown')
        if ctype == 'leave':
            reason = esc(u.get('Reason') or u.get('reason') or 'No reason specified')
            line = f"  <b>{cnt}.</b> <code>{name}</code>\n     ┗ <i>{reason}</i>\n"
        else:
            line = f"  <b>{cnt}.</b> <code>{name}</code>\n"
        if length + len(line) > 3000:
            chunks.append("".join(cur)); cur = [line]; length = len(line)
        else:
            cur.append(line); length += len(line)
        cnt += 1
    if cur: chunks.append("".join(cur))
    return chunks


async def job_night(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Generating 9 PM report...")
    now = datetime.now(IST)
    today = now.strftime("%d-%m-%Y")
    yesterday = (now - timedelta(days=1)).strftime("%d-%m-%Y")
    day_before = (now - timedelta(days=2)).strftime("%d-%m-%Y")

    try:
        raw_members = await call_script_async(params={"action": "get_members"})
        members_list = _parse_raw_to_records(raw_members)
        unique = {}
        for m in members_list:
            uid = find_user_id(m)
            if uid and uid not in unique:
                unique[uid] = {'userId': uid, 'name': find_name(m)}
        members = list(unique.values())

        raw_att = await call_script_async()
        attendance = _parse_raw_to_records(raw_att)

        today_att = [r for r in attendance if str(r.get('Date') or '').strip() == today]
        present = [r for r in today_att if str(r.get('Status') or 'Present').strip() == 'Present']
        leave = [r for r in today_att if str(r.get('Status') or '').strip() == 'Leave']

        p_ids = {find_user_id(u) for u in present}
        l_ids = {find_user_id(u) for u in leave}
        absent = [m for m in members if m['userId'] not in p_ids and m['userId'] not in l_ids]

        warns = []
        for m in absent:
            mid = m['userId']
            y = any(str(r.get('Date') or '').strip() == yesterday and find_user_id(r) == mid for r in attendance)
            d = any(str(r.get('Date') or '').strip() == day_before and find_user_id(r) == mid for r in attendance)
            if not y and not d:
                warns.append(m['name'])

        div = "━━━━━━━━━━━━━━━━━━━━━━\n"
        msgs = []

        pc = chunk_list(present, 'present')
        m1 = f"<b>📊 DAILY ATTENDANCE REPORT</b>\n{div}📅 <b>Date:</b> <code>{today}</code>\n👥 <b>Total Members:</b> <code>{len(members)}</code>\n{div}✅ <b>Present Count:</b> <code>{len(present)}</code>\n\n"
        m1 += f"📝 <b>Present Members (Part 1):</b>\n{pc[0]}" if pc else "📝 <b>Present Members:</b>\n  <i>None</i>"
        msgs.append(m1)
        for i in range(1, len(pc)):
            msgs.append(f"📝 <b>Present Members (Part {i+1}):</b>\n{pc[i]}")

        lc = chunk_list(leave, 'leave')
        lm = f"🍂 <b>ON LEAVE COUNT: {len(leave)}</b>\n{div}"
        lm += f"📝 <b>Leave Registered:</b>\n{''.join(lc)}" if lc else "📝 <b>Leave Registered:</b>\n  <i>None</i>"
        msgs.append(lm)

        ac = chunk_list(absent, 'absent')
        am = f"❌ <b>ABSENT COUNT: {len(absent)}</b>\n{div}"
        am += f"📝 <b>Absent Members:</b>\n{''.join(ac)}" if ac else "📝 <b>Absent Members:</b>\n  <i>None</i>"
        am += "\n⚠️ <b>Consecutive Absentees (3+ days):</b>\n"
        if warns:
            for i, w in enumerate(warns, 1):
                am += f"  <b>{i}.</b> <code>{esc(w)}</code> ⚠️\n"
        else:
            am += "  <i>None</i>"
        msgs.append(am)

        for mt in msgs:
            await context.bot.send_message(chat_id=CHAT_ID, text=mt, parse_mode="HTML")
            await asyncio.sleep(0.3)

        logger.info("9 PM report sent.")
    except Exception as e:
        logger.error(f"Night report error: {e}", exc_info=True)


# ----------- COMMAND HANDLERS ----------- #

async def handle_admission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📄 Admission Form\n\n🔗 https://admissionverify.infinityfreeapp.com/\n\nPlease fill the form carefully. ✅"
    )


async def handle_mystatus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user or update.effective_chat
    chat = update.effective_chat
    if not user: return
    uid = str(user.id).strip()
    name = esc(getattr(user, 'first_name', None) or getattr(user, 'title', None) or 'Unknown')
    umid = update.message.message_id

    asyncio.create_task(delete_later(context.bot, chat.id, umid, 0))

    try:
        # Single call — fast
        result = await call_script_async(params={"action": "mystatus", "userId": uid})

        if isinstance(result, dict) and 'presentCount' in result:
            pc = result['presentCount']
            lc = result['leaveCount']
            tl = result['totalLogs']
            sc = result['streakCount']
            rate = round((pc / tl) * 100) if tl > 0 else 0
        else:
            # Fallback: parse raw
            rows = _parse_raw_to_records(result)
            user_rows = [r for r in rows if find_user_id(r) == uid]
            pc = sum(1 for r in user_rows if str(r.get('Status') or 'Present').strip() == 'Present')
            lc = sum(1 for r in user_rows if str(r.get('Status') or '').strip() == 'Leave')
            tl = len(user_rows)
            rate = round((pc / tl) * 100) if tl > 0 else 0
            sc = 0
            cd = datetime.now(IST)
            while True:
                ds = cd.strftime("%d-%m-%Y")
                pr = next((r for r in user_rows if str(r.get('Date') or '').strip() == ds), None)
                if pr and str(pr.get('Status') or 'Present').strip() == 'Present':
                    sc += 1; cd -= timedelta(days=1)
                else:
                    break

        badge = ""
        if sc >= 30: badge = " 👑 [Legend]"
        elif sc >= 15: badge = " 🌟 [Gold]"
        elif sc >= 7: badge = " 🔥 [Silver]"
        elif sc >= 3: badge = " ⚡ [Rising Star]"

        card = (
            f"<b>📊 ATTENDANCE SUMMARY: {name}</b>\n━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 <b>Total Logs:</b> <code>{tl}</code>\n"
            f"✅ <b>Present Days:</b> <code>{pc}</code>\n"
            f"🍂 <b>Leave Days:</b> <code>{lc}</code>\n"
            f"📈 <b>Attendance Rate:</b> <code>{rate}%</code>\n"
            f"🔥 <b>Current Streak:</b> <code>{sc} Days{badge}</code>"
        )
        sent = await context.bot.send_message(chat_id=chat.id, text=card, parse_mode="HTML")
        asyncio.create_task(delete_later(context.bot, chat.id, sent.message_id, 60))
    except Exception as e:
        logger.error(f"/mystatus error: {e}", exc_info=True)


async def handle_attendance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg: return
    chat = msg.chat
    if chat.type == "private": return

    text = msg.text or ""
    now = datetime.now(IST)
    hour = now.hour
    date_str = now.strftime("%d-%m-%Y")

    user = msg.from_user or msg.sender_chat
    if not user: return

    uid = str(user.id).strip()
    name = getattr(user, 'first_name', None) or getattr(user, 'title', None) or "Unknown"
    username = getattr(user, 'username', '') or ""
    umid = msg.message_id

    if not (6 <= hour < 10):
        sent = await msg.reply_text(
            "❌ Attendance/Leave is closed for today.\n\n⏰ Attendance timing: 6:00 AM – 10:00 AM\n\nPlease try again tomorrow morning."
        )
        asyncio.create_task(delete_later(context.bot, chat.id, sent.message_id, 15))
        asyncio.create_task(delete_later(context.bot, chat.id, umid, 15))
        return

    is_present = text.lower().startswith("/present")
    status = "Present" if is_present else "Leave"
    reason = ""
    if not is_present:
        parts = text.split(" ", 1)
        reason = parts[1].strip() if len(parts) > 1 and parts[1].strip() else "No reason specified"

    try:
        # ONE single call to Apps Script: check duplicate + calculate streak + append row
        result = await call_script_async(payload={
            "action": "mark_attendance",
            "date": date_str,
            "userId": uid,
            "name": name,
            "username": username,
            "status": status,
            "reason": reason
        })

        if result.get("duplicate"):
            dup_text = f"<b>✅ {esc(name)}, attendance/leave already marked</b>"
            sent = await msg.reply_text(dup_text, parse_mode="HTML")
            asyncio.create_task(delete_later(context.bot, chat.id, umid, 0))
            asyncio.create_task(delete_later(context.bot, chat.id, sent.message_id, 10))
            return

        streak = result.get("streak", 1)
        badge = ""
        if streak >= 30: badge = " 👑 [Legend]"
        elif streak >= 15: badge = " 🌟 [Gold]"
        elif streak >= 7: badge = " 🔥 [Silver]"
        elif streak >= 3: badge = " ⚡ [Rising Star]"

        if status == "Present":
            reply = f"<b>✅ {esc(name)}, attendance marked!</b>\n<code>🔥 {streak}-Day Streak!{badge}</code>"
        else:
            reply = f"<b>🍂 {esc(name)}, leave registered</b>"

        sent = await msg.reply_text(reply, parse_mode="HTML")
        asyncio.create_task(delete_later(context.bot, chat.id, umid, 0))
        asyncio.create_task(delete_later(context.bot, chat.id, sent.message_id, 30))

    except Exception as e:
        logger.error(f"Attendance error: {e}", exc_info=True)
        await msg.reply_text(f"⚠️ Attendance Error: {e}")


async def post_init(application):
    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook cleared.")
    except Exception as e:
        logger.warning(f"Webhook clear failed: {e}")


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    jq = app.job_queue

    jq.run_daily(job_morning, time=time(6, 0, tzinfo=IST), days=(0,1,2,3,4,5,6))
    jq.run_daily(job_night, time=time(21, 0, tzinfo=IST), days=(0,1,2,3,4,5,6))

    app.add_handler(MessageHandler(filters.Regex(re.compile(r"^/[Aa]dmission ?[Ff]orm$")), handle_admission))
    app.add_handler(MessageHandler(filters.Regex(re.compile(r"^/mystatus(@[a-zA-Z0-9_]+)?$")), handle_mystatus))
    app.add_handler(MessageHandler(filters.Regex(re.compile(r"^/present(@[a-zA-Z0-9_]+)?$|^/leave(@[a-zA-Z0-9_]+)?( .*)?$")), handle_attendance))

    logger.info("Bot started in polling mode...")
    app.run_polling()

if __name__ == "__main__":
    main()
