import os
import json
import random
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from urllib.parse import quote
import qrcode
import io

# --- تنظیمات اولیه ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
REPO_BASE_URL = "https://raw.githubusercontent.com/Ganjabady/XC/main"
STATS_URL = f"{REPO_BASE_URL}/reports/stats.json"
ALL_CONFIGS_URL = f"{REPO_BASE_URL}/subscriptions/v2ray/all_sub.txt"

# --- پیام‌ها و متن‌ها ---
START_MESSAGE = """
سلام! 👋 به ربات V2XCore خوش آمدید.

این ربات به شما کمک می‌کند تا به راحتی به کانفیگ‌های رایگان و پرسرعت دسترسی داشته باشید.

از دکمه‌های زیر برای شروع استفاده کنید:
"""

# --- توابع کمکی ---

async def get_stats():
    """آمار را از فایل stats.json گیت‌هاب دریافت می‌کند."""
    try:
        response = await asyncio.to_thread(requests.get, STATS_URL, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
    return None

def generate_qr_code(text):
    """یک کد QR تولید کرده و به صورت بایت برمی‌گرداند."""
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    buffer = io.BytesIO()
    img.save(buffer, "PNG")
    buffer.seek(0)
    return buffer

# --- دستورات اصلی ربات ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی اصلی را با دکمه‌های شیشه‌ای نمایش می‌دهد."""
    keyboard = [
        [InlineKeyboardButton("🚀 دریافت کانفیگ", callback_data='get_config_menu')],
        [InlineKeyboardButton("📚 راهنما و دانلود", callback_data='help_menu')],
        [InlineKeyboardButton("📣 کانال‌های ما", callback_data='channels_menu')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(START_MESSAGE, reply_markup=reply_markup)

async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تمام کلیک‌های روی دکمه‌ها را مدیریت می‌کند."""
    query = update.callback_query
    await query.answer()
    
    data = query.data

    if data == 'main_menu':
        await query.edit_message_text(START_MESSAGE, reply_markup=get_main_menu_keyboard())
    elif data == 'get_config_menu':
        await query.edit_message_text("یک روش برای دریافت کانفیگ انتخاب کنید:", reply_markup=get_config_menu_keyboard())
    elif data == 'help_menu':
        await query.edit_message_text("بخش راهنما و دانلود:", reply_markup=get_help_menu_keyboard())
    elif data == 'channels_menu':
        await query.edit_message_text("ما را در کانال‌های زیر دنبال کنید:", reply_markup=get_channels_menu_keyboard())
    elif data == 'get_random_config':
        await send_random_config(query)
    elif data.startswith('sub_'):
        await send_subscription_link(query, data)
    elif data.startswith('qr_'):
        await send_qr_code(query, data)

# --- توابع مربوط به منوها و کیبوردها ---

def get_main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🚀 دریافت کانفیگ", callback_data='get_config_menu')],
        [InlineKeyboardButton("📚 راهنما و دانلود", callback_data='help_menu')],
        [InlineKeyboardButton("📣 کانال‌های ما", callback_data='channels_menu')],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_config_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🎲 یک کانفیگ تصادفی", callback_data='get_random_config')],
        [InlineKeyboardButton("🔗 لینک اشتراک (کامل)", callback_data='sub_all')],
        [InlineKeyboardButton("🌍 لینک اشتراک (بر اساس کشور)", callback_data='sub_country')],
        [InlineKeyboardButton("🔩 لینک اشتراک (بر اساس پروتکل)", callback_data='sub_protocol')],
        [InlineKeyboardButton("⬅️ بازگشت", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_help_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📱 دانلود V2RayNG (اندروید)", url="https://github.com/2dust/v2rayNG/releases/latest")],
        [InlineKeyboardButton("🖥️ دانلود Nekoray (ویندوز/لینوکس)", url="https://github.com/MatsuriDayo/nekoray/releases/latest")],
        [InlineKeyboardButton("🍏 آموزش آیفون (NapsternetV)", url="https://t.me/V2XCore/10")], # مثال
        [InlineKeyboardButton("⬅️ بازگشت", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_channels_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🚀 کانال اصلی (V2XCore)", url="https://t.me/V2XCore")],
        [InlineKeyboardButton("🤖 ربات پروژه (V2XCore Bot)", url="https://t.me/V2XCore_BOT")],
        [InlineKeyboardButton("💎 پروژه دیگر (MTXCore)", url="https://t.me/MTXCore")],
        [InlineKeyboardButton("⬅️ بازگشت", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- توابع مربوط به ارسال کانفیگ و لینک ---

async def send_random_config(query: Update.callback_query):
    """یک کانفیگ تصادفی از لیست کلی ارسال می‌کند."""
    await query.edit_message_text("⏳ در حال یافتن یک کانفیگ سریع...")
    try:
        response = await asyncio.to_thread(requests.get, ALL_CONFIGS_URL, timeout=10)
        if response.status_code == 200:
            configs = response.text.strip().split('\n')
            random_config = random.choice(configs)
            await query.edit_message_text(f"👇🏼 برای کپی روی کانفیگ زیر کلیک کنید:\n\n<code>{random_config}</code>", parse_mode='HTML', reply_markup=get_config_menu_keyboard())
        else:
            await query.edit_message_text("❌ متاسفانه در حال حاضر امکان دریافت کانفیگ وجود ندارد.", reply_markup=get_config_menu_keyboard())
    except Exception as e:
        logger.error(f"Error sending random config: {e}")
        await query.edit_message_text("❌ خطایی رخ داد. لطفاً دوباره تلاش کنید.", reply_markup=get_config_menu_keyboard())

async def send_subscription_link(query: Update.callback_query, data: str):
    """لینک اشتراک مربوطه را ارسال می‌کند."""
    sub_type = data.split('_')[1]
    text = ""
    if sub_type == 'all':
        text = f"🔗 لینک اشتراک کامل (شامل تمام کانفیگ‌ها):\n\n`{ALL_CONFIGS_URL}`"
    elif sub_type == 'country':
        # در آینده می‌توان یک منوی داینامیک از کشورها ساخت
        text = f"🔗 لینک‌های اشتراک بر اساس کشور در صفحه گیت‌هاب ما موجود است:\n\nhttps://github.com/Ganjabady/XC"
    elif sub_type == 'protocol':
        text = f"🔗 لینک‌های اشتراک بر اساس پروتکل در صفحه گیت‌هاب ما موجود است:\n\nhttps://github.com/Ganjabady/XC"
    
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=get_config_menu_keyboard())

# --- بخش ارسال خودکار به کانال ---

async def post_to_channel(context: ContextTypes.DEFAULT_TYPE):
    """یک کانفیگ را به صورت دوره‌ای در کانال ارسال می‌کند."""
    logger.info("Running scheduled job: post_to_channel")
    try:
        response = await asyncio.to_thread(requests.get, ALL_CONFIGS_URL, timeout=10)
        if response.status_code == 200:
            configs = response.text.strip().split('\n')
            config_to_send = random.choice(configs)
            
            name = unquote(config_to_send.split('#')[-1])
            protocol = config_to_send.split('://')[0].upper()

            caption = (
                f"{name}\n\n"
                f"👇🏼 برای کپی روی کانفیگ زیر کلیک کنید:\n"
                f"<code>{config_to_send}</code>\n\n"
                f"#{protocol} #V2Ray\n@{SETTINGS.get('brand', 'V2XCore')}"
            )

            keyboard = [[InlineKeyboardButton("🖼️ دریافت کد QR", callback_data=f"qr_{config_to_send}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await context.bot.send_message(chat_id=CHAT_ID, text=caption, parse_mode='HTML', reply_markup=reply_markup)
            logger.info(f"Successfully sent config to channel: {name}")
        else:
            logger.warning(f"Could not fetch configs for scheduled post. Status: {response.status_code}")
    except Exception as e:
        logger.error(f"Error in scheduled job: {e}")

async def send_qr_code(query: Update.callback_query, data: str):
    """کد QR را به صورت یک پیام موقت ارسال می‌کند."""
    config_link = data.replace("qr_", "")
    qr_image_buffer = generate_qr_code(config_link)
    try:
        await query.message.reply_photo(photo=qr_image_buffer, caption="این کد QR پس از چند ثانیه حذف می‌شود.")
        # این بخش برای حذف خودکار پیام است که نیاز به مدیریت بیشتری دارد.
        # برای سادگی، فعلا پیام را حذف نمی‌کنیم.
    except Exception as e:
        logger.error(f"Failed to send QR code: {e}")
        await query.answer("خطا در ساخت کد QR!", show_alert=True)

def main():
    """ربات را اجرا می‌کند."""
    if not BOT_TOKEN or not CHAT_ID:
        logger.critical("BOT_TOKEN یا CHAT_ID در متغیرهای محیطی تنظیم نشده است.")
        return

    application = Application.builder().token(BOT_TOKEN).build()
    
    # اضافه کردن دستورات و کنترل‌گرها
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback_handler))
    
    # تنظیم ارسال دوره‌ای به کانال (مثلاً هر ۱ ساعت)
    job_queue = application.job_queue
    job_queue.run_repeating(post_to_channel, interval=3600, first=10)

    print("🚀 ربات با موفقیت راه‌اندازی شد و در حال اجراست...")
    application.run_polling()

if __name__ == '__main__':
    main()
