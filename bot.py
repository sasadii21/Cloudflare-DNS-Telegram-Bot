import os
import logging
import httpx
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")
# Parse admin IDs from comma-separated string (e.g., "12345,67890")
ADMIN_IDS = [int(id_str) for id_str in os.getenv("ADMIN_IDS", "").split(",") if id_str.strip()]

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Conversation States
WAITING_IP = 1
WAITING_NEW_RECORD_DATA = 2

# --- Cloudflare API Helper Functions (Async/httpx) ---
async def cf_request(method, endpoint, json_data=None):
    url = f"https://api.cloudflare.com/client/v4{endpoint}"
    headers = {
        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json"
    }
    async with httpx.AsyncClient() as client:
        try:
            if method == 'GET':
                resp = await client.get(url, headers=headers)
            elif method == 'POST':
                resp = await client.post(url, headers=headers, json=json_data)
            elif method == 'PUT':
                resp = await client.put(url, headers=headers, json=json_data)
            elif method == 'PATCH':
                resp = await client.patch(url, headers=headers, json=json_data)
            elif method == 'DELETE':
                resp = await client.delete(url, headers=headers)
            
            return resp.json()
        except Exception as e:
            logger.error(f"Cloudflare API Error: {e}")
            return {"success": False, "errors": [{"message": str(e)}]}

async def get_zones():
    res = await cf_request('GET', "/zones")
    return res.get('result', [])

async def get_dns_records(zone_id):
    res = await cf_request('GET', f"/zones/{zone_id}/dns_records?per_page=50")
    return res.get('result', [])

async def get_single_record(zone_id, record_id):
    res = await cf_request('GET', f"/zones/{zone_id}/dns_records/{record_id}")
    return res.get('result', None)

async def update_dns_record(zone_id, record_id, data):
    res = await cf_request('PUT', f"/zones/{zone_id}/dns_records/{record_id}", json_data=data)
    return res.get('success', False), res.get('errors', [])

async def toggle_proxy_status(zone_id, record_id, current_status):
    payload = {"proxied": not current_status}
    res = await cf_request('PATCH', f"/zones/{zone_id}/dns_records/{record_id}", json_data=payload)
    return res.get('success', False), res.get('errors', [])

async def create_dns_record(zone_id, name, ip):
    payload = {"type": "A", "name": name, "content": ip, "proxied": False, "ttl": 1}
    res = await cf_request('POST', f"/zones/{zone_id}/dns_records", json_data=payload)
    return res.get('success', False), res.get('errors', [])

async def delete_dns_record(zone_id, record_id):
    res = await cf_request('DELETE', f"/zones/{zone_id}/dns_records/{record_id}")
    return res.get('success', False), res.get('errors', [])

# --- Authorization Check ---
def is_admin(user_id):
    return user_id in ADMIN_IDS

# --- Telegram Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    
    keyboard = [[InlineKeyboardButton("☁️ Manage Domains", callback_data='list_zones')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👋 **Cloudflare Management Panel**\n\nSelect an option to start:", 
        reply_markup=reply_markup, 
        parse_mode='Markdown'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Access Denied", show_alert=True)
        return

    await query.answer()
    data = query.data

    # 1. List Zones
    if data == 'list_zones':
        zones = await get_zones()
        if not zones:
            await query.edit_message_text("❌ No zones found or API token is invalid.", 
                                          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Retry", callback_data='list_zones')]]))
            return

        keyboard = []
        for zone in zones:
            keyboard.append([InlineKeyboardButton(f"📂 {zone['name']}", callback_data=f"zone_{zone['id']}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("🌐 Select a Domain:", reply_markup=reply_markup)

    # 2. List Records
    elif data.startswith('zone_'):
        zone_id = data.split('_')[1]
        context.user_data['current_zone_id'] = zone_id
        
        records = await get_dns_records(zone_id)
        keyboard = []
        
        for rec in records:
            if rec['type'] in ['A', 'CNAME', 'AAAA']:
                icon = "☁️" if rec['proxied'] else "🌪"
                btn_text = f"{icon} {rec['name'].split('.')[0]} ({rec['type']}) -> {rec['content']}"
                keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"rec_{rec['id']}")])
        
        keyboard.append([InlineKeyboardButton("➕ New Record (A)", callback_data="add_new_record")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="list_zones")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"📝 DNS Records:", reply_markup=reply_markup)

    # 3. Record Details
    elif data.startswith('rec_'):
        record_id = data.split('_')[1]
        zone_id = context.user_data.get('current_zone_id')
        
        record = await get_single_record(zone_id, record_id)
        if not record:
            await query.edit_message_text("❌ Record not found.")
            return

        context.user_data['current_record_id'] = record_id
        context.user_data['current_record_data'] = record
        
        status_icon = "✅ Active (Proxied)" if record['proxied'] else "❌ DNS Only"
        
        details = (
            f"📌 **Record:** `{record['name']}`\n"
            f"📎 **Type:** `{record['type']}`\n"
            f"🌐 **Content:** `{record['content']}`\n"
            f"🛡 **Proxy:** {status_icon}\n"
        )
        
        keyboard = [
            [InlineKeyboardButton("✏️ Edit IP/Content", callback_data="action_edit_ip")],
            [InlineKeyboardButton("🔄 Toggle Proxy", callback_data="action_toggle_proxy")],
            [InlineKeyboardButton("🗑 Delete Record", callback_data="action_confirm_delete")],
            [InlineKeyboardButton("🔙 Back", callback_data=f"zone_{zone_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(details, reply_markup=reply_markup, parse_mode='Markdown')

    # 4. Action: Edit IP Input
    elif data == 'action_edit_ip':
        context.user_data['state'] = WAITING_IP
        await query.edit_message_text("✍️ Send the **New IP**:", parse_mode='Markdown')

    # 5. Action: Toggle Proxy
    elif data == 'action_toggle_proxy':
        zone_id = context.user_data.get('current_zone_id')
        record_id = context.user_data.get('current_record_id')
        record_data = context.user_data.get('current_record_data')
        
        await query.edit_message_text("⏳ Toggling proxy...")
        
        success, errors = await toggle_proxy_status(zone_id, record_id, record_data['proxied'])
        
        if success:
            new_status = "DNS Only" if record_data['proxied'] else "Proxied"
            keyboard = [[InlineKeyboardButton("🔙 Back to Record", callback_data=f"rec_{record_id}")]]
            await query.edit_message_text(f"✅ Proxy status changed to **{new_status}**.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        else:
            await query.edit_message_text(f"❌ Error: {errors[0]['message'] if errors else 'Unknown Error'}")

    # 6. Action: Confirm Delete
    elif data == 'action_confirm_delete':
        keyboard = [
            [InlineKeyboardButton("✅ Yes, Delete", callback_data="action_do_delete")],
            [InlineKeyboardButton("❌ Cancel", callback_data=f"rec_{context.user_data.get('current_record_id')}")]
        ]
        await query.edit_message_text("⚠️ **Are you sure?**\nThis action cannot be undone.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    # 7. Action: Perform Delete
    elif data == 'action_do_delete':
        zone_id = context.user_data.get('current_zone_id')
        record_id = context.user_data.get('current_record_id')
        
        success, errors = await delete_dns_record(zone_id, record_id)
        
        if success:
            keyboard = [[InlineKeyboardButton("🔙 Back to List", callback_data=f"zone_{zone_id}")]]
            await query.edit_message_text("✅ Record deleted successfully.", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await query.edit_message_text(f"❌ Delete Failed: {errors[0]['message']}")

    # 8. Action: New Record Input
    elif data == 'add_new_record':
        context.user_data['state'] = WAITING_NEW_RECORD_DATA
        await query.edit_message_text(
            "✍️ Send Name and IP separated by space.\n\n"
            "Example: `vpn 192.168.1.1`\n"
            "(Result: vpn.yourdomain.com)", 
            parse_mode='Markdown'
        )

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    state = context.user_data.get('state')
    
    # Process: Edit IP
    if state == WAITING_IP:
        new_content = update.message.text.strip()
        zone_id = context.user_data.get('current_zone_id')
        record_id = context.user_data.get('current_record_id')
        record_data = context.user_data.get('current_record_data')
        
        msg = await update.message.reply_text("⏳ Updating...")
        
        payload = {
            "type": record_data['type'],
            "name": record_data['name'],
            "content": new_content,
            "proxied": record_data['proxied'],
            "ttl": record_data['ttl']
        }
        
        success, errors = await update_dns_record(zone_id, record_id, payload)
        
        if success:
            keyboard = [[InlineKeyboardButton("🔙 Back to Record", callback_data=f"rec_{record_id}")]]
            await msg.edit_text(f"✅ Success!\nNew Content: `{new_content}`", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        else:
            await msg.edit_text(f"❌ Error: {errors[0]['message'] if errors else 'Unknown'}")
        
        context.user_data['state'] = None

    # Process: New Record
    elif state == WAITING_NEW_RECORD_DATA:
        try:
            text = update.message.text.strip()
            parts = text.split()
            
            if len(parts) < 2:
                await update.message.reply_text("❌ Invalid format. Use: `name ip`")
                return
            
            name = parts[0]
            ip = parts[1]
            zone_id = context.user_data.get('current_zone_id')
            
            msg = await update.message.reply_text("⏳ Creating record...")
            success, errors = await create_dns_record(zone_id, name, ip)
            
            if success:
                keyboard = [[InlineKeyboardButton("🔙 Back to List", callback_data=f"zone_{zone_id}")]]
                await msg.edit_text(f"✅ Record `{name}` created.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            else:
                await msg.edit_text(f"❌ Error: {errors[0]['message'] if errors else 'Unknown'}")
            
            context.user_data['state'] = None
            
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

if __name__ == '__main__':
    # Validate Environment Variables
    if not TELEGRAM_BOT_TOKEN or not CLOUDFLARE_API_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN or CLOUDFLARE_API_TOKEN is missing in .env file.")
        exit(1)
    
    if not ADMIN_IDS:
        print("Warning: ADMIN_IDS is empty. No one can access the bot.")

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), text_handler))
    
    print("Bot is running...")
    application.run_polling()
