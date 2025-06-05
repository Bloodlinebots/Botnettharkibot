import os
import json
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import CommandHandler, ApplicationBuilder, ContextTypes, CallbackQueryHandler
from motor.motor_asyncio import AsyncIOMotorClient

# CONFIG
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI") or "mongodb://localhost:27017"
ADMIN_USER_ID = 7755789304

client = AsyncIOMotorClient(MONGO_URI)
db = client["telegram_bot"]

USERS_FILE = "users.json"

# --- UTILITIES ---

def load_user_ids():
    if not os.path.exists(USERS_FILE):
        return []
    with open(USERS_FILE, "r") as f:
        return json.load(f)

def save_user_ids(user_ids):
    with open(USERS_FILE, "w") as f:
        json.dump(user_ids, f)

async def update_user_file(user_id):
    user_ids = load_user_ids()
    if user_id not in user_ids:
        user_ids.append(user_id)
        save_user_ids(user_ids)

# --- START HANDLER WITH REFERRAL ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    args = context.args
    referrer_id = int(args[0]) if args else None

    await db.users.update_one({"_id": uid}, {"$set": {"_id": uid}}, upsert=True)
    await update_user_file(uid)

    # Referral logic
    user_data = await db.referrals.find_one({"_id": uid})
    if not user_data:
        await db.referrals.insert_one({
            "_id": uid,
            "referred_by": referrer_id,
            "referrals": 0,
            "unlocked": False
        })

        if referrer_id and referrer_id != uid:
            ref_data = await db.referrals.find_one({"_id": referrer_id})
            if ref_data:
                new_count = ref_data.get("referrals", 0) + 1
                await db.referrals.update_one({"_id": referrer_id}, {"$set": {"referrals": new_count}})

                if new_count >= 1 and not ref_data.get("unlocked"):
                    await db.referrals.update_one({"_id": referrer_id}, {"$set": {"unlocked": True}})
                    try:
                        await context.bot.send_message(
                            referrer_id,
                            "🎉 Aapka video unlock ho gaya! Use /start to get it."
                        )
                    except:
                        pass

    btn = InlineKeyboardMarkup(
        [[InlineKeyboardButton("📩 Get Video", callback_data="get_video")]]
    )

    await update.message.reply_text(
        "🥵 Welcome! Refer 1 user using your link to unlock the video.\n\n"
        f"🔗 Your link: https://t.me/{context.bot.username}?start={uid}",
        reply_markup=btn
    )

# --- GET VIDEO CALLBACK (Only if unlocked) ---

async def get_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    await query.answer()

    user = await db.referrals.find_one({"_id": uid})
    if not user or not user.get("unlocked"):
        await query.message.reply_text(
            "🔒 Video locked. Refer 1 user to unlock.\n"
            f"Your link: https://t.me/{context.bot.username}?start={uid}"
        )
        return

    await query.message.reply_text("✅ Here is your secret video link! (or send actual video here)")

# --- ADMIN: GET USER ID FILE ---

async def get_user_ids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID:
        return

    user_ids = load_user_ids()
    with open("user_ids.txt", "w") as f:
        f.write("\n".join(str(uid) for uid in user_ids))

    await update.message.reply_document(InputFile("user_ids.txt"))

# --- MAIN ---

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("get_userid", get_user_ids))
    app.add_handler(CallbackQueryHandler(get_video, pattern="get_video"))

    app.run_polling()

if __name__ == "__main__":
    main()
