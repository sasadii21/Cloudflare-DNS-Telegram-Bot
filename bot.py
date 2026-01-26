import os
import logging
import requests
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Conversation States
WAITING_IP = 1
WAITING_NEW_RECORD_DATA = 2

# Cloudflare API Helper Functions
def cf_headers():
    return {"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}", "Content-Type": "application/json"}

def get_zones():
    url = "https://api.cloudflare.com/client/v4/zones"
    try:
        res = requests.get(url, headers=cf_headers()).json()
        return res.get('result', [])
    except Exception as e:
        logger.error(f"Error fetching zones: {e}")
        return []

def get_dns_records(zone_id):
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records?type=A"
    try:
        res = requests.get(url, headers=cf_headers()).json()
        return res.get('result', [])
    except Exception as e:
        logger.error(f"Error fetching DNS records: {e}")
        return []

def get_single_record(zone_id, record_id):
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}"
    try:
        res = requests.get(url, headers=cf_headers()).json()
        return res.get('result', None)
    except Exception as e:
        logger.error(f"Error fetching single record: {e}")
        return None

def update_dns_ip(zone_id, record_id, new_ip, record_data):
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}"
    payload = {
        "type": "A",
        "name": record_data['name'],
        "content": new_ip,
        "proxied": record_data['proxied'],
        "ttl": record_data['ttl']
    }
    try:
        res = requests.put(url, headers=cf_headers(), json=payload).json()
        return res.get('success', False), res.get('errors', [])
    except Exception as e:
        return False, [{"message": str(e)}]

def create_dns_record(zone_id, name, ip):
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
    payload = {"type": "A", "name": name, "content": ip, "proxied": False, "ttl": 1}
    try:
        res = requests.post(url, headers=cf_headers(), json=payload).json()
        return res.get('success', False), res.get('errors', [])
    except Exception as e:
        return False, [{"message": str(e)}]

# Telegram Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    keyboard = [[InlineKeyboardButton("🌐 نمایش دامنه‌ها", callback_data='list_zones')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("👋 به پنل مدیریت کلودفلر خوش آمدید.", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    # 1. List Zones
    if data == 'list_zones':
        zones = get_zones()
        if not zones:
            await query.edit_message_text("❌ هیچ دامنه‌ای یافت نشد یا توکن اشتباه است.")
            return

        keyboard = []
        for zone in zones:
            keyboard.append([InlineKeyboardButton(f"📂 {zone['name']}", callback_data=f"zone_{zone['id']}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("یکی از دامنه‌های خود را انتخاب کنید:", reply_markup=reply_markup)

    # 2. List Records
    elif data.startswith('zone_'):
        zone_id = data.split('_')[1]
        context.user_data['current_zone_id'] = zone_id
        
        records = get_dns_records(zone_id)
        keyboard = []
        for rec in records:
            name_part = rec['name'].split('.')[0]
            if name_part == rec['name']: name_part = "@" # Handle root domain
            
            btn_text = f"🔸 {name_part} -> {rec['content']}"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"rec_{rec['id']}")])
        
        keyboard.append([InlineKeyboardButton("➕ افزودن رکورد جدید", callback_data="add_new_record")])
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="list_zones")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"رکوردهای دامنه انتخاب شده:", reply_markup=reply_markup)

    # 3. Show Record Details
    elif data.startswith('rec_'):
        record_id = data.split('_')[1]
        zone_id = context.user_data.get('current_zone_id')
        
        record = get_single_record(zone_id, record_id)
        if not record:
            await query.edit_message_text("❌ خطا در دریافت اطلاعات رکورد.")
            return

        context.user_data['current_record_id'] = record_id
        context.user_data['current_record_data'] = record
        
        details = (
            f"📌 **دامنه:** `{record['name']}`\n"
            f"🌐 **ای‌پی فعلی:** `{record['content']}`\n"
            f"🛡 **پروکسی:** {'روشن ✅' if record['proxied'] else 'خاموش ❌'}\n"
        )
        
        keyboard = [
            [InlineKeyboardButton("✏️ تغییر IP", callback_data="action_edit_ip")],
            [InlineKeyboardButton("🔙 بازگشت به لیست", callback_data=f"zone_{zone_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(details, reply_markup=reply_markup, parse_mode='Markdown')

    # 4. Ask for IP
    elif data == 'action_edit_ip':
        context.user_data['state'] = WAITING_IP
        await query.edit_message_text("✍️ لطفاً **IP جدید** را ارسال کنید:\n(مثال: 1.1.1.1)", parse_mode='Markdown')

    # 5. Ask for New Record Data
    elif data == 'add_new_record':
        context.user_data['state'] = WAITING_NEW_RECORD_DATA
        await query.edit_message_text(
            "✍️ برای ساخت رکورد جدید، **نام و ای‌پی** را با فاصله بفرستید.\n\n"
            "مثال: `sub 10.20.30.40`\n"
            "(این کار ساب‌دامین sub.domain.com را با ای‌پی داده شده می‌سازد)", 
            parse_mode='Markdown'
        )

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    state = context.user_data.get('state')
    
    # Process IP Change
    if state == WAITING_IP:
        new_ip = update.message.text.strip()
        zone_id = context.user_data.get('current_zone_id')
        record_id = context.user_data.get('current_record_id')
        record_data = context.user_data.get('current_record_data')
        
        msg = await update.message.reply_text("⏳ در حال آپدیت...")
        
        success, errors = update_dns_ip(zone_id, record_id, new_ip, record_data)
        
        if success:
            await msg.edit_text(f"✅ انجام شد!\nای‌پی به `{new_ip}` تغییر یافت.")
        else:
            error_msg = errors[0]['message'] if errors else "Unknown error"
            await msg.edit_text(f"❌ خطا: {error_msg}")
        
        context.user_data['state'] = None
        keyboard = [[InlineKeyboardButton("🔙 بازگشت به لیست رکوردها", callback_data=f"zone_{zone_id}")]]
        await update.message.reply_text("منو:", reply_markup=InlineKeyboardMarkup(keyboard))

    # Process New Record Creation
    elif state == WAITING_NEW_RECORD_DATA:
        try:
            text_parts = update.message.text.strip().split()
            if len(text_parts) != 2:
                await update.message.reply_text("❌ فرمت اشتباه. لطفا ارسال کنید: `نام ای‌پی`")
                return
            
            name = text_parts[0]
            ip = text_parts[1]
            zone_id = context.user_data.get('current_zone_id')
            
            msg = await update.message.reply_text("⏳ در حال ساخت رکورد...")
            success, errors = create_dns_record(zone_id, name, ip)
            
            if success:
                await msg.edit_text(f"✅ رکورد `{name}` با ای‌پی `{ip}` ساخته شد.")
            else:
                error_msg = errors[0]['message'] if errors else "Unknown error"
                await msg.edit_text(f"❌ خطا: {error_msg}")
            
            context.user_data['state'] = None
            keyboard = [[InlineKeyboardButton("🔙 بازگشت به لیست رکوردها", callback_data=f"zone_{zone_id}")]]
            await update.message.reply_text("منو:", reply_markup=InlineKeyboardMarkup(keyboard))
            
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

if __name__ == '__main__':
    if not TELEGRAM_BOT_TOKEN or not CLOUDFLARE_API_TOKEN:
        print("Error: Environment variables not set. Please check .env file.")
        exit(1)

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), text_handler))
    
    print("Bot is running...")
    application.run_polling()
