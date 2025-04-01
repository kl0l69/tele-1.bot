import telebot
from telebot.types import (InlineKeyboardMarkup, InlineKeyboardButton, 
                          ReplyKeyboardMarkup, KeyboardButton, InputFile)
import sqlite3
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import os
import json
from dotenv import load_dotenv

# تحميل الإعدادات
load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS = [int(id) for id in os.getenv('ADMIN_IDS').split(',')]

bot = telebot.TeleBot(TOKEN)
scheduler = BackgroundScheduler()

# ------ قاعدة البيانات ------
def init_db():
    conn = sqlite3.connect('smart_bot.db')
    c = conn.cursor()
    
    # جدول المستخدمين
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, 
                  username TEXT, 
                  full_name TEXT,
                  join_date TEXT)''')
    
    # جدول المهام
    c.execute('''CREATE TABLE IF NOT EXISTS tasks
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  title TEXT,
                  description TEXT,
                  due_date TEXT,
                  priority INTEGER,
                  status TEXT DEFAULT 'pending',
                  category TEXT,
                  FOREIGN KEY(user_id) REFERENCES users(user_id))''')
    
    # جدول المشاريع
    c.execute('''CREATE TABLE IF NOT EXISTS projects
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  name TEXT,
                  description TEXT,
                  start_date TEXT,
                  end_date TEXT,
                  status TEXT,
                  FOREIGN KEY(user_id) REFERENCES users(user_id))''')
    
    # جدول الوسائط
    c.execute('''CREATE TABLE IF NOT EXISTS media
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  file_id TEXT,
                  file_type TEXT,
                  category TEXT,
                  tags TEXT,
                  upload_date TEXT,
                  FOREIGN KEY(user_id) REFERENCES users(user_id))''')
    
    # جدول المراجع
    c.execute('''CREATE TABLE IF NOT EXISTS references
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  title TEXT,
                  author TEXT,
                  link TEXT,
                  type TEXT,
                  category TEXT,
                  added_date TEXT,
                  FOREIGN KEY(user_id) REFERENCES users(user_id))''')
    
    conn.commit()
    conn.close()

init_db()

# ------ وظائف مساعدة ------
def get_user(user_id):
    conn = sqlite3.connect('smart_bot.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def register_user(user_id, username, full_name):
    conn = sqlite3.connect('smart_bot.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users VALUES (?, ?, ?, ?)",
              (user_id, username, full_name, datetime.now().strftime("%Y-%m-%d")))
    conn.commit()
    conn.close()

# ------ نظام المهام ------
@bot.message_handler(commands=['tasks'])
def tasks_menu(message):
    user_id = message.from_user.id
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("📝 إضافة مهمة", callback_data="add_task"),
        InlineKeyboardButton("📋 قائمة المهام", callback_data="list_tasks")
    )
    markup.row(
        InlineKeyboardButton("⏰ المهام القادمة", callback_data="upcoming_tasks"),
        InlineKeyboardButton("✅ المهام المكتملة", callback_data="completed_tasks")
    )
    bot.send_message(user_id, "📅 قائمة إدارة المهام:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "add_task")
def add_task_callback(call):
    msg = bot.send_message(call.from_user.id, "✍️ الرجاء إرسال عنوان المهمة:")
    bot.register_next_step_handler(msg, process_task_title)

def process_task_title(message):
    user_id = message.from_user.id
    title = message.text
    msg = bot.send_message(user_id, "📝 الرجاء إرسال وصف المهمة (اختياري):")
    bot.register_next_step_handler(msg, process_task_description, title)

def process_task_description(message, title):
    user_id = message.from_user.id
    description = message.text if message.text else "لا يوجد وصف"
    
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("⏰ إضافة موعد نهائي", callback_data=f"set_due_date:{title}:{description}"),
        InlineKeyboardButton("➡️ تخطي", callback_data=f"skip_due_date:{title}:{description}")
    )
    bot.send_message(user_id, "⏳ هل ترغب في تحديد موعد نهائي للمهمة؟", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_due_date:"))
def set_due_date_callback(call):
    _, title, description = call.data.split(":")
    msg = bot.send_message(call.from_user.id, "📅 الرجاء إرسال الموعد النهائي (YYYY-MM-DD HH:MM):")
    bot.register_next_step_handler(msg, save_task_with_date, title, description)

def save_task_with_date(message, title, description):
    user_id = message.from_user.id
    try:
        due_date = datetime.strptime(message.text, "%Y-%m-%d %H:%M")
        
        conn = sqlite3.connect('smart_bot.db')
        c = conn.cursor()
        c.execute("INSERT INTO tasks (user_id, title, description, due_date) VALUES (?, ?, ?, ?)",
                  (user_id, title, description, due_date.strftime("%Y-%m-%d %H:%M")))
        conn.commit()
        conn.close()
        
        # جدولة تذكير
        scheduler.add_job(
            send_reminder,
            'date',
            run_date=due_date - timedelta(hours=1),
            args=[user_id, title]
        )
        
        bot.send_message(user_id, f"✅ تم إضافة المهمة '{title}' مع التذكير!")
    except ValueError:
        bot.send_message(user_id, "⚠️ تنسيق التاريخ غير صحيح! الرجاء المحاولة مرة أخرى.")

# ------ نظام المشاريع ------
@bot.message_handler(commands=['projects'])
def projects_menu(message):
    user_id = message.from_user.id
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("🆕 مشروع جديد", callback_data="add_project"),
        InlineKeyboardButton("📂 مشاريعي", callback_data="list_projects")
    )
    bot.send_message(user_id, "📂 إدارة المشاريع:", reply_markup=markup)

# ------ نظام الوسائط ------
@bot.message_handler(content_types=['photo', 'video', 'document', 'audio'])
def handle_media(message):
    user_id = message.from_user.id
    file_id = None
    file_type = None
    
    if message.photo:
        file_id = message.photo[-1].file_id
        file_type = 'photo'
    elif message.video:
        file_id = message.video.file_id
        file_type = 'video'
    elif message.document:
        file_id = message.document.file_id
        file_type = 'document'
    elif message.audio:
        file_id = message.audio.file_id
        file_type = 'audio'
    
    if file_id:
        msg = bot.send_message(user_id, "📁 الرجاء إرسال تصنيف لهذا الملف (مثال: عمل، دراسة، شخصي):")
        bot.register_next_step_handler(msg, save_media, file_id, file_type)

def save_media(message, file_id, file_type):
    user_id = message.from_user.id
    category = message.text
    
    conn = sqlite3.connect('smart_bot.db')
    c = conn.cursor()
    c.execute("INSERT INTO media (user_id, file_id, file_type, category, upload_date) VALUES (?, ?, ?, ?, ?)",
              (user_id, file_id, file_type, category, datetime.now().strftime("%Y-%m-%d")))
    conn.commit()
    conn.close()
    
    bot.send_message(user_id, f"✅ تم حفظ الملف في تصنيف '{category}'")

# ------ نظام التذكيرات ------
def send_reminder(user_id, task_title):
    bot.send_message(user_id, f"⏰ تذكير: المهمة '{task_title}' ستكون مستحقة خلال ساعة!")

# ------ لوحة التحكم الإدارية ------
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    user_id = message.from_user.id
    if user_id in ADMIN_IDS:
        markup = ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("📊 الإحصائيات", "📢 إرسال إشعار")
        markup.add("🔄 تحديث البوت", "🔙 القائمة الرئيسية")
        bot.send_message(user_id, "🛠️ لوحة التحكم الإدارية:", reply_markup=markup)
    else:
        bot.send_message(user_id, "⛔ ليس لديك صلاحية الوصول لهذه الأداة")

# ------ تشغيل البوت ------
if __name__ == '__main__':
    scheduler.start()
    print("🤖 البوت يعمل...")
    bot.infinity_polling()