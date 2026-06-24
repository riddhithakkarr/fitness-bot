#!/usr/bin/env python3
"""
Rocky Health v2.4 - Personalized for Ridhhi
- Vegetarian food database
- Calories (1600) + Protein goals only
- AI-powered macro deduction from grams
- Gym workout tracking (sets/reps/weights)
- Accountability: legs 2-3x/week, cardio 1x/week
- 90-day goal: lose 3kg
- Weekly weight check-ins
"""

import os
import sqlite3
import logging
from datetime import datetime, timedelta
from anthropic import Anthropic

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB_FILE = 'fitness_tracker.db'
BOT_VERSION = "2.4"
client = Anthropic()

# VEGETARIAN FOOD DATABASE - grams -> (calories, protein)
VEGETARIAN_FOODS = {
    # Proteins
    "paneer": (265, 25),  # per 100g
    "tofu": (76, 8),
    "tempeh": (193, 19),
    "seitan": (370, 25),
    "chickpeas": (210, 12),
    "lentils": (230, 18),
    "dal": (220, 15),
    "beans": (130, 9),
    "peas": (80, 6),
    
    # Grains
    "rice": (130, 2.7),  # per 100g
    "wheat": (340, 14),
    "oats": (150, 5),
    "bread": (79, 2.7),
    "pasta": (131, 5),
    "chapati": (80, 2.7),
    "idli": (95, 2),
    "dosa": (150, 4),
    
    # Vegetables
    "broccoli": (34, 2.8),
    "spinach": (23, 2.9),
    "carrot": (41, 0.9),
    "tomato": (18, 0.9),
    "onion": (40, 1.1),
    "potato": (77, 2),
    "cucumber": (16, 0.7),
    "bell pepper": (31, 1),
    "cabbage": (25, 1.3),
    
    # Fruits
    "banana": (89, 1.1),
    "apple": (95, 0.5),
    "orange": (47, 0.9),
    "mango": (60, 0.8),
    "berries": (57, 0.7),
    
    # Dairy
    "milk": (61, 3.2),  # per 100ml
    "yogurt": (100, 10),
    "cheese": (402, 25),
    "butter": (717, 0.7),
    
    # Nuts & Seeds
    "almonds": (579, 21),
    "peanuts": (567, 26),
    "seeds": (585, 20),
    
    # Others
    "egg": (155, 13),
    "honey": (304, 0.3),
    "oil": (884, 0),
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
                 (id INTEGER PRIMARY KEY, user_id INTEGER, date TEXT, exercise TEXT, sets INTEGER, reps INTEGER, weight REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS cardio
                 (id INTEGER PRIMARY KEY, user_id INTEGER, date TEXT, type TEXT, duration INTEGER, notes TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS goals
                 (id INTEGER PRIMARY KEY, user_id INTEGER, goal_type TEXT, target TEXT, deadline TEXT, current TEXT, created_date TEXT)''')
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
    
    c.execute("SELECT GROUP_CONCAT(exercise) FROM gym_workouts WHERE user_id=? AND date=?", (user_id, today))
    gym = c.fetchone()
    
    c.execute("SELECT GROUP_CONCAT(type) FROM cardio WHERE user_id=? AND date=?", (user_id, today))
    cardio = c.fetchone()
    
    conn.close()
    
    return {
        "calories": int(nut[0] or 0),
        "protein": round(nut[1] or 0, 1),
        "gym": gym[0] if gym[0] else None,
        "cardio": cardio[0] if cardio[0] else None,
    }

def get_weekly_accountability(user_id: int):
    """Check weekly accountability"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    
    # Leg workouts this week
    c.execute("SELECT COUNT(*) FROM gym_workouts WHERE user_id=? AND date >= ? AND exercise LIKE '%leg%'", 
             (user_id, week_ago))
    leg_count = c.fetchone()[0]
    
    # Any cardio this week
    c.execute("SELECT COUNT(*) FROM cardio WHERE user_id=? AND date >= ?", (user_id, week_ago))
    cardio_count = c.fetchone()[0]
    
    conn.close()
    
    return {
        "leg_workouts": leg_count,
        "cardio_sessions": cardio_count,
    }

def get_user_goals(user_id):
    """Get user settings"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT daily_calories, daily_protein FROM user_settings WHERE user_id=?", (user_id,))
    result = c.fetchone()
    conn.close()
    
    if result:
        return {"calories": result[0], "protein": result[1]}
    return {"calories": 1600, "protein": 100}

def log_food(user_id, food_name, grams):
    """Log food - AI will calculate calories and protein"""
    try:
        grams = int(grams)
        # Find matching food
        food_lower = food_name.lower()
        
        for food, (cal_per_100, protein_per_100) in VEGETARIAN_FOODS.items():
            if food in food_lower or food_lower in food:
                # Calculate for given grams
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
                
                return f"✅ Logged {grams}g {food_name} → {calories}cal | {protein}g protein"
        
        return None
    except:
        return None

def log_gym_workout(user_id, exercise, sets, reps, weight=None):
    """Log gym workout with sets/reps/weight"""
    try:
        sets = int(sets)
        reps = int(reps)
        weight = float(weight) if weight else None
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        c.execute("INSERT INTO gym_workouts (user_id, date, exercise, sets, reps, weight) VALUES (?, ?, ?, ?, ?, ?)",
                 (user_id, today, exercise, sets, reps, weight))
        conn.commit()
        conn.close()
        
        weight_str = f" @ {weight}kg" if weight else ""
        return f"✅ Logged {exercise}: {sets}x{reps}{weight_str}"
    except:
        return None

def log_cardio(user_id, cardio_type, duration):
    """Log cardio (steps/treadmill/incline/yoga/stretching)"""
    try:
        duration = int(duration)
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        c.execute("INSERT INTO cardio (user_id, date, type, duration) VALUES (?, ?, ?, ?)",
                 (user_id, today, cardio_type, duration))
        conn.commit()
        conn.close()
        
        return f"✅ Logged {cardio_type} for {duration}min"
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
        
        return f"✅ Logged weight: {w}kg"
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

def get_chat_history(user_id):
    """Get chat history"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT role, content FROM chat_history WHERE user_id=? ORDER BY id DESC LIMIT 10", (user_id,))
    messages = list(reversed(c.fetchall()))
    conn.close()
    return messages

async def get_ai_response(user_id, user_message):
    """Get AI response tailored to user"""
    stats = get_today_stats(user_id)
    goals = get_user_goals(user_id)
    accountability = get_weekly_accountability(user_id)
    chat_history = get_chat_history(user_id)
    
    context = f"""You are Rocky, a personal fitness coach for Ridhhi, a vegetarian.

RIDHHI'S GOALS:
- Daily: 1600 calories, high protein (aiming for 100g+)
- 90-day goal: Lose 3kg
- Leg workouts: 2-3 times per week (knee rehab + functional strength)
- Cardio: 4-5 times per week (steps/treadmill/incline/yoga/stretching)

TODAY'S PROGRESS:
- Calories: {stats['calories']}/1600
- Protein: {stats['protein']}g/100g
- Gym: {stats['gym'] or 'None yet'}
- Cardio: {stats['cardio'] or 'None yet'}

THIS WEEK'S ACCOUNTABILITY:
- Leg workouts: {accountability['leg_workouts']}/2-3 ✓
- Cardio sessions: {accountability['cardio_sessions']}/1+ ✓

FOOD DATABASE: Vegetarian only (paneer, tofu, lentils, chickpeas, dal, etc.)
When user gives grams of food, calculate calories and protein.

Be encouraging about her goals. Track leg workouts and cardio accountability.
Ask about weight once a week (Monday is good).
Celebrate progress toward 3kg loss in 90 days.
"""
    
    messages = []
    for role, content in chat_history:
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})
    
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        system=context,
        messages=messages
    )
    
    return response.content[0].text

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user message"""
    user_id = update.effective_user.id
    user_message = update.message.text
    
    await context.bot.send_chat_action(user_id, "typing")
    
    try:
        lower_msg = user_message.lower()
        logged_msg = ""
        
        # Parse food logging: "100g paneer" or "200g dal rice"
        import re
        food_match = re.search(r'(\d+)g?\s+([a-z\s]+)', lower_msg)
        if food_match:
            grams = food_match.group(1)
            food = food_match.group(2).strip()
            result = log_food(user_id, food, grams)
            if result:
                logged_msg = result + "\n"
        
        # Parse gym: "legs 4x8 40kg" or "chest 3x10"
        if any(x in lower_msg for x in ["leg", "back", "chest", "shoulder", "arm", "deadlift", "squat"]):
            # Try to extract: exercise, sets, reps, weight
            gym_match = re.search(r'(\d+)\s*x\s*(\d+)(?:\s+(\d+)(?:kg)?)?', lower_msg)
            if gym_match:
                sets = gym_match.group(1)
                reps = gym_match.group(2)
                weight = gym_match.group(3)
                exercise = lower_msg.split(gym_match.group(0))[0].strip()
                result = log_gym_workout(user_id, exercise, sets, reps, weight)
                if result:
                    logged_msg = result + "\n"
        
        # Parse cardio: "30min treadmill" or "45min yoga"
        cardio_match = re.search(r'(\d+)\s*min\s+([a-z\s]+)', lower_msg)
        if cardio_match:
            duration = cardio_match.group(1)
            cardio_type = cardio_match.group(2).strip()
            result = log_cardio(user_id, cardio_type, duration)
            if result:
                logged_msg = result + "\n"
        
        # Parse weight: "weight 62.5" or "62.5kg"
        if "weight" in lower_msg or "kg" in lower_msg:
            weight_match = re.search(r'(\d+\.?\d*)\s*kg?', lower_msg)
            if weight_match:
                weight = weight_match.group(1)
                result = log_weight(user_id, weight)
                if result:
                    logged_msg = result + "\n"
        
        # Get AI response
        ai_response = await get_ai_response(user_id, user_message)
        save_chat(user_id, "user", user_message)
        save_chat(user_id, "assistant", ai_response)
        
        response_text = logged_msg + ai_response
        await update.message.reply_text(response_text, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("Oops! Try again? 😊")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start"""
    await update.message.reply_text(
        f"🏋️ *Rocky Health v{BOT_VERSION}*\n\n"
        "Hey Ridhhi! Your personal coach is here.\n\n"
        "Just chat naturally:\n"
        "📝 \"100g paneer with rice\"\n"
        "💪 \"legs 4x8 40kg\"\n"
        "🏃 \"30min treadmill\"\n"
        "⚖️ \"weight 62.5\"\n"
        "📊 \"how am i doing?\"\n\n"
        "Let's crush your 3kg loss in 90 days! 💪",
        parse_mode="Markdown"
    )

async def send_morning_check(application):
    """Morning accountability check - 7am"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT DISTINCT user_id FROM user_settings")
        users = [row[0] for row in c.fetchall()]
        conn.close()
        
        for user_id in users:
            try:
                # Check what's needed
                accountability = get_weekly_accountability(user_id)
                today = datetime.now().strftime("%Y-%m-%d")
                
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                
                # Check today's status
                c.execute("SELECT COUNT(*) FROM cardio WHERE user_id=? AND date=?", (user_id, today))
                cardio_today = c.fetchone()[0] > 0
                
                c.execute("SELECT COUNT(*) FROM gym_workouts WHERE user_id=? AND date=?", (user_id, today))
                gym_today = c.fetchone()[0] > 0
                
                c.execute("SELECT COUNT(*) FROM gym_workouts WHERE user_id=? AND exercise LIKE '%leg%' AND date >= ?",
                         (user_id, (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")))
                leg_past_3 = c.fetchone()[0] > 0
                
                c.execute("SELECT COUNT(*) FROM cardio WHERE user_id=? AND date >= ?",
                         (user_id, (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")))
                cardio_past_2 = c.fetchone()[0] > 0
                
                conn.close()
                
                # Build message
                message = "🌅 *Good Morning!*\n\n"
                message += "📋 *Today's Checklist:*\n"
                
                if not cardio_today:
                    message += "• 🏃 Cardio - aim for 4-5 times this week\n"
                
                if not leg_past_3:
                    message += "• 💪 Leg workout - you need this for your rehab (2-3x/week)\n"
                
                message += "\n✅ Leg workouts this week: " + str(accountability['leg_workouts']) + "/2-3\n"
                message += "✅ Cardio this week: " + str(accountability['cardio_sessions']) + "/4-5\n"
                message += "\nYou've got this! 💪"
                
                await application.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Error sending morning check to {user_id}: {e}")
    except Exception as e:
        logger.error(f"Error in morning check: {e}")

async def send_leg_reminder(application):
    """Leg workout reminder - Wednesday"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT DISTINCT user_id FROM user_settings")
        users = [row[0] for row in c.fetchall()]
        conn.close()
        
        for user_id in users:
            try:
                accountability = get_weekly_accountability(user_id)
                if accountability['leg_workouts'] < 2:
                    await application.bot.send_message(
                        chat_id=user_id,
                        text="💪 Leg day reminder! Your knee rehab & functional strength work. Got time? 🦵"
                    )
            except:
                pass
    except:
        pass

async def post_init(application):
    """Setup scheduler"""
    scheduler = AsyncIOScheduler()
    
    # Daily 7am - morning accountability check
    scheduler.add_job(
        send_morning_check,
        CronTrigger(hour=7, minute=0),
        args=[application],
        id='morning_check'
    )
    
    # Wednesday 6pm - leg reminder
    scheduler.add_job(
        send_leg_reminder,
        CronTrigger(day_of_week=2, hour=18, minute=0),
        args=[application],
        id='leg_reminder'
    )
    
    scheduler.start()
    logger.info(f"✅ Rocky Health v{BOT_VERSION} - Personalized for Ridhhi!")

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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("🚀 Rocky Health v2.4 - Ready!")
    app.run_polling(allowed_updates=['message', 'callback_query'])

if __name__ == '__main__':
    init_db()
    main()
