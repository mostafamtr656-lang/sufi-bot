import telebot
from telebot.types import BotCommand, BotCommandScopeAllChatAdministrators, InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import threading

# توكن البوت الخاص بك
TOKEN = '8403693554:AAFbnRJKaKHmxs03sjFX2HA34B6URGHdClw'
bot = telebot.TeleBot(TOKEN)

db_lock = threading.Lock()
conn = sqlite3.connect('bot_database.db', check_same_thread=False)
cursor = conn.cursor()

# بناء قاعدة البيانات وتحديثها برتبة المشرف
with db_lock:
    cursor.execute('''CREATE TABLE IF NOT EXISTS warnings (chat_id INTEGER, user_id INTEGER, count INTEGER, PRIMARY KEY (chat_id, user_id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, user_id INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS bot_admins (
                        user_id INTEGER PRIMARY KEY,
                        can_owner INTEGER DEFAULT 0,
                        can_admin INTEGER DEFAULT 0,
                        can_ban INTEGER DEFAULT 0,
                        can_mute INTEGER DEFAULT 0,
                        can_warn INTEGER DEFAULT 0
                    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS bot_owner (user_id INTEGER PRIMARY KEY)''')
    conn.commit()

# تحديث الجداول في حال كانت قديمة
with db_lock:
    try: cursor.execute("ALTER TABLE bot_admins ADD COLUMN can_owner INTEGER DEFAULT 0")
    except: pass
    try: cursor.execute("ALTER TABLE bot_admins ADD COLUMN can_admin INTEGER DEFAULT 0")
    except: pass
    conn.commit()

commands = [
    BotCommand("ban", "طرد وحظر المستخدم"),
    BotCommand("unban", "إلغاء الحظر"),
    BotCommand("mute", "كتم المستخدم"),
    BotCommand("unmute", "إلغاء الكتم"),
    BotCommand("warn", "تحذير العضو"),
    BotCommand("unwarn", "إلغاء تحذير واحد")
]
bot.set_my_commands(commands, scope=BotCommandScopeAllChatAdministrators())

# --- دوال فحص الرتب والحصانة ---

def get_owner_id():
    with db_lock:
        cursor.execute("SELECT user_id FROM bot_owner")
        row = cursor.fetchone()
        return row[0] if row else None

def get_role_level(user_id, chat_id):
    if user_id == get_owner_id():
        return 4 # المستوى 4: المالك الرئيسي
    
    with db_lock:
        cursor.execute("SELECT can_owner, can_admin FROM bot_admins WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            if row[0] == 1: 
                return 3 # المستوى 3: مالك ثاني
            if row[1] == 1: 
                return 2 # المستوى 2: مشرف بوت (اسم وحصانة فقط)
            
    try:
        member = bot.get_chat_member(chat_id, user_id)
        if member.status in ['administrator', 'creator']:
            return 2 # المستوى 2: مشرف بالمجموعة
    except:
        pass
    
    return 1 # المستوى 1: عضو عادي

def check_hierarchy(executor_id, target_id, chat_id, required_perm):
    exec_lvl = get_role_level(executor_id, chat_id)
    target_lvl = get_role_level(target_id, chat_id)

    if target_id == executor_id:
        return False, "⚠️ لا يمكنك معاقبة نفسك."

    # فحص الحصانة
    if target_lvl == 4:
        return False, "❌ تعذر اكمال الاجراء لانه مالك الرئيسي للبوت"
    if target_lvl == 3 and exec_lvl < 4:
        return False, "❌ تعذر اكمال الاجراء لانه مالك الثاني للبوت"
    if target_lvl == 2 and exec_lvl < 3:
        return False, "❌ تعذر اكمال الاجراء لانه مشرف في البوت او المجموعة"

    # فحص امتلاك الصلاحية
    has_perm = False
    if exec_lvl >= 3: 
        has_perm = True 
    else:
        with db_lock:
            cursor.execute(f"SELECT {required_perm} FROM bot_admins WHERE user_id = ?", (executor_id,))
            row = cursor.fetchone()
            if row and row[0] == 1:
                has_perm = True

    if not has_perm:
        return False, "⛔️ عذراً، لا تمتلك الصلاحية لاستخدام هذا الأمر بالبوت."

    return True, ""

def get_target_user(message):
    if message.reply_to_message:
        return message.reply_to_message.from_user.id
    if message.text:
        parts = message.text.split()
        if len(parts) > 1:
            username = parts[1].strip()
            if not username.startswith('@'):
                username = '@' + username
            with db_lock:
                cursor.execute("SELECT user_id FROM users WHERE LOWER(username) = ?", (username.lower(),))
                row = cursor.fetchone()
                if row: 
                    return row[0]
            return "not_found"
    return None

def get_warns(chat_id, user_id):
    with db_lock:
        cursor.execute("SELECT count FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        row = cursor.fetchone()
        return row[0] if row else 0

def set_warns(chat_id, user_id, count):
    with db_lock:
        if count <= 0:
            cursor.execute("DELETE FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        else:
            cursor.execute("INSERT OR REPLACE INTO warnings (chat_id, user_id, count) VALUES (?, ?, ?)", (chat_id, user_id, count))
        conn.commit()

# --- رسالة الترحيب المرتبة عند اضافة البوت للمجموعات ---
@bot.message_handler(content_types=['new_chat_members'])
def welcome_new_chat(message):
    for member in message.new_chat_members:
        if member.id == bot.get_me().id:
            bot.reply_to(message, "✨ شكراً لإضافتي إلى مجموعتكم، تم تفعيل نظام الحماية وجاهز للعمل.")

# --- أوامر التحكم والإدارة ---

@bot.message_handler(commands=['setowner'])
def set_owner(message):
    if get_owner_id() is None:
        with db_lock:
            cursor.execute("INSERT INTO bot_owner (user_id) VALUES (?)", (message.from_user.id,))
            conn.commit()
        bot.reply_to(message, "👑 **تم تسجيلك كمالك رئيسي للبوت!**\nتم تفعيل الحصانة الكاملة لك.")
    elif get_role_level(message.from_user.id, message.chat.id) == 4:
        bot.reply_to(message, "✅ أنت المالك الرئيسي للبوت بالفعل وحصانتك مفعلة.")
    else:
        bot.reply_to(message, "⛔️ البوت لديه مالك مسجل من قبل.")

def generate_admin_keyboard(target_id):
    with db_lock:
        cursor.execute("SELECT can_owner, can_admin, can_ban, can_mute, can_warn FROM bot_admins WHERE user_id = ?", (target_id,))
        row = cursor.fetchone()
    
    can_owner = row[0] if row else 0
    can_admin = row[1] if row else 0
    can_ban = row[2] if row else 0
    can_mute = row[3] if row else 0
    can_warn = row[4] if row else 0

    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton(f"👑 رتبة مالك ثاني: {'✅ مسموح' if can_owner else '❌ ممنوع'}", callback_data=f"perm_owner_{target_id}"),
        InlineKeyboardButton(f"👮‍♂️ رتبة مشرف: {'✅ مسموح' if can_admin else '❌ ممنوع'}", callback_data=f"perm_admin_{target_id}"),
        InlineKeyboardButton(f"🚫 صلاحية الحظر: {'✅ مسموح' if can_ban else '❌ ممنوع'}", callback_data=f"perm_ban_{target_id}"),
        InlineKeyboardButton(f"🔇 صلاحية الكتم: {'✅ مسموح' if can_mute else '❌ ممنوع'}", callback_data=f"perm_mute_{target_id}"),
        InlineKeyboardButton(f"⚠️ صلاحية التحذير: {'✅ مسموح' if can_warn else '❌ ممنوع'}", callback_data=f"perm_warn_{target_id}")
    )
    return keyboard

@bot.message_handler(commands=['addadmin'])
def add_admin(message):
    if get_role_level(message.from_user.id, message.chat.id) != 4:
        return bot.reply_to(message, "⛔️ عذراً، فقط **المالك الرئيسي** يمكنه التحكم بالصلاحيات.")

    target_id = get_target_user(message)
    if target_id == "not_found":
        return bot.reply_to(message, "⚠️ عذراً، اليوزرنيم غير متفاعل بالكروب، يرجى الرد على رسالته مباشرة.")
    if not target_id:
        return bot.reply_to(message, "⚠️ يرجى الرد على رسالة الشخص أو كتابة يوزره.")
    
    with db_lock:
        cursor.execute("INSERT OR IGNORE INTO bot_admins (user_id, can_owner, can_admin, can_ban, can_mute, can_warn) VALUES (?, 0, 0, 0, 0, 0)", (target_id,))
        conn.commit()
    keyboard = generate_admin_keyboard(target_id)
    bot.reply_to(message, "⚙️ **لوحة الصلاحيات والمناصب:**\nحدد الرتبة والصلاحيات التي تريد منحها:", reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith('perm_'))
def handle_permission_callback(call):
    if get_role_level(call.from_user.id, call.message.chat.id) != 4:
        return bot.answer_callback_query(call.id, "⛔️ فقط المالك الرئيسي يمكنه تغيير الصلاحيات!", show_alert=True)

    data_parts = call.data.split('_')
    perm_type = data_parts[1]
    target_id = int(data_parts[2])
    col_name = f"can_{perm_type}"

    with db_lock:
        cursor.execute(f"SELECT {col_name} FROM bot_admins WHERE user_id = ?", (target_id,))
        row = cursor.fetchone()
        new_val = 0 if (row and row[0] == 1) else 1
        cursor.execute(f"UPDATE bot_admins SET {col_name} = ? WHERE user_id = ?", (new_val, target_id))
        conn.commit()

    new_keyboard = generate_admin_keyboard(target_id)
    try:
        bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=new_keyboard)
    except:
        pass
    bot.answer_callback_query(call.id, "✅ تم التحديث بنجاح!")

# --- أوامر العقوبات ---

@bot.message_handler(commands=['ban', 'باند'])
def ban_user(message):
    target_id = get_target_user(message)
    if not target_id: return bot.reply_to(message, "⚠️ يرجى الرد أو كتابة اليوزرنيم.")
    if target_id == "not_found": return bot.reply_to(message, "⚠️ اليوزرنيم غير متفاعل، استخدم الرد.")

    allowed, error_msg = check_hierarchy(message.from_user.id, target_id, message.chat.id, 'can_ban')
    if not allowed: return bot.reply_to(message, error_msg)

    try:
        bot.ban_chat_member(message.chat.id, target_id)
        bot.reply_to(message, "✅ تم طرد وحظر المستخدم بنجاح.")
    except:
        bot.reply_to(message, "❌ فشل الحظر، تأكد أن البوت لديه صلاحية حظر في المجموعة الأساسية.")

@bot.message_handler(commands=['unban', 'الغاء_حظر'])
def unban_user(message):
    target_id = get_target_user(message)
    if not target_id: return bot.reply_to(message, "⚠️ يرجى الرد أو كتابة اليوزرنيم.")
    if target_id == "not_found": return bot.reply_to(message, "⚠️ اليوزرنيم غير متفاعل، استخدم الرد.")

    allowed, error_msg = check_hierarchy(message.from_user.id, target_id, message.chat.id, 'can_ban')
    if not allowed: return bot.reply_to(message, error_msg)

    bot.unban_chat_member(message.chat.id, target_id, only_if_banned=True)
    bot.reply_to(message, "✅ تم إلغاء الحظر.")

@bot.message_handler(commands=['mute', 'كتم'])
def mute_user(message):
    target_id = get_target_user(message)
    if not target_id: return bot.reply_to(message, "⚠️ يرجى الرد أو كتابة اليوزرنيم.")
    if target_id == "not_found": return bot.reply_to(message, "⚠️ اليوزرنيم غير متفاعل، استخدم الرد.")

    allowed, error_msg = check_hierarchy(message.from_user.id, target_id, message.chat.id, 'can_mute')
    if not allowed: return bot.reply_to(message, error_msg)

    try:
        bot.restrict_chat_member(message.chat.id, target_id, can_send_messages=False)
        bot.reply_to(message, "✅ تم كتم المستخدم بنجاح.")
    except:
        bot.reply_to(message, "❌ فشل الكتم، تأكد أن البوت لديه صلاحية تقييد في المجموعة الأساسية.")

@bot.message_handler(commands=['unmute', 'الغاء_الكتم'])
def unmute_user(message):
    target_id = get_target_user(message)
    if not target_id: return bot.reply_to(message, "⚠️ يرجى الرد أو كتابة اليوزرنيم.")
    if target_id == "not_found": return bot.reply_to(message, "⚠️ اليوزرنيم غير متفاعل، استخدم الرد.")

    allowed, error_msg = check_hierarchy(message.from_user.id, target_id, message.chat.id, 'can_mute')
    if not allowed: return bot.reply_to(message, error_msg)

    bot.restrict_chat_member(message.chat.id, target_id, can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True)
    bot.reply_to(message, "✅ تم إلغاء الكتم بنجاح.")

@bot.message_handler(commands=['warn', 'تحذير'])
def warn_user(message):
    target_id = get_target_user(message)
    if not target_id: return bot.reply_to(message, "⚠️ يرجى الرد أو كتابة اليوزرنيم.")
    if target_id == "not_found": return bot.reply_to(message, "⚠️ اليوزرنيم غير متفاعل، استخدم الرد.")

    allowed, error_msg = check_hierarchy(message.from_user.id, target_id, message.chat.id, 'can_warn')
    if not allowed: return bot.reply_to(message, error_msg)

    chat_id = message.chat.id
    current_warns = get_warns(chat_id, target_id) + 1
    if current_warns >= 3:
        bot.restrict_chat_member(chat_id, target_id, can_send_messages=False)
        bot.reply_to(message, "⛔️ تم كتم المستخدم لوصوله إلى 3 تحذيرات.")
        set_warns(chat_id, target_id, 0)
    else:
        set_warns(chat_id, target_id, current_warns)
        bot.reply_to(message, f"⚠️ تم تحذير المستخدم. ({current_warns}/3)")

@bot.message_handler(commands=['unwarn', 'الغاء_تحذير'])
def unwarn_user(message):
    target_id = get_target_user(message)
    if not target_id: return bot.reply_to(message, "⚠️ يرجى الرد أو كتابة اليوزرنيم.")
    if target_id == "not_found": return bot.reply_to(message, "⚠️ اليوزرنيم غير متفاعل، استخدم الرد.")

    allowed, error_msg = check_hierarchy(message.from_user.id, target_id, message.chat.id, 'can_warn')
    if not allowed: return bot.reply_to(message, error_msg)

    chat_id = message.chat.id
    current_warns = get_warns(chat_id, target_id)
    if current_warns > 0:
        set_warns(chat_id, target_id, current_warns - 1)
        bot.reply_to(message, f"✅ تم سحب تحذير. (المتبقي: {current_warns - 1}/3)")
    else:
        bot.reply_to(message, "ℹ️ لا توجد تحذيرات على هذا العضو.")

@bot.message_handler(func=lambda message: True, content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker'])
def cache_users(message):
    if message.from_user.username:
        username = "@" + message.from_user.username.lower()
        with db_lock:
            cursor.execute("INSERT OR REPLACE INTO users (username, user_id) VALUES (?, ?)", (username, message.from_user.id))
            conn.commit()

bot.infinity_polling()