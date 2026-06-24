#!/usr/bin/env python3
"""
Rocky Health v2.4 Final - FIXED
- Menu stays visible
- Custom food logging: "salad 500 calories 10g protein"
- Back button to return to menu
- Quick logging with buttons
"""

import os
import sqlite3
import logging
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB_FILE = 'fitness_tracker.db'
BOT_VERSION = "2.4"

# VEGETARIAN FOOD DATABASE
VEGETARIAN_FOODS = {
    "paneer": (265, 25), "tofu": (76, 8), "tempeh": (193, 19), "seitan": (370, 25),
    "chickpeas": (210, 12), "lentils": (230, 18), "dal": (220, 15), "beans": (130, 9),
    "rice": (130, 2.7), "wheat": (340, 14), "oats": (150, 5), "bread": (79, 2.7),
    "pasta": (131, 5), "chapati": (80, 2.7), "idli": (95, 2), "dosa": (150, 4),
    "broccoli": (34, 2.8), "spinach": (23, 2.9), "carrot": (41, 0.9), "tomato": (18, 0.9),
    "banana": (89, 1.1), "apple": (95, 0.5), "orange": (47, 0.9), "mango": (60, 0.8),
    "milk": (61, 3.2), "yogurt": (100, 10), "cheese": (402, 25),
    "almonds": (579, 21), "peanuts": (567, 26),
}

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS weights
                 (id INTEGER PRIMARY KEY, user_id INTEGER, date TEXT, weight REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS nutrition
                 (id INTEGER PRIMARY KEY, user_id INTEGER, date TEXT, time TEXT, food TEXT, grams INTEGER, calories INTEGER, protein REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS gym_workouts
                 (id INTEGER PRIMARY KEY, user_id INTEGER, date TEXT, exercise_type TEXT, exercise TEXT, sets INTEGER, reps INTEGER, weight REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS cardio
                 (id INTEGER PRIMARY KEY, user_id INTEGER, date TEXT, type TEXT, duration INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS sleep
                 (id INTEGER PRIMARY KEY, user_id INTEGER, date TEXT, hours REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS notes
                 (id INTEGER PRIMARY KEY, user_id INTEGER, date TEXT, note TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_settings
                 (id INTEGER PRIMARY KEY, user_id INTEGER, daily_calories INTEGER, daily_protein REAL)''')
    
    conn.commit()
    conn.close()

def get_today_stats(user_id: int):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    
    c.execute("SELECT SUM(calories), SUM(protein) FROM nutrition WHERE user_id=? AND date=?", (user_id, today))
    nut = c.fetchone()
    
    c.execute("SELECT SUM(duration) FROM cardio WHERE user_id=? AND date=?", (user_id, today))
    cardio = c.fetchone()[0] or 0
    
    c.execute("SELECT COUNT(*) FROM gym_workouts WHERE user_id=? AND date=?", (user_id, today))
    gym = c.fetchone()[0]
    
    conn.close()
    
    return {
        "calories": int(nut[0] or 0),
        "protein": round(nut[1] or 0, 1),
        "cardio_min": int(cardio),
        "gym_sessions": gym,
    }

def get_user_goals(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT daily_calories, daily_protein FROM user_settings WHERE user_id=?", (user_id,))
    result = c.fetchone()
    conn.close()
    
    if result:
        return {"calories": result[0], "protein": result[1]}
    return {"calories": 1600, "protein": 100}

def log_food(user_id, food_name, grams):
    try:
        grams = int(grams)
        food_lower = food_name.lower()
        
        for food, (cal_per_100, protein_per_100) in VEGETARIAN_FOODS.items():
            if food in food_lower or food_lower in food:
                calories = int((cal_per_100 / 100) * grams)
                protein = round((protein_per_100 / 100) * grams, 1)
                
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                today = datetime.now().strftime("%Y-%m-%d")
                time = datetime.now().strftime("%H:%M")
                c.execute("INSERT INTO nutrition (user_id, date, time, food, grams, calories, protein) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (user_id, today, time, food_name, grams, calories, protein))
                conn.commit()
                conn.close()
                
                return f"✅ {grams}g {food_name} → {calories}cal | {protein}g protein"
        return None
    except:
        return None

def log_food_custom(user_id, food_name, calories, protein):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        time = datetime.now().strftime("%H:%M")
        c.execute("INSERT INTO nutrition (user_id, date, time, food, grams, calories, protein) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (user_id, today, time, food_name, 0, int(calories), float(protein)))
        conn.commit()
        conn.close()
        return f"✅ {food_name} → {int(calories)}cal | {protein}g protein"
    except:
        return None

def log_gym_workout(user_id, exercise_type, exercise, sets, reps, weight=None):
    try:
        sets = int(sets)
        reps = int(reps)
        weight = float(weight) if weight else None
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        c.execute("INSERT INTO gym_workouts (user_id, date, exercise_type, exercise, sets, reps, weight) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (user_id, today, exercise_type, exercise, sets, reps, weight))
        conn.commit()
        conn.close()
        
        weight_str = f" @ {weight}kg" if weight else ""
        return f"✅ {exercise}: {sets}x{reps}{weight_str}"
    except:
        return None

def log_cardio(user_id, cardio_type, duration):
    try:
        duration = int(duration)
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        c.execute("INSERT INTO cardio (user_id, date, type, duration) VALUES (?, ?, ?, ?)",
                 (user_id, today, cardio_type, duration))
        conn.commit()
        conn.close()
        return f"✅ {cardio_type} for {duration}min"
    except:
        return None

def log_sleep(user_id, hours):
    try:
        h = float(hours)
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        c.execute("INSERT INTO sleep (user_id, date, hours) VALUES (?, ?, ?)",
                 (user_id, yesterday, h))
        conn.commit()
        conn.close()
        return f"✅ {h}h sleep"
    except:
        return None

def log_weight(user_id, weight):
    try:
        w = float(weight)
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        c.execute("INSERT INTO weights (user_id, date, weight) VALUES (?, ?, ?)",
                 (user_id, today, w))
        conn.commit()
        conn.close()
        return f"✅ Weight: {w}kg"
    except:
        return None

def add_note(user_id, note):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        c.execute("INSERT INTO notes (user_id, date, note) VALUES (?, ?, ?)",
                 (user_id, today, note))
        conn.commit()
        conn.close()
        return f"✅ Note: {note}"
    except:
        return None

def get_menu_buttons():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🍎 Log Food", callback_data="log_food")],
        [InlineKeyboardButton("💪 Log Leg", callback_data="log_leg"), InlineKeyboardButton("🦾 Log Upper", callback_data="log_upper")],
        [InlineKeyboardButton("🏃 Log Cardio", callback_data="log_cardio")],
        [InlineKeyboardButton("😴 Log Sleep", callback_data="log_sleep"), InlineKeyboardButton("⚖️ Log Weight", callback_data="log_weight")],
        [InlineKeyboardButton("📝 Add Note", callback_data="add_note")],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    stats = get_today_stats(user_id)
    goals = get_user_goals(user_id)
    
    summary = f"📊 *Today's Summary*\n\n"
    summary += f"🍎 Calories: {stats['calories']}/{goals['calories']}\n"
    summary += f"💪 Protein: {stats['protein']}g/{goals['protein']}g\n"
    summary += f"🏃 Cardio: {stats['cardio_min']}min\n"
    summary += f"🏋️ Gym: {stats['gym_sessions']} sessions"
    
    await update.message.reply_text(
        f"🏋️ *Rocky Health v{BOT_VERSION}*\n\n{summary}",
        reply_markup=get_menu_buttons(),
        parse_mode="Markdown"
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "log_food":
        context.user_data['state'] = 'food_input'
        await query.edit_message_text(
            text="What did you eat?\n\n*Format options:*\n• '100g paneer'\n• 'salad 500 calories 10g protein'",
            reply_markup=get_menu_buttons(),
            parse_mode="Markdown"
        )
    elif query.data == "log_leg":
        context.user_data['state'] = 'leg_input'
        await query.edit_message_text("Leg? (e.g., 'squat 4x8 40kg')", reply_markup=get_menu_buttons())
    elif query.data == "log_upper":
        context.user_data['state'] = 'upper_input'
        await query.edit_message_text("Upper? (e.g., 'chest 3x10 25kg')", reply_markup=get_menu_buttons())
    elif query.data == "log_cardio":
        context.user_data['state'] = 'cardio_input'
        await query.edit_message_text("Cardio? (e.g., '30min treadmill')", reply_markup=get_menu_buttons())
    elif query.data == "log_sleep":
        context.user_data['state'] = 'sleep_input'
        await query.edit_message_text("Hours? (e.g., '7.5')", reply_markup=get_menu_buttons())
    elif query.data == "log_weight":
        context.user_data['state'] = 'weight_input'
        await query.edit_message_text("Weight? (e.g., '62.5')", reply_markup=get_menu_buttons())
    elif query.data == "add_note":
        context.user_data['state'] = 'note_input'
        await query.edit_message_text("Note? (e.g., 'got period')", reply_markup=get_menu_buttons())

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg = update.message.text
    state = context.user_data.get('state')
    
    if not state:
        return
    
    logged = ""
    
    try:
        if state == 'food_input':
            import re
            # Try custom format: "salad 500 calories 10g protein"
            custom = re.search(r'(.+?)\s+(\d+)\s*(?:cal|calories).*?(\d+)\s*(?:g\s*)?protein', msg.lower())
            if custom:
                food = msg[:msg.lower().index(str(custom.group(2)))].strip()
                logged = log_food_custom(user_id, food, custom.group(2), custom.group(3))
            else:
                # Try grams: "100g paneer"
                grams = re.search(r'(\d+)g?\s+([a-z\s]+)', msg.lower())
                if grams:
                    logged = log_food(user_id, grams.group(2).strip(), grams.group(1))
                else:
                    logged = "❌ Format: '100g paneer' OR 'salad 500 calories 10g protein'"
        
        elif state == 'leg_input':
            import re
            match = re.search(r'(\d+)\s*x\s*(\d+)(?:\s+(\d+)(?:kg)?)?', msg)
            if match:
                ex = msg[:match.start()].strip()
                logged = log_gym_workout(user_id, 'leg', ex, match.group(1), match.group(2), match.group(3))
        
        elif state == 'upper_input':
            import re
            match = re.search(r'(\d+)\s*x\s*(\d+)(?:\s+(\d+)(?:kg)?)?', msg)
            if match:
                ex = msg[:match.start()].strip()
                logged = log_gym_workout(user_id, 'upper', ex, match.group(1), match.group(2), match.group(3))
        
        elif state == 'cardio_input':
            import re
            match = re.search(r'(\d+)\s*min\s+([a-z\s]+)', msg.lower())
            if match:
                logged = log_cardio(user_id, match.group(2).strip(), match.group(1))
        
        elif state == 'sleep_input':
            logged = log_sleep(user_id, msg)
        
        elif state == 'weight_input':
            logged = log_weight(user_id, msg)
        
        elif state == 'note_input':
            logged = add_note(user_id, msg)
        
        context.user_data['state'] = None
        
        if logged:
            await update.message.reply_text(logged)
    
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("Error! Try again? 😊")

async def send_morning_sleep_reminder(application):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT DISTINCT user_id FROM user_settings")
        users = [row[0] for row in c.fetchall()]
        conn.close()
        
        for uid in users:
            try:
                await application.bot.send_message(uid, "🌅 Good morning! Log last night's sleep?")
            except:
                pass
    except:
        pass

async def send_night_reminder(application):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT DISTINCT user_id FROM user_settings")
        users = [row[0] for row in c.fetchall()]
        conn.close()
        
        for uid in users:
            try:
                await application.bot.send_message(uid, "🌙 Good night! Log anything you missed?")
            except:
                pass
    except:
        pass

async def post_init(application):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_morning_sleep_reminder, CronTrigger(hour=7, minute=0), args=[application], id='morning')
    scheduler.add_job(send_night_reminder, CronTrigger(hour=23, minute=0), args=[application], id='night')
    scheduler.start()
    logger.info(f"✅ Rocky Health v{BOT_VERSION}!")

def main():
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        return
    
    init_db()
    app = Application.builder().token(token).build()
    app.post_init = post_init
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("🚀 Rocky Health v2.4 Final!")
    app.run_polling(allowed_updates=['message', 'callback_query'])

if __name__ == '__main__':
    init_db()
    main()
