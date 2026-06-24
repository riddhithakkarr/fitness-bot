#!/usr/bin/env python3
"""
Rocky Health v2.4 Final
- 7am: Good morning - log sleep?
- 11pm: Good night - log everything?
- Sunday: Full weekly review with goals + progress
- Notes: Add context (period, illness, etc.)
"""

import os
import sqlite3
import logging
from datetime import datetime, timedelta
from anthropic import Anthropic

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
client = Anthropic()

# VEGETARIAN FOOD DATABASE
VEGETARIAN_FOODS = {
    "paneer": (265, 25), "tofu": (76, 8), "tempeh": (193, 19), "seitan": (370, 25),
    "chickpeas": (210, 12), "lentils": (230, 18), "dal": (220, 15), "beans": (130, 9),
    "rice": (130, 2.7), "wheat": (340, 14), "oats": (150, 5), "bread": (79, 2.7),
    "pasta": (131, 5), "chapati": (80, 2.7), "idli": (95, 2), "dosa": (150, 4),
    "broccoli": (34, 2.8), "spinach": (23, 2.9), "carrot": (41, 0.9), "tomato": (18, 0.9),
    "onion": (40, 1.1), "potato": (77, 2), "cucumber": (16, 0.7), "bell pepper": (31, 1),
    "banana": (89, 1.1), "apple": (95, 0.5), "orange": (47, 0.9), "mango": (60, 0.8),
    "milk": (61, 3.2), "yogurt": (100, 10), "cheese": (402, 25),
    "almonds": (579, 21), "peanuts": (567, 26),
}

def init_db():
    """Initialize database"""
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
    c.execute('''CREATE TABLE IF NOT EXISTS chat_history
                 (id INTEGER PRIMARY KEY, user_id INTEGER, role TEXT, content TEXT, timestamp TEXT)''')
    
    conn.commit()
    conn.close()

def get_today_stats(user_id: int):
    """Get today's stats"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    
    c.execute("SELECT SUM(calories), SUM(protein) FROM nutrition WHERE user_id=? AND date=?", 
             (user_id, today))
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

def get_weekly_stats(user_id: int):
    """Get weekly goal achievement"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    today = datetime.now().strftime("%Y-%m-%d")
    
    goals = get_user_goals(user_id)
    
    # Leg workouts
    c.execute("SELECT COUNT(*) FROM gym_workouts WHERE user_id=? AND date BETWEEN ? AND ? AND exercise_type='leg'", 
             (user_id, week_ago, today))
    leg_count = c.fetchone()[0]
    
    # Upper body workouts
    c.execute("SELECT COUNT(*) FROM gym_workouts WHERE user_id=? AND date BETWEEN ? AND ? AND exercise_type='upper'", 
             (user_id, week_ago, today))
    upper_count = c.fetchone()[0]
    
    # Cardio sessions
    c.execute("SELECT COUNT(DISTINCT date) FROM cardio WHERE user_id=? AND date BETWEEN ? AND ?", 
             (user_id, week_ago, today))
    cardio_count = c.fetchone()[0]
    
    # Days hit calorie goal
    c.execute("""SELECT COUNT(DISTINCT date) FROM (
                 SELECT date FROM nutrition WHERE user_id=? AND date BETWEEN ? AND ? 
                 GROUP BY date HAVING SUM(calories) >= ?)""", 
             (user_id, week_ago, today, goals['calories']))
    cal_days = c.fetchone()[0]
    
    # Days hit protein goal
    c.execute("""SELECT COUNT(DISTINCT date) FROM (
                 SELECT date FROM nutrition WHERE user_id=? AND date BETWEEN ? AND ? 
                 GROUP BY date HAVING SUM(protein) >= ?)""", 
             (user_id, week_ago, today, goals['protein']))
    protein_days = c.fetchone()[0]
    
    # Weight progress (from first day of week to today)
    c.execute("SELECT weight FROM weights WHERE user_id=? AND date=?", (user_id, week_ago))
    week_start_weight = c.fetchone()
    c.execute("SELECT weight FROM weights WHERE user_id=? AND date=? ORDER BY date DESC LIMIT 1", (user_id, today))
    current_weight = c.fetchone()
    
    weight_change = None
    if week_start_weight and current_weight:
        weight_change = round(week_start_weight[0] - current_weight[0], 2)
    
    conn.close()
    
    return {
        "leg_workouts": leg_count,
        "upper_workouts": upper_count,
        "cardio_sessions": cardio_count,
        "calories_days": cal_days,
        "protein_days": protein_days,
        "weight_change": weight_change,
    }

def get_90day_progress(user_id: int):
    """Get 90-day progress"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Get oldest and newest weight
    c.execute("SELECT weight FROM weights WHERE user_id=? ORDER BY date ASC LIMIT 1", (user_id,))
    start_weight = c.fetchone()
    c.execute("SELECT weight FROM weights WHERE user_id=? ORDER BY date DESC LIMIT 1", (user_id,))
    current_weight = c.fetchone()
    
    conn.close()
    
    if start_weight and current_weight:
        loss = round(start_weight[0] - current_weight[0], 2)
        progress_pct = int((loss / 3) * 100)
        return {"loss": loss, "progress_pct": min(progress_pct, 100), "current": current_weight[0]}
    return None

def get_user_goals(user_id):
    """Get goals"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT daily_calories, daily_protein FROM user_settings WHERE user_id=?", (user_id,))
    result = c.fetchone()
    conn.close()
    
    if result:
        return {"calories": result[0], "protein": result[1]}
    return {"calories": 1600, "protein": 100}

def log_food(user_id, food_name, grams):
    """Log food"""
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

def log_gym_workout(user_id, exercise_type, exercise, sets, reps, weight=None):
    """Log gym workout"""
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
    """Log cardio"""
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
    """Log sleep"""
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
    """Log weight"""
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
    """Add note"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        c.execute("INSERT INTO notes (user_id, date, note) VALUES (?, ?, ?)",
                 (user_id, today, note))
        conn.commit()
        conn.close()
        
        return f"✅ Note added: {note}"
    except:
        return None

def save_chat(user_id, role, content):
    """Save chat"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    timestamp = datetime.now().isoformat()
    c.execute("INSERT INTO chat_history (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
             (user_id, role, content, timestamp))
    conn.commit()
    conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start - show today's summary + buttons"""
    user_id = update.effective_user.id
    stats = get_today_stats(user_id)
    goals = get_user_goals(user_id)
    
    summary = f"📊 *Today's Summary*\n\n"
    summary += f"🍎 Calories: {stats['calories']}/{goals['calories']}\n"
    summary += f"💪 Protein: {stats['protein']}g/{goals['protein']}g\n"
    summary += f"🏃 Cardio: {stats['cardio_min']}min\n"
    summary += f"🏋️ Gym: {stats['gym_sessions']} sessions"
    
    keyboard = [
        [InlineKeyboardButton("🍎 Log Food", callback_data="log_food")],
        [InlineKeyboardButton("💪 Log Leg", callback_data="log_leg"), InlineKeyboardButton("🦾 Log Upper", callback_data="log_upper")],
        [InlineKeyboardButton("🏃 Log Cardio", callback_data="log_cardio")],
        [InlineKeyboardButton("😴 Log Sleep", callback_data="log_sleep"), InlineKeyboardButton("⚖️ Log Weight", callback_data="log_weight")],
        [InlineKeyboardButton("📝 Add Note", callback_data="add_note")],
    ]
    
    await update.message.reply_text(
        f"🏋️ *Rocky Health v{BOT_VERSION}*\n\n{summary}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle buttons"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "log_food":
        await query.edit_message_text("What? (e.g., '100g paneer')")
        context.user_data['state'] = 'food_input'
    elif query.data == "log_leg":
        await query.edit_message_text("Leg workout? (e.g., 'squat 4x8 40kg')")
        context.user_data['state'] = 'leg_input'
    elif query.data == "log_upper":
        await query.edit_message_text("Upper body? (e.g., 'chest 3x10 25kg')")
        context.user_data['state'] = 'upper_input'
    elif query.data == "log_cardio":
        await query.edit_message_text("Cardio? (e.g., '30min treadmill')")
        context.user_data['state'] = 'cardio_input'
    elif query.data == "log_sleep":
        await query.edit_message_text("Hours slept? (e.g., '7.5')")
        context.user_data['state'] = 'sleep_input'
    elif query.data == "log_weight":
        await query.edit_message_text("Weight? (e.g., '62.5')")
        context.user_data['state'] = 'weight_input'
    elif query.data == "add_note":
        await query.edit_message_text("Note? (e.g., 'got period - taking it easy')")
        context.user_data['state'] = 'note_input'

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text input"""
    user_id = update.effective_user.id
    user_message = update.message.text
    state = context.user_data.get('state')
    
    logged_msg = ""
    
    try:
        if state == 'food_input':
            import re
            match = re.search(r'(\d+)g?\s+([a-z\s]+)', user_message.lower())
            if match:
                grams = match.group(1)
                food = match.group(2).strip()
                result = log_food(user_id, food, grams)
                if result:
                    logged_msg = result + "\n"
            context.user_data['state'] = None
        
        elif state == 'leg_input':
            import re
            match = re.search(r'(\d+)\s*x\s*(\d+)(?:\s+(\d+)(?:kg)?)?', user_message)
            if match:
                sets = match.group(1)
                reps = match.group(2)
                weight = match.group(3)
                exercise = user_message[:match.start()].strip()
                result = log_gym_workout(user_id, 'leg', exercise, sets, reps, weight)
                if result:
                    logged_msg = result + "\n"
            context.user_data['state'] = None
        
        elif state == 'upper_input':
            import re
            match = re.search(r'(\d+)\s*x\s*(\d+)(?:\s+(\d+)(?:kg)?)?', user_message)
            if match:
                sets = match.group(1)
                reps = match.group(2)
                weight = match.group(3)
                exercise = user_message[:match.start()].strip()
                result = log_gym_workout(user_id, 'upper', exercise, sets, reps, weight)
                if result:
                    logged_msg = result + "\n"
            context.user_data['state'] = None
        
        elif state == 'cardio_input':
            import re
            match = re.search(r'(\d+)\s*min\s+([a-z\s]+)', user_message.lower())
            if match:
                duration = match.group(1)
                cardio_type = match.group(2).strip()
                result = log_cardio(user_id, cardio_type, duration)
                if result:
                    logged_msg = result + "\n"
            context.user_data['state'] = None
        
        elif state == 'sleep_input':
            result = log_sleep(user_id, user_message)
            if result:
                logged_msg = result + "\n"
            context.user_data['state'] = None
        
        elif state == 'weight_input':
            result = log_weight(user_id, user_message)
            if result:
                logged_msg = result + "\n"
            context.user_data['state'] = None
        
        elif state == 'note_input':
            result = add_note(user_id, user_message)
            if result:
                logged_msg = result + "\n"
            context.user_data['state'] = None
        
        await update.message.reply_text(logged_msg if logged_msg else "Got it! 💚")
        
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("Try again? 😊")

async def send_morning_sleep_reminder(application):
    """7am - Good morning, log sleep?"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT DISTINCT user_id FROM user_settings")
        users = [row[0] for row in c.fetchall()]
        conn.close()
        
        for user_id in users:
            try:
                await application.bot.send_message(
                    chat_id=user_id,
                    text="🌅 Good morning! Did you log last night's sleep? Click [😴 Log Sleep] 💤"
                )
            except:
                pass
    except:
        pass

async def send_night_reminder(application):
    """11pm - Good night, log everything?"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT DISTINCT user_id FROM user_settings")
        users = [row[0] for row in c.fetchall()]
        conn.close()
        
        for user_id in users:
            try:
                await application.bot.send_message(
                    chat_id=user_id,
                    text="🌙 Good night! Log any meals/workouts you missed? Type or click buttons 💚"
                )
            except:
                pass
    except:
        pass

async def send_sunday_review(application):
    """Sunday 8am - Weekly review"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT DISTINCT user_id FROM user_settings")
        users = [row[0] for row in c.fetchall()]
        conn.close()
        
        for user_id in users:
            try:
                stats = get_weekly_stats(user_id)
                progress = get_90day_progress(user_id)
                
                message = "📊 *Weekly Review*\n\n"
                message += f"💪 Leg workouts: {stats['leg_workouts']}/2 "
                message += "✅\n" if stats['leg_workouts'] >= 2 else "\n"
                message += f"🦾 Upper body: {stats['upper_workouts']}/1 "
                message += "✅\n" if stats['upper_workouts'] >= 1 else "\n"
                message += f"🏃 Cardio: {stats['cardio_sessions']}/4 "
                message += "✅\n" if stats['cardio_sessions'] >= 4 else "\n"
                message += f"🍎 Calories goal: {stats['calories_days']}/6 days\n"
                message += f"💪 Protein goal: {stats['protein_days']}/6 days\n"
                
                if progress:
                    bar = "█" * int(progress['progress_pct']/10) + "░" * (10 - int(progress['progress_pct']/10))
                    message += f"\n🎯 *90-Day Goal: Lose 3kg*\n"
                    message += f"{bar} {progress['progress_pct']}%\n"
                    message += f"Lost: {progress['loss']}kg | Current: {progress['current']}kg"
                
                message += f"\n\n📝 Click [⚖️ Log Weight] to update!"
                
                await application.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Error in Sunday review: {e}")
    except:
        pass

async def post_init(application):
    """Setup scheduler"""
    scheduler = AsyncIOScheduler()
    
    # 7am - morning sleep reminder
    scheduler.add_job(
        send_morning_sleep_reminder,
        CronTrigger(hour=7, minute=0),
        args=[application],
        id='morning_reminder'
    )
    
    # 11pm - night reminder
    scheduler.add_job(
        send_night_reminder,
        CronTrigger(hour=23, minute=0),
        args=[application],
        id='night_reminder'
    )
    
    # Sunday 8am - weekly review
    scheduler.add_job(
        send_sunday_review,
        CronTrigger(day_of_week=6, hour=8, minute=0),
        args=[application],
        id='sunday_review'
    )
    
    scheduler.start()
    logger.info(f"✅ Rocky Health v{BOT_VERSION}!")

def main():
    """Start bot"""
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        logger.error("No token!")
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
