import os
import asyncio
import json
import zipfile
import io
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from telegram.error import BadRequest, TelegramError
from motor.motor_asyncio import AsyncIOMotorClient

# ---------- CONFIG ----------
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI") or "mongodb://localhost:27017"

client = AsyncIOMotorClient(MONGO_URI)
db = client["telegram_bot"]

VAULT_CHANNEL_ID = -1002710213590
LOG_CHANNEL_ID = -1002767911705
FORCE_JOIN_CHANNEL = "bot_backup"
ADMIN_USER_ID = 1209978813
DEVELOPER_LINK = "https://t.me/GODCHEATOFFICIAL"
SUPPORT_LINK = "https://t.me/botmine_tech"
TERMS_LINK = "https://t.me/bot_backup/7"
WELCOME_IMAGE = "https://files.catbox.moe/fxsuba.jpg"

COOLDOWN = 5
cooldowns = {}

USERS_JSON_FILE = "users.json"

# For sudo users
sudo_users = set()

# ---------- HELPERS ----------

def is_admin(uid):
    return uid == ADMIN_USER_ID

def is_sudo(uid):
    return uid in sudo_users or is_admin(uid)

async def save_user_to_json(uid):
    try:
        if os.path.exists(USERS_JSON_FILE):
            with open(USERS_JSON_FILE, "r") as f:
                users = json.load(f)
        else:
            users = []

        if uid not in users:
            users.append(uid)
            with open(USERS_JSON_FILE, "w") as f:
                json.dump(users, f)
    except Exception as e:
        print(f"Error saving user to JSON: {e}")

async def delete_after_delay(bot, chat_id, message_id, delay):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except:
        pass

# ---------- HANDLERS ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if await db.banned.find_one({"_id": uid}):
        await update.message.reply_text("🛑 You are banned from using this bot.")
        return

    # Force join channel check
    try:
        member = await context.bot.get_chat_member(f"@{FORCE_JOIN_CHANNEL}", uid)
        if member.status in ["left", "kicked"]:
            btn = InlineKeyboardMarkup([
                [InlineKeyboardButton("Join Channel", url=f"https://t.me/{FORCE_JOIN_CHANNEL}")]
            ])
            await update.message.reply_text(
                "🛑 You must join our channel to use this bot.\n\n"
                "✅ After joining, use /start",
                reply_markup=btn,
            )
            return
    except:
        pass

    args = context.args
    referrer_id = None
    if args:
        try:
            referrer_id = int(args[0])
        except:
            pass

    # Save user to MongoDB users collection
    await db.users.update_one({"_id": uid}, {"$set": {"_id": uid}}, upsert=True)
    # Save user in JSON
    await save_user_to_json(uid)

    # Handle referral if valid
    if referrer_id and referrer_id != uid:
        already_referred = await db.referrals.find_one({"referral": uid})
        if not already_referred:
            await db.referrals.insert_one({"referrer": referrer_id, "referral": uid})
            count = await db.referrals.count_documents({"referrer": referrer_id})
            if count == 1:
                # Notify referrer about unlock
                try:
                    await context.bot.send_message(
                        referrer_id,
                        "✅ Your video is unlocked. Please press the button again."
                    )
                except:
                    pass

    user = update.effective_user
    log_text = (
        f"📥 New User Started Bot\n\n"
        f"👤 Name: {user.full_name}\n"
        f"🆔 ID: {user.id}\n"
        f"📛 Username: @{user.username or 'N/A'}"
    )
    await context.bot.send_message(LOG_CHANNEL_ID, log_text)

    bot_username = (await context.bot.get_me()).username
    caption = (
        f"🥵 Welcome to @{bot_username}!\n"
        "Here you will access the most unseen videos.\n👇 Tap below to explore:"
    )

    await update.message.reply_photo(
        photo=WELCOME_IMAGE,
        caption=caption,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📩 Get Random Video", callback_data="get_video")],
            [InlineKeyboardButton("Developer", url=DEVELOPER_LINK)],
            [
                InlineKeyboardButton("Support", url=SUPPORT_LINK),
                InlineKeyboardButton("Help", callback_data="show_privacy_info"),
            ],
        ]),
    )

    disclaimer = (
        "⚠️ **Disclaimer** ⚠️\n\n"
        "We do NOT produce or spread adult content.\n"
        "This bot is only for forwarding files.\n"
        "Please read terms and conditions."
    )
    btn = InlineKeyboardMarkup(
        [[InlineKeyboardButton("📘 Terms & Conditions", url=TERMS_LINK)]]
    )
    await context.bot.send_message(uid, disclaimer, reply_markup=btn, parse_mode="Markdown")

async def callback_get_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    await query.answer()

    if await db.banned.find_one({"_id": uid}):
        await query.message.reply_text("🛑 You are banned from using this bot.")
        return

    now = asyncio.get_event_loop().time()
    if not is_admin(uid):
        if uid in cooldowns and cooldowns[uid] > now:
            wait = int(cooldowns[uid] - now)
            await query.message.reply_text(f"⏳ Please wait {wait} seconds before getting another video.")
            return
        cooldowns[uid] = now + COOLDOWN

    # Check referral count
    referral_count = await db.referrals.count_documents({"referrer": uid})
    if referral_count < 1:
        bot_username = (await context.bot.get_me()).username
        ref_link = f"https://t.me/{bot_username}?start={uid}"
        await query.message.reply_text(
            f"🔒 Video locked! Refer 1 user to unlock it.\n\n"
            f"Your referral link:\n{ref_link}"
        )
        return

    # User can get video
    video_doc = await db.videos.aggregate([
        {"$sample": {"size": 1}}
    ]).to_list(1)

    if not video_doc:
        await query.message.reply_text("⚠️ No videos available.")
        return

    msg_id = video_doc[0]["msg_id"]

    try:
        sent = await context.bot.copy_message(
            chat_id=uid,
            from_chat_id=VAULT_CHANNEL_ID,
            message_id=msg_id,
            protect_content=True,
        )

        context.application.create_task(
            delete_after_delay(context.bot, uid, sent.message_id, 10800)
        )

        await query.message.reply_text(
            f"😈 Want another?",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("📥 Get Another Video", callback_data="get_video")]]
            ),
        )
    except BadRequest as e:
        if "MESSAGE_ID_INVALID" in str(e):
            await db.videos.delete_one({"msg_id": msg_id})
            await context.bot.send_message(LOG_CHANNEL_ID, f"⚠️ Deleted broken video: `{msg_id}`", parse_mode="Markdown")
            await query.message.reply_text("⚠️ That video was broken. Trying another...")
            await asyncio.sleep(1)
            await callback_get_video(update, context)
        else:
            await query.message.reply_text(f"⚠️ Telegram error: {e}")
    except TelegramError as e:
        await query.message.reply_text(f"⚠️ Telegram error occurred: {e}")
    except Exception as e:
        await query.message.reply_text(f"⚠️ Unknown error occurred: {e}")

# Show privacy and help info
async def show_privacy_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "This bot forwards videos from a private channel.\n"
        "You must refer 1 user to unlock videos.\n"
        "Please follow the terms and conditions."
    )
    await query.message.edit_text(text)

async def privacy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Privacy policy: This bot does not store your data except user IDs and referrals.\n"
        "All data is kept securely."
    )
    await update.message.reply_text(text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Help:\n"
        "/start - Start bot\n"
        "Use the buttons to get videos.\n"
        "Refer 1 user to unlock videos."
    )
    await update.message.reply_text(text)

# Admin commands

async def add_sudo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /addsudo <user_id>")
        return
    try:
        uid = int(context.args[0])
        sudo_users.add(uid)
        await update.message.reply_text(f"Added {uid} to sudo users.")
    except:
        await update.message.reply_text("Invalid user ID.")

async def remove_sudo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /remsudo <user_id>")
        return
    try:
        uid = int(context.args[0])
        sudo_users.discard(uid)
        await update.message.reply_text(f"Removed {uid} from sudo users.")
    except:
        await update.message.reply_text("Invalid user ID.")

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /ban <user_id>")
        return
    try:
        uid = int(context.args[0])
        await db.banned.update_one({"_id": uid}, {"$set": {"_id": uid}}, upsert=True)
        await update.message.reply_text(f"Banned user {uid}")
    except:
        await update.message.reply_text("Invalid user ID.")

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /unban <user_id>")
        return
    try:
        uid = int(context.args[0])
        await db.banned.delete_one({"_id": uid})
        await update.message.reply_text(f"Unbanned user {uid}")
    except:
        await update.message.reply_text("Invalid user ID.")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    text = " ".join(context.args)
    users = await db.users.find().to_list(length=None)
    count = 0
    for u in users:
        try:
            await context.bot.send_message(u["_id"], text)
            count += 1
            await asyncio.sleep(0.1)
        except:
            continue
    await update.message.reply_text(f"Broadcast sent to {count} users.")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    total_users = await db.users.count_documents({})
    total_videos = await db.videos.count_documents({})
    total_banned = await db.banned.count_documents({})
    text = (
        f"📊 Stats:\n"
        f"Users: {total_users}\n"
        f"Videos: {total_videos}\n"
        f"Banned: {total_banned}"
    )
    await update.message.reply_text(text)

async def auto_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_sudo(uid):
        return
    msg = update.message
    if msg.video:
        try:
            await db.videos.update_one(
                {"msg_id": msg.message_id},
                {"$set": {"msg_id": msg.message_id}},
                upsert=True,
            )
            await msg.reply_text("✅ Video added to vault.")
        except Exception as e:
            await msg.reply_text(f"Error: {e}")

async def export_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID:
        return

    if not os.path.exists(USERS_JSON_FILE):
        await update.message.reply_text("⚠️ Users file not found.")
        return

    with open(USERS_JSON_FILE, "rb") as f:
        data = f.read()

    bio = io.BytesIO()
    with zipfile.ZipFile(bio, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("users.json", data)
    bio.seek(0)

    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=bio,
        filename="users.zip",
        caption="📦 Here is the users JSON file zipped."
    )

# ---------- MAIN ----------

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_get_video, pattern="get_video"))
    app.add_handler(CallbackQueryHandler(show_privacy_info, pattern="show_privacy_info"))
    app.add_handler(CommandHandler("privacy", privacy_command))
    app.add_handler(CommandHandler("help", help_command))

    app.add_handler(CommandHandler("addsudo", add_sudo))
    app.add_handler(CommandHandler("remsudo", remove_sudo))
    app.add_handler(CommandHandler("ban", ban_user))
    app.add_handler(CommandHandler("unban", unban_user))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("export_users", export_users))

    app.add_handler(MessageHandler(filters.VIDEO, auto_upload))

    print("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
