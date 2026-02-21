import os
import logging
import httpx
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

# ----------------- Config -----------------
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")

# Comma-separated admin IDs: "12345,67890"
ADMIN_IDS = [
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
]

PER_PAGE_ZONES = 25
PER_PAGE_RECORDS = 50

# Conversation States
WAITING_EDIT_CONTENT = 1
WAITING_NEW_RECORD_DATA = 2

# ----------------- Logging -----------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ----------------- Helpers -----------------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def trunc(s: str, n: int = 55) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def cb_home() -> str:
    return "home"


def cb_zones(page: int = 1) -> str:
    return f"zones:{page}"


def cb_records(zone_id: str, page: int = 1) -> str:
    return f"recs:{zone_id}:{page}"


def cb_record(record_id: str) -> str:
    return f"rec:{record_id}"


# ----------------- Cloudflare API -----------------
async def cf_request(method: str, endpoint: str, json_data=None):
    url = f"https://api.cloudflare.com/client/v4{endpoint}"
    headers = {
        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json",
    }
    timeout = httpx.Timeout(15.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            if method == "GET":
                resp = await client.get(url, headers=headers)
            elif method == "POST":
                resp = await client.post(url, headers=headers, json=json_data)
            elif method == "PUT":
                resp = await client.put(url, headers=headers, json=json_data)
            elif method == "PATCH":
                resp = await client.patch(url, headers=headers, json=json_data)
            elif method == "DELETE":
                resp = await client.delete(url, headers=headers)
            else:
                return {"success": False, "errors": [{"message": "Invalid method"}]}

            return resp.json()
        except Exception as e:
            logger.error(f"Cloudflare API Error: {e}")
            return {"success": False, "errors": [{"message": str(e)}]}


async def get_zones_page(page: int = 1, per_page: int = PER_PAGE_ZONES):
    res = await cf_request("GET", f"/zones?page={page}&per_page={per_page}")
    return res.get("result", []), res.get("result_info", {}), res.get("success", False), res.get("errors", [])


async def get_records_page(zone_id: str, page: int = 1, per_page: int = PER_PAGE_RECORDS):
    res = await cf_request("GET", f"/zones/{zone_id}/dns_records?page={page}&per_page={per_page}")
    return res.get("result", []), res.get("result_info", {}), res.get("success", False), res.get("errors", [])


async def get_single_record(zone_id: str, record_id: str):
    res = await cf_request("GET", f"/zones/{zone_id}/dns_records/{record_id}")
    return res.get("result", None), res.get("success", False), res.get("errors", [])


async def update_dns_record(zone_id: str, record_id: str, data: dict):
    res = await cf_request("PUT", f"/zones/{zone_id}/dns_records/{record_id}", json_data=data)
    return res.get("success", False), res.get("errors", [])


async def toggle_proxy_status(zone_id: str, record_id: str, new_status: bool):
    payload = {"proxied": new_status}
    res = await cf_request("PATCH", f"/zones/{zone_id}/dns_records/{record_id}", json_data=payload)
    return res.get("success", False), res.get("errors", [])


async def create_dns_record(zone_id: str, rtype: str, name: str, content: str):
    payload = {
        "type": rtype,
        "name": name,
        "content": content,
        "proxied": False,
        "ttl": 1,
    }
    res = await cf_request("POST", f"/zones/{zone_id}/dns_records", json_data=payload)
    return res.get("success", False), res.get("errors", [])


async def delete_dns_record(zone_id: str, record_id: str):
    res = await cf_request("DELETE", f"/zones/{zone_id}/dns_records/{record_id}")
    return res.get("success", False), res.get("errors", [])


# ----------------- UI Screens -----------------
async def show_home(update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False):
    keyboard = [
        [InlineKeyboardButton("☁️ Manage Domains", callback_data=cb_zones(1))]
    ]
    text = "**Cloudflare Management Panel**\n\nSelect an option:"
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def show_zones(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    query = update.callback_query
    zones, info, ok, errs = await get_zones_page(page=page)
    if not ok:
        msg = (errs[0]["message"] if errs else "Unknown error")
        await query.edit_message_text(
            f"❌ Cloudflare error:\n`{msg}`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data=cb_home())]]),
            parse_mode="Markdown",
        )
        return

    if not zones:
        await query.edit_message_text(
            "❌ No zones found.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data=cb_home())]]),
        )
        return

    keyboard = []
    for z in zones:
        keyboard.append([InlineKeyboardButton(f"🌐 {trunc(z['name'], 60)}", callback_data=cb_records(z["id"], 1))])

    # Pagination
    nav = []
    total_pages = info.get("total_pages", 1)
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=cb_zones(page - 1)))
    if page < total_pages:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=cb_zones(page + 1)))
    if nav:
        keyboard.append(nav)

    keyboard.append([InlineKeyboardButton("🏠 Home", callback_data=cb_home())])

    await query.edit_message_text("✅ Select a Domain:", reply_markup=InlineKeyboardMarkup(keyboard))


async def show_records(update: Update, context: ContextTypes.DEFAULT_TYPE, zone_id: str, page: int = 1):
    query = update.callback_query
    context.user_data["current_zone_id"] = zone_id
    context.user_data["current_records_page"] = page

    records, info, ok, errs = await get_records_page(zone_id=zone_id, page=page)
    if not ok:
        msg = (errs[0]["message"] if errs else "Unknown error")
        await query.edit_message_text(
            f"❌ Cloudflare error:\n`{msg}`",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back", callback_data=cb_zones(1))],
                [InlineKeyboardButton("🏠 Home", callback_data=cb_home())],
            ]),
            parse_mode="Markdown",
        )
        return

    keyboard = []
    for rec in records:
        # نشان دادن A/AAAA/CNAME (قابل پروکسی)
        if rec.get("type") in ["A", "AAAA", "CNAME"]:
            icon = "☁️" if rec.get("proxied") else "⚪️"
            btn_text = trunc(f"{icon} {rec.get('name')} ({rec.get('type')}) -> {rec.get('content')}", 60)
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=cb_record(rec["id"]))])

    # ابزارها
    keyboard.append([InlineKeyboardButton("➕ New Record", callback_data="newrec:menu")])

    # Pagination
    nav = []
    total_pages = info.get("total_pages", 1)
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=cb_records(zone_id, page - 1)))
    if page < total_pages:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=cb_records(zone_id, page + 1)))
    if nav:
        keyboard.append(nav)

    keyboard.append([
        InlineKeyboardButton("⬅️ Back", callback_data=cb_zones(1)),
        InlineKeyboardButton("🏠 Home", callback_data=cb_home()),
    ])

    await query.edit_message_text("📌 DNS Records:", reply_markup=InlineKeyboardMarkup(keyboard))


async def show_record_details(update: Update, context: ContextTypes.DEFAULT_TYPE, record_id: str):
    query = update.callback_query
    zone_id = context.user_data.get("current_zone_id")
    if not zone_id:
        await query.edit_message_text("❌ No zone selected.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data=cb_home())]]))
        return

    record, ok, errs = await get_single_record(zone_id, record_id)
    if not ok or not record:
        msg = (errs[0]["message"] if errs else "Record not found")
        await query.edit_message_text(
            f"❌ {msg}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=cb_records(zone_id, context.user_data.get('current_records_page', 1)))]])
        )
        return

    context.user_data["current_record_id"] = record_id
    context.user_data["current_record_data"] = record

    status_icon = "✅ Proxied" if record.get("proxied") else "❌ DNS Only"
    proxiable = record.get("proxiable", False)

    details = (
        f"**Record:** `{record.get('name')}`\n"
        f"**Type:** `{record.get('type')}`\n"
        f"**Content:** `{record.get('content')}`\n"
        f"**Proxy:** {status_icon}\n"
        f"**Proxiable:** `{'yes' if proxiable else 'no'}`\n"
    )

    keyboard = [
        [InlineKeyboardButton("✏️ Edit Content", callback_data="action:edit")],
    ]

    # Toggle فقط وقتی CF اجازه بده
    if proxiable and record.get("type") in ["A", "AAAA", "CNAME"]:
        keyboard.append([InlineKeyboardButton("☁️ Toggle Proxy", callback_data="action:toggle")])

    keyboard.append([InlineKeyboardButton("🗑 Delete Record", callback_data="action:confirm_delete")])

    back_page = context.user_data.get("current_records_page", 1)
    keyboard.append([
        InlineKeyboardButton("⬅️ Back", callback_data=cb_records(zone_id, back_page)),
        InlineKeyboardButton("🏠 Home", callback_data=cb_home()),
    ])

    await query.edit_message_text(details, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


# ----------------- Telegram Handlers -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await show_home(update, context, edit=False)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Access Denied", show_alert=True)
        return

    await query.answer()
    data = query.data

    # Home
    if data == cb_home():
        await show_home(update, context, edit=True)
        return

    # Zones pagination: zones:page
    if data.startswith("zones:"):
        page = int(data.split(":")[1])
        await show_zones(update, context, page=page)
        return

    # Records pagination: recs:zone_id:page
    if data.startswith("recs:"):
        _, zone_id, page = data.split(":")
        await show_records(update, context, zone_id=zone_id, page=int(page))
        return

    # Record details: rec:record_id
    if data.startswith("rec:"):
        record_id = data.split(":")[1]
        await show_record_details(update, context, record_id=record_id)
        return

    # New record menu
    if data == "newrec:menu":
        zone_id = context.user_data.get("current_zone_id")
        keyboard = [
            [InlineKeyboardButton("A", callback_data="newrec:type:A"),
             InlineKeyboardButton("AAAA", callback_data="newrec:type:AAAA")],
            [InlineKeyboardButton("CNAME", callback_data="newrec:type:CNAME"),
             InlineKeyboardButton("TXT", callback_data="newrec:type:TXT")],
            [
                InlineKeyboardButton("⬅️ Back", callback_data=cb_records(zone_id, context.user_data.get("current_records_page", 1))),
                InlineKeyboardButton("🏠 Home", callback_data=cb_home()),
            ],
        ]
        await query.edit_message_text("➕ Select record type:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("newrec:type:"):
        rtype = data.split(":")[2]
        context.user_data["state"] = WAITING_NEW_RECORD_DATA
        context.user_data["new_record_type"] = rtype
        await query.edit_message_text(
            "✍️ Send `name content` (with a space).\n\n"
            "Examples:\n"
            "- `vpn 1.2.3.4` (A)\n"
            "- `app target.example.com` (CNAME)\n",
            parse_mode="Markdown",
        )
        return

    # Edit content
    if data == "action:edit":
        context.user_data["state"] = WAITING_EDIT_CONTENT
        await query.edit_message_text("✍️ Send the **new Content**:", parse_mode="Markdown")
        return

    # Toggle proxy
    if data == "action:toggle":
        zone_id = context.user_data.get("current_zone_id")
        record_id = context.user_data.get("current_record_id")
        record_data = context.user_data.get("current_record_data") or {}

        # اگر proxiable نباشه، جلوش رو بگیر
        if not record_data.get("proxiable", False):
            await query.edit_message_text(
                "⚠️ This record is not proxiable on Cloudflare.\nSo proxy cannot be toggled.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back to Record", callback_data=cb_record(record_id))],
                    [InlineKeyboardButton("🏠 Home", callback_data=cb_home())],
                ]),
            )
            return

        await query.edit_message_text("⏳ Toggling proxy...")
        new_status = not bool(record_data.get("proxied"))
        success, errors = await toggle_proxy_status(zone_id, record_id, new_status)

        if success:
            # Refresh record data so UI is consistent
            refreshed, ok, _ = await get_single_record(zone_id, record_id)
            if ok and refreshed:
                context.user_data["current_record_data"] = refreshed

            await query.edit_message_text(
                f"✅ Proxy status changed to **{'Proxied' if new_status else 'DNS Only'}**.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back to Record", callback_data=cb_record(record_id))],
                    [InlineKeyboardButton("🏠 Home", callback_data=cb_home())],
                ]),
                parse_mode="Markdown",
            )
        else:
            msg = errors[0]["message"] if errors else "Unknown Error"
            await query.edit_message_text(
                f"❌ Error: `{msg}`",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back to Record", callback_data=cb_record(record_id))],
                    [InlineKeyboardButton("🏠 Home", callback_data=cb_home())],
                ]),
                parse_mode="Markdown",
            )
        return

    # Confirm delete
    if data == "action:confirm_delete":
        record_id = context.user_data.get("current_record_id")
        keyboard = [
            [InlineKeyboardButton("✅ Yes, Delete", callback_data="action:do_delete")],
            [InlineKeyboardButton("❌ Cancel", callback_data=cb_record(record_id))],
        ]
        await query.edit_message_text(
            "⚠️ **Are you sure?**\nThis action cannot be undone.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        return

    # Do delete
    if data == "action:do_delete":
        zone_id = context.user_data.get("current_zone_id")
        record_id = context.user_data.get("current_record_id")
        success, errors = await delete_dns_record(zone_id, record_id)
        if success:
            page = context.user_data.get("current_records_page", 1)
            await query.edit_message_text(
                "✅ Record deleted successfully.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back to List", callback_data=cb_records(zone_id, page))],
                    [InlineKeyboardButton("🏠 Home", callback_data=cb_home())],
                ]),
            )
        else:
            msg = errors[0]["message"] if errors else "Unknown"
            await query.edit_message_text(f"❌ Delete Failed: `{msg}`", parse_mode="Markdown")
        return


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    state = context.user_data.get("state")

    # Edit existing record content
    if state == WAITING_EDIT_CONTENT:
        new_content = update.message.text.strip()
        zone_id = context.user_data.get("current_zone_id")
        record_id = context.user_data.get("current_record_id")
        record_data = context.user_data.get("current_record_data") or {}

        msg = await update.message.reply_text("⏳ Updating...")

        payload = {
            "type": record_data.get("type"),
            "name": record_data.get("name"),
            "content": new_content,
            "proxied": record_data.get("proxied", False),
            "ttl": record_data.get("ttl", 1),
        }

        success, errors = await update_dns_record(zone_id, record_id, payload)
        if success:
            # refresh cache
            refreshed, ok, _ = await get_single_record(zone_id, record_id)
            if ok and refreshed:
                context.user_data["current_record_data"] = refreshed

            await msg.edit_text(
                f"✅ Success!\nNew Content: `{new_content}`",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back to Record", callback_data=cb_record(record_id))],
                    [InlineKeyboardButton("🏠 Home", callback_data=cb_home())],
                ]),
                parse_mode="Markdown",
            )
        else:
            err = errors[0]["message"] if errors else "Unknown"
            await msg.edit_text(f"❌ Error: `{err}`", parse_mode="Markdown")

        context.user_data["state"] = None
        return

    # Create new record
    if state == WAITING_NEW_RECORD_DATA:
        text = update.message.text.strip()
        parts = text.split(maxsplit=1)
        if len(parts) != 2:
            await update.message.reply_text("❌ Invalid format.\nUse: `name content`", parse_mode="Markdown")
            return

        name, content = parts
        zone_id = context.user_data.get("current_zone_id")
        rtype = context.user_data.get("new_record_type", "A")

        msg = await update.message.reply_text("⏳ Creating record...")
        success, errors = await create_dns_record(zone_id, rtype, name, content)

        if success:
            page = context.user_data.get("current_records_page", 1)
            await msg.edit_text(
                f"✅ Record `{name}` created. (type: `{rtype}`)",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back to List", callback_data=cb_records(zone_id, page))],
                    [InlineKeyboardButton("🏠 Home", callback_data=cb_home())],
                ]),
                parse_mode="Markdown",
            )
        else:
            err = errors[0]["message"] if errors else "Unknown"
            await msg.edit_text(f"❌ Error: `{err}`", parse_mode="Markdown")

        context.user_data["state"] = None
        context.user_data["new_record_type"] = None
        return


# ----------------- Main -----------------
if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or not CLOUDFLARE_API_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN or CLOUDFLARE_API_TOKEN is missing in .env file.")
        raise SystemExit(1)

    if not ADMIN_IDS:
        print("Warning: ADMIN_IDS is empty. No one can access the bot.")

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), text_handler))

    print("Bot is running...")
    app.run_polling()
