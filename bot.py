import os
import json
import base64
import re
import html
import logging
import asyncio
from datetime import datetime, time, timedelta
import pytz
import gspread
from google.oauth2.service_account import Credentials

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# Logging configuration
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Timezone
IST = pytz.timezone("Asia/Kolkata")

# Environment variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8974478810:AAEgxD-ikJrMwV_JSBJY9F45ppBhefoZjtg")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "-1003493006883")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "123XUsCdQRMTt_HtcHclEE8RRoFYoAl27KDBi1Ealn3E")
SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")

# Google Sheets Auth Helper
def get_gspread_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    if SERVICE_ACCOUNT_JSON:
        raw_json = SERVICE_ACCOUNT_JSON.strip()
        try:
            creds_dict = json.loads(raw_json)
        except Exception:
            # Try decoding base64 if user base64-encoded their credentials
            try:
                decoded = base64.b64decode(raw_json).decode("utf-8")
                creds_dict = json.loads(decoded)
            except Exception as err:
                logger.error(f"Failed to parse GOOGLE_SERVICE_ACCOUNT_JSON: {err}")
                raise err
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    elif os.path.exists(SERVICE_ACCOUNT_FILE):
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    else:
        raise ValueError(
            "Google Service Account credentials not found! Set GOOGLE_SERVICE_ACCOUNT_JSON env variable or place service_account.json file."
        )
    return gspread.authorize(creds)

def get_attendance_sheet():
    gc = get_gspread_client()
    doc = gc.open_by_key(SHEET_ID)
    # Sheet 1 or 'Admissions' (gid=0)
    return doc.get_worksheet(0)

def get_members_sheet():
    gc = get_gspread_client()
    doc = gc.open_by_key(SHEET_ID)
    try:
        return doc.worksheet("Members")
    except Exception:
        # Fallback to second sheet if name is different
        return doc.get_worksheet(1)

# Helper functions to normalize column lookups (matches n8n logic)
def find_user_id(row: dict) -> str:
    keys = ['User ID', 'UserId', 'user id', 'ID', 'id', 'Telegram ID', 'TelegramID', 'Member ID']
    for k in keys:
        if k in row and row[k] is not None and str(row[k]).strip() != '':
            return str(row[k]).strip()
    for k, v in row.items():
        normalized = re.sub(r'[^a-z0-9]', '', k.lower())
        if normalized in ['userid', 'id', 'telegramid']:
            if v is not None and str(v).strip() != '':
                return str(v).strip()
    return ''

def find_name(row: dict) -> str:
    keys = ['Name', 'name', 'Full Name', 'fullname', 'Member Name']
    for k in keys:
        if k in row and row[k] is not None and str(row[k]).strip() != '':
            return str(row[k]).strip()
    for k, v in row.items():
        normalized = re.sub(r'[^a-z0-9]', '', k.lower())
        if normalized in ['name', 'fullname', 'membername']:
            if v is not None and str(v).strip() != '':
                return str(v).strip()
    return 'Unknown'

def escape_html(str_val: str) -> str:
    return html.escape(str(str_val or ''))

# Message Auto-Delete Helper
async def delete_message_later(bot, chat_id: int | str, message_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"Deleted message {message_id} in {chat_id}")
    except Exception as e:
        logger.warning(f"Failed to delete message {message_id} in {chat_id}: {e}")

# ----------------- SCHEDULED JOBS ----------------- #

# 1. 06:00 AM Morning Announcement
async def job_morning_announcement(context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🌸 राधे राधे! आप सभी का स्वागत है। ☀️\n\n"
        "💚 Daily Attendance is now OPEN.\n\n"
        "⏰ Timing:\n"
        "🕕 06:00 AM – 10:00 AM (IST)\n\n"
        "📌 Mark your attendance by sending:\n"
        "👉🏻 /present\n\n"
        "📚 📚 Keep learning. Keep growing.\n"
        "✨ Have a wonderful day! 😍"
    )
    try:
        await context.bot.send_message(chat_id=CHAT_ID, text=msg)
        logger.info("Sent morning attendance announcement.")
    except Exception as e:
        logger.error(f"Error sending morning announcement: {e}")

# 2. 09:00 PM Daily Report
def chunk_list(users: list, chunk_type: str) -> list[str]:
    chunks = []
    current_chunk = []
    current_length = 0
    counter = 1

    for user in users:
        name = escape_html(user.get('name') or user.get('Name') or 'Unknown')
        if chunk_type == 'leave':
            reason = escape_html(user.get('Reason') or user.get('reason') or 'No reason specified')
            line = f"  <b>{counter}.</b> <code>{name}</code>\n     ┗ <i>{reason}</i>\n"
        else:
            line = f"  <b>{counter}.</b> <code>{name}</code>\n"

        if current_length + len(line) > 3000:
            chunks.append("".join(current_chunk))
            current_chunk = [line]
            current_length = len(line)
        else:
            current_chunk.append(line)
            current_length += len(line)
        counter += 1

    if current_chunk:
        chunks.append("".join(current_chunk))
    return chunks

def chunk_warnings(warning_list: list[str]) -> list[str]:
    chunks = []
    current_chunk = []
    current_length = 0
    counter = 1

    for name in warning_list:
        line = f"  <b>{counter}.</b> <code>{escape_html(name)}</code> ⚠️\n"
        if current_length + len(line) > 3000:
            chunks.append("".join(current_chunk))
            current_chunk = [line]
            current_length = len(line)
        else:
            current_chunk.append(line)
            current_length += len(line)
        counter += 1

    if current_chunk:
        chunks.append("".join(current_chunk))
    return chunks

async def job_night_report(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Generating 9 PM Attendance Report...")
    now_ist = datetime.now(IST)
    today = now_ist.strftime("%d-%m-%Y")
    yesterday = (now_ist - timedelta(days=1)).strftime("%d-%m-%Y")
    day_before = (now_ist - timedelta(days=2)).strftime("%d-%m-%Y")

    try:
        # Fetch members
        members_sheet = get_members_sheet()
        raw_members = members_sheet.get_all_records()
        unique_members_map = {}
        for m in raw_members:
            u_id = find_user_id(m)
            if u_id and u_id not in unique_members_map:
                unique_members_map[u_id] = {
                    'userId': u_id,
                    'name': find_name(m),
                    'original': m
                }
        members = list(unique_members_map.values())
        total_members_count = len(members)

        # Fetch attendance
        att_sheet = get_attendance_sheet()
        raw_att = att_sheet.get_all_records()
        unique_att_map = {}
        for a in raw_att:
            u_id = find_user_id(a)
            date_str = str(a.get('Date') or a.get('date') or '').strip()
            key = f"{u_id}_{date_str}"
            if u_id and date_str and key not in unique_att_map:
                unique_att_map[key] = a
        attendance = list(unique_att_map.values())

        # Today's attendance filter
        today_attendance = [
            r for r in attendance 
            if str(r.get('Date') or r.get('date') or '').strip() == today
        ]

        present_users = [
            r for r in today_attendance 
            if str(r.get('Status') or r.get('status') or 'Present').strip() == 'Present'
        ]
        leave_users = [
            r for r in today_attendance 
            if str(r.get('Status') or r.get('status') or '').strip() == 'Leave'
        ]

        present_user_ids = {find_user_id(u) for u in present_users}
        leave_user_ids = {find_user_id(u) for u in leave_users}

        absent_users = [
            m for m in members 
            if m['userId'] not in present_user_ids and m['userId'] not in leave_user_ids
        ]

        warnings = []
        for m in absent_users:
            m_id = m['userId']
            attended_yesterday = any(
                str(r.get('Date') or r.get('date') or '').strip() == yesterday and find_user_id(r) == m_id
                for r in attendance
            )
            attended_day_before = any(
                str(r.get('Date') or r.get('date') or '').strip() == day_before and find_user_id(r) == m_id
                for r in attendance
            )
            if not attended_yesterday and not attended_day_before:
                warnings.append(m['name'])

        present_chunks = chunk_list(present_users, 'present')
        leave_chunks = chunk_list(leave_users, 'leave')
        absent_chunks = chunk_list(absent_users, 'absent')
        warning_chunks = chunk_warnings(warnings)

        messages = []
        divider = "━━━━━━━━━━━━━━━━━━━━━━\n"

        msg1 = (
            f"<b>📊 DAILY ATTENDANCE REPORT</b>\n{divider}"
            f"📅 <b>Date:</b> <code>{today}</code>\n"
            f"👥 <b>Total Members:</b> <code>{total_members_count}</code>\n{divider}"
            f"✅ <b>Present Count:</b> <code>{len(present_users)}</code>\n\n"
        )
        if present_chunks:
            msg1 += f"📝 <b>Present Members (Part 1):</b>\n{present_chunks[0]}"
        else:
            msg1 += "📝 <b>Present Members:</b>\n  <i>None</i>"
        messages.append(msg1)

        for i in range(1, len(present_chunks)):
            messages.append(f"📝 <b>Present Members (Part {i + 1}):</b>\n{present_chunks[i]}")

        leave_msg = f"🍂 <b>ON LEAVE COUNT: {len(leave_users)}</b>\n{divider}"
        if leave_chunks:
            leave_msg += f"📝 <b>Leave Registered:</b>\n{''.join(leave_chunks)}"
        else:
            leave_msg += "📝 <b>Leave Registered:</b>\n  <i>None</i>"
        messages.append(leave_msg)

        absent_msg = f"❌ <b>ABSENT COUNT: {len(absent_users)}</b>\n{divider}"
        if absent_chunks:
            absent_msg += f"📝 <b>Absent Members:</b>\n{''.join(absent_chunks)}"
        else:
            absent_msg += "📝 <b>Absent Members:</b>\n  <i>None</i>"

        absent_msg += "\n⚠️ <b>Consecutive Absentees (3+ days):</b>\n"
        if warning_chunks:
            absent_msg += "".join(warning_chunks)
        else:
            absent_msg += "  <i>None</i>"
        messages.append(absent_msg)

        for msg_text in messages:
            await context.bot.send_message(chat_id=CHAT_ID, text=msg_text, parse_mode="HTML")
            await asyncio.sleep(0.5)

        logger.info("Successfully sent 9 PM report.")
    except Exception as e:
        logger.error(f"Error generating 9 PM report: {e}")


# ----------------- COMMAND HANDLERS ----------------- #

# 1. /admissionform
async def handle_admission_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📄 Admission Form\n\n"
        "🔗 https://admissionverify.infinityfreeapp.com/\n\n"
        "Please fill the form carefully. ✅"
    )
    await update.message.reply_text(text)

# 2. /mystatus
async def handle_my_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    user_id = str(user.id).strip()
    name = escape_html(user.first_name or 'Unknown')
    user_msg_id = update.message.message_id

    # Delete user command immediately
    asyncio.create_task(delete_message_later(context.bot, chat.id, user_msg_id, 0))

    try:
        att_sheet = get_attendance_sheet()
        all_rows = att_sheet.get_all_records()
        user_rows = [r for r in all_rows if find_user_id(r) == user_id]

        present_count = sum(
            1 for r in user_rows 
            if str(r.get('Status') or r.get('status') or 'Present').strip() == 'Present'
        )
        leave_count = sum(
            1 for r in user_rows 
            if str(r.get('Status') or r.get('status') or '').strip() == 'Leave'
        )
        total_logs = len(user_rows)
        attendance_rate = round((present_count / total_logs) * 100) if total_logs > 0 else 0

        # Calculate Streak
        streak_count = 0
        check_date = datetime.now(IST)
        while True:
            date_str = check_date.strftime("%d-%m-%Y")
            past_record = next(
                (r for r in user_rows if str(r.get('Date') or r.get('date') or '').strip() == date_str),
                None
            )
            if past_record and str(past_record.get('Status') or past_record.get('status') or 'Present').strip() == 'Present':
                streak_count += 1
                check_date -= timedelta(days=1)
            else:
                break

        badge = ""
        if streak_count >= 30:
            badge = " 👑 [Legend]"
        elif streak_count >= 15:
            badge = " 🌟 [Gold]"
        elif streak_count >= 7:
            badge = " 🔥 [Silver]"
        elif streak_count >= 3:
            badge = " ⚡ [Rising Star]"

        card_text = (
            f"<b>📊 ATTENDANCE SUMMARY: {name}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 <b>Total Logs:</b> <code>{total_logs}</code>\n"
            f"✅ <b>Present Days:</b> <code>{present_count}</code>\n"
            f"🍂 <b>Leave Days:</b> <code>{leave_count}</code>\n"
            f"📈 <b>Attendance Rate:</b> <code>{attendance_rate}%</code>\n"
            f"🔥 <b>Current Streak:</b> <code>{streak_count} Days{badge}</code>"
        )

        sent_msg = await context.bot.send_message(chat_id=chat.id, text=card_text, parse_mode="HTML")
        # Auto delete status card after 60s
        asyncio.create_task(delete_message_later(context.bot, chat.id, sent_msg.message_id, 60))

    except Exception as e:
        logger.error(f"Error handling /mystatus: {e}")

# 3. /present & /leave
async def handle_attendance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    chat = msg.chat
    # Ignore private chats for /present & /leave
    if chat.type == "private":
        return

    text = msg.text or ""
    now_ist = datetime.now(IST)
    hour = now_ist.hour
    date_str = now_ist.strftime("%d-%m-%Y")
    user = msg.from_user
    user_id = str(user.id).strip()
    name = user.first_name or "Unknown"
    username = user.username or ""

    user_msg_id = msg.message_id

    # Check timing window: 6 AM to 10 AM (6 <= hour < 10)
    if not (6 <= hour < 10):
        closed_text = (
            "❌ Attendance/Leave is closed for today.\n\n"
            "⏰ Attendance timing: 6:00 AM – 10:00 AM\n\n"
            "Please try again tomorrow morning."
        )
        sent_msg = await msg.reply_text(closed_text)
        # Delete closed notice and user command after 15 seconds
        asyncio.create_task(delete_message_later(context.bot, chat.id, sent_msg.message_id, 15))
        asyncio.create_task(delete_message_later(context.bot, chat.id, user_msg_id, 15))
        return

    # Parse command details
    is_present = text.lower().startswith("/present")
    status = "Present" if is_present else "Leave"

    reason = ""
    if not is_present:
        parts = text.split(" ", 1)
        reason = parts[1].strip() if len(parts) > 1 and parts[1].strip() else "No reason specified"

    try:
        att_sheet = get_attendance_sheet()
        all_rows = att_sheet.get_all_records()

        # Check duplicate for today
        already = next(
            (
                r for r in all_rows 
                if str(r.get('Date') or r.get('date') or '').strip() == date_str 
                and find_user_id(r) == user_id
            ),
            None
        )

        if already:
            dup_text = f"<b>✅ {escape_html(name)}, attendance/leave already marked</b>"
            sent_msg = await msg.reply_text(dup_text, parse_mode="HTML")
            # Delete user command immediately
            asyncio.create_task(delete_message_later(context.bot, chat.id, user_msg_id, 0))
            # Delete duplicate message after 10s
            asyncio.create_task(delete_message_later(context.bot, chat.id, sent_msg.message_id, 10))
            return

        # Calculate streak if present
        streak_count = 0
        badge = ""
        if status == "Present":
            streak_count = 1
            check_date = now_ist - timedelta(days=1)
            while True:
                d_str = check_date.strftime("%d-%m-%Y")
                past_record = next(
                    (
                        r for r in all_rows 
                        if find_user_id(r) == user_id 
                        and str(r.get('Date') or r.get('date') or '').strip() == d_str
                    ),
                    None
                )
                if past_record and str(past_record.get('Status') or past_record.get('status') or 'Present').strip() == 'Present':
                    streak_count += 1
                    check_date -= timedelta(days=1)
                else:
                    break

            if streak_count >= 30:
                badge = " 👑 [Legend]"
            elif streak_count >= 15:
                badge = " 🌟 [Gold]"
            elif streak_count >= 7:
                badge = " 🔥 [Silver]"
            elif streak_count >= 3:
                badge = " ⚡ [Rising Star]"

            reply_text = f"<b>✅ {escape_html(name)}, attendance marked!</b>\n<code>🔥 {streak_count}-Day Streak!{badge}</code>"
        else:
            reply_text = f"<b>🍂 {escape_html(name)}, leave registered</b>"

        # Append row to Google Sheets
        row_data = [date_str, user_id, name, username, status, reason]
        att_sheet.append_row(row_data)

        # Send confirmation message
        sent_msg = await msg.reply_text(reply_text, parse_mode="HTML")

        # Delete user command immediately
        asyncio.create_task(delete_message_later(context.bot, chat.id, user_msg_id, 0))
        # Delete confirmation message after 30s
        asyncio.create_task(delete_message_later(context.bot, chat.id, sent_msg.message_id, 30))

    except Exception as e:
        logger.error(f"Error recording attendance: {e}")
        await msg.reply_text("⚠️ An error occurred while processing attendance.")

async def post_init(application):
    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
        logger.info("Cleared existing Telegram webhooks.")
    except Exception as e:
        logger.warning(f"Could not clear webhook: {e}")

# Main function
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    # Job Queue for scheduled crons
    job_queue = app.job_queue

    # 06:00 AM IST daily (06:00)
    job_queue.run_daily(
        job_morning_announcement,
        time=time(6, 0, tzinfo=IST),
        days=(0, 1, 2, 3, 4, 5, 6),
    )

    # 21:00 PM IST daily (21:00)
    job_queue.run_daily(
        job_night_report,
        time=time(21, 0, tzinfo=IST),
        days=(0, 1, 2, 3, 4, 5, 6),
    )

    # Handlers
    admission_regex = re.compile(r"^/[Aa]dmission ?[Ff]orm$")
    mystatus_regex = re.compile(r"^/mystatus(@[a_zA_Z0-9_]+)?$")
    attendance_regex = re.compile(r"^/present(@[a_zA_Z0-9_]+)?$|^/leave(@[a_zA_Z0-9_]+)?( .*)?$")

    app.add_handler(MessageHandler(filters.Regex(admission_regex), handle_admission_form))
    app.add_handler(MessageHandler(filters.Regex(mystatus_regex), handle_my_status))
    app.add_handler(MessageHandler(filters.Regex(attendance_regex), handle_attendance))

    logger.info("Bot started successfully in polling mode...")
    app.run_polling()

if __name__ == "__main__":
    main()

