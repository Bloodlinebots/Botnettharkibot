import os
import asyncio
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from telegram.error import BadRequest, TelegramError
from motor.motor_asyncio import AsyncIOMotorClient

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI") or "mongodb://localhost:27017"

client = AsyncIOMotorClient(MONGO_URI)
db = client["telegram_bot"]

VAULT_CHANNEL_ID = -1002564608005
LOG_CHANNEL_ID = -1002624785490
FORCE_JOIN_CHANNEL = "bot_backup"
ADMIN_USER_ID = 7755789304

USER_FILE = "users.json"

COOLDOWN = 5
cooldowns = {}

# Ensure user file exists
def save_user_id(uid):
    try:
        if os.path.exists(USER_FILE):
            with open(USER_FILE, "r") as f:
                data = json.load(f)
        else:
            data = []
        if uid not in data:
            data.append(uid)
            with open(USER_FILE, "w") as f:
                json.dump(data, f)
    except:
        pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    save_user_id(uid)

    if await db.banned.find_one({"_id": uid}):
        await update.message.reply_text("🚑 You are banned from using this bot.")
        return

    try:
        member = await context.bot.get_chat_member(f"@{FORCE_JOIN_CHANNEL}", uid)
        if member.status in ["left", "kicked"]:
            btn = InlineKeyboardMarkup([
                [InlineKeyboardButton("Join Channel", url=f"https://t.me/{FORCE_JOIN_CHANNEL}")]
            ])
            await update.message.reply_text(
                "🚫 You must join our channel to use this bot.\n\n"
                "✅ After joining, use /start",
                reply_markup=btn,
            )
            return
    except:
        pass

    await db.users.update_one({"_id": uid}, {"$set": {"_id": uid}}, upsert=True)

    user = update.effective_user
    log_text = (
        f"📥 New User Started Bot\n\n"
        f"👤 Name: {user.full_name}\n"
        f"🆔 ID: {user.id}\n"
        f"📛 Username: @{user.username or 'N/A'}"
    )
    await context.bot.send_message(LOG_CHANNEL_ID, log_text)

    caption = (
        "🥵 Welcome to Vault Video Bot!\n"
        "Here you will access the most unseen videos.\n⬇️ Tap below to explore:"
    )

    await update.message.reply_photo(
        photo="https://files.catbox.moe/19j4mc.jpg",
        caption=caption,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📩 Get Random Video", callback_data="get_video")],
            [InlineKeyboardButton("Developer", url="https://t.me/unbornvillian")],
            [
                InlineKeyboardButton("Support", url="https://t.me/botmine_tech"),
                InlineKeyboardButton("Help", callback_data="show_privacy_info"),
            ],
        ]),
    )

async def callback_get_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    await query.answer()

    user = await db.users.find_one({"_id": uid})
    if not user:
        await db.users.insert_one({"_id": uid})

    if user.get("ref_count", 0) < 1:
        link = f"https://t.me/{context.bot.username}?start={uid}"
        await query.message.reply_text(
            f"🔐 Video Locked. Refer 1 user using your link:\n\n🔗 {link}"
        )
        return

    now = asyncio.get_event_loop().time()
    if uid in cooldowns and cooldowns[uid] > now:
        wait = int(cooldowns[uid] - now)
        await query.message.reply_text(f"⏳ Please wait {wait} seconds before getting another video.")
        return
    cooldowns[uid] = now + COOLDOWN

    video_doc = await db.videos.aggregate([{"$sample": {"size": 1}}]).to_list(1)
    if not video_doc:
        await query.message.reply_text("⚠️ No videos available.")
        return

    msg_id = video_doc[0]["msg_id"]
    try:
        await context.bot.copy_message(
            chat_id=uid,
            from_chat_id=VAULT_CHANNEL_ID,
            message_id=msg_id,
            protect_content=True,
        )
        await query.message.reply_text(
            "😈 Want another?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 Get Another Video", callback_data="get_video")]
            ]),
        )
    except Exception as e:
        await query.message.reply_text(f"⚠️ Error: {e}")

async def get_user_ids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID:
        return
    if os.path.exists(USER_FILE):
        await update.message.reply_document(document=open(USER_FILE, "rb"), filename="users.json")
    else:
        await update.message.reply_text("No users recorded yet.")

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_get_video, pattern="get_video"))
    app.add_handler(CallbackQueryHandler(lambda u, c: u.callback_query.answer("/privacy - Read T&C"), pattern="show_privacy_info"))
    app.add_handler(CommandHandler("get_userid", get_user_ids))

    app.run_polling()

if __name__ == "__main__":
    main()
