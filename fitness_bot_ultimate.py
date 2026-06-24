#!/usr/bin/env python3
"""
Ultimate Fitness Tracker Bot
- Macro tracking (protein, carbs, fat)
- Weekly progress reports
- 75-90 day goal roadmap with checkmarks
- Complete fitness management
- Update notifications
"""

import os
import sqlite3
import logging
from datetime import datetime, timedelta
import json
from statistics import mean
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB_FILE = 'fitness_tracker.db'

# Version and updates
BOT_VERSION = "2.2"
LATEST_UPDATES = [
    {
        "version": "2.2",
        "date": "Today",
        "changes": [
            "✅ Auto-broadcast updates to all users",
            "✅ Daily reminders (7am & 9pm)",
            "✅ Ask what you want to track today",
        ]
    },
    {
        "version": "2.1",
        "date": "Yesterday",
        "changes": [
            "✅ Fixed back button navigation",
            "✅ Added update notification system",
            "✅ Better error handling",
        ]
    },
    {
        "version": "2.0",
        "date": "2 days ago",
        "changes": [
            "✅ Added macro tracking (protein/carbs/fat)",
            "✅ Added weekly progress reports",
            "✅ Added 75-day roadmap with milestones",
        ]
    },
]

# Foods with full macro info: name -> (calories, protein, carbs, fat)
FOODS_WITH_MACROS = {
    "chicken breast": (165, 31, 0, 3.6),
    "rice": (130, 2.7, 28, 0.3),
    "broccoli": (34, 2.8, 7, 0.4),
    "banana": (89, 1.1, 23, 0.3),
    "apple": (95, 0.5, 25, 0.3),
    "egg": (70, 6, 1.1, 5),
    "pasta": (131, 5, 25, 1.1),
    "pizza": (285, 12, 36, 10),
    "burger": (354, 15, 35, 17),
    "fries": (365, 3.4, 48, 17),
    "salad": (50, 3, 10, 0.5),
    "milk": (61, 3.2, 4.8, 3.3),
    "yogurt": (100, 10, 3.5, 0),
    "bread": (79, 2.7, 14, 1),
    "peanut butter": (188, 8, 7, 16),
    "protein shake": (120, 25, 2, 1),
    "oats": (150, 5, 27, 3),
    "almonds": (579, 21, 22, 50),
    "coffee": (2, 0, 0, 0),
    "tea": (1, 0, 0, 0),
    "coke": (140, 0, 39, 0),
    "juice": (120, 1, 30, 0),
    "donut": (250, 3, 33, 12),
    "chocolate": (500, 8, 60, 30),
    "ice cream": (200, 4, 25, 10),
    "idli": (95, 2, 22, 0),
    "dosa": (150, 4, 30, 2),
    "chapati": (80, 2.7, 15, 0.5),
    "dal": (120, 8, 20, 2),
}

def init_db():
    """Initialize database"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS weights
                 (id INTEGER PRIMARY KEY, user_id INTEGER, date TEXT, weight REAL, notes TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS nutrition
                 (id INTEGER PRIMARY KEY, user_id INTEGER, date TEXT, time TEXT, food TEXT, calories INTEGER, protein REAL, carbs REAL, fat REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS workouts
                 (id INTEGER PRIMARY KEY, user_id INTEGER, date TEXT, time TEXT, exercise TEXT, duration INTEGER, calories INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS steps
                 (id INTEGER PRIMARY KEY, user_id INTEGER, date TEXT, steps INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS sleep
                 (id INTEGER PRIMARY KEY, user_id INTEGER, date TEXT, hours REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_settings
                 (id INTEGER PRIMARY KEY, user_id INTEGER, daily_calories INTEGER, daily_protein REAL, daily_carbs REAL, daily_fat REAL, goal_weight REAL, goal_days INTEGER, start_date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS roadmap_milestones
                 (id INTEGER PRIMARY KEY, user_id INTEGER, day_number INTEGER, milestone TEXT, completed INTEGER, date_completed TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_versions
                 (id INTEGER PRIMARY KEY, user_id INTEGER, last_seen_version TEXT)''')
    
    conn.commit()
    conn.close()

def get_user_seen_version(user_id):
    """Get last version user saw"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT last_seen_version FROM user_versions WHERE user_id=?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def set_user_seen_version(user_id, version):
    """Save version user has seen"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO user_versions (user_id, last_seen_version) VALUES (?, ?)", (user_id, version))
    conn.commit()
    conn.close()

def get_user_goals(user_id):
    """Get user settings"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT daily_calories, daily_protein, daily_carbs, daily_fat, goal_weight, goal_days, start_date FROM user_settings WHERE user_id=?", (user_id,))
    result = c.fetchone()
    conn.close()
    
    if result:
        return {
            "calories": result[0] or 2000,
            "protein": result[1] or 100,
            "carbs": result[2] or 250,
            "fat": result[3] or 65,
            "goal_weight": result[4],
            "goal_days": result[5] or 75,
            "start_date": result[6],
        }
    return {
        "calories": 2000,
        "protein": 100,
        "carbs": 250,
        "fat": 65,
        "goal_weight": None,
        "goal_days": 75,
        "start_date": None,
    }

def get_today_full_stats(user_id: int):
    """Get comprehensive today stats with macros"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        
        # Nutrition totals
        c.execute("SELECT SUM(calories), SUM(protein), SUM(carbs), SUM(fat), COUNT(*) FROM nutrition WHERE user_id=? AND date=?", 
                 (user_id, today))
        nut_result = c.fetchone()
        
        # Workouts
        c.execute("SELECT SUM(calories), COUNT(*) FROM workouts WHERE user_id=? AND date=?", (user_id, today))
        work_result = c.fetchone()
        
        # Steps
        c.execute("SELECT steps FROM steps WHERE user_id=? AND date=?", (user_id, today))
        steps_result = c.fetchone()
        
        # Sleep
        c.execute("SELECT hours FROM sleep WHERE user_id=? AND date=?", (user_id, today))
        sleep_result = c.fetchone()
        
        # Weight
        c.execute("SELECT weight FROM weights WHERE user_id=? ORDER BY date DESC LIMIT 1", (user_id,))
        weight_result = c.fetchone()
        
        conn.close()
        
        goals = get_user_goals(user_id)
        
        return {
            "calories_consumed": int(nut_result[0] or 0),
            "protein": round(nut_result[1] or 0, 1),
            "carbs": round(nut_result[2] or 0, 1),
            "fat": round(nut_result[3] or 0, 1),
            "meals_logged": nut_result[4] or 0,
            "calories_burned": int(work_result[0] or 0),
            "workouts": work_result[1] or 0,
            "steps": steps_result[0] if steps_result else 0,
            "sleep": sleep_result[0] if sleep_result else 0,
            "weight": weight_result[0] if weight_result else None,
            "goals": goals,
        }
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return {}

def get_weekly_report(user_id: int):
    """Get last 7 days stats"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        
        # Weekly nutrition
        c.execute("""SELECT AVG(total_cal), AVG(total_protein), AVG(total_carbs), AVG(total_fat)
                     FROM (SELECT date, SUM(calories) as total_cal, SUM(protein) as total_protein, 
                                  SUM(carbs) as total_carbs, SUM(fat) as total_fat 
                           FROM nutrition WHERE user_id=? AND date >= ?
                           GROUP BY date)""", (user_id, week_ago))
        nut_avg = c.fetchone()
        
        # Weekly weight change
        c.execute("SELECT weight FROM weights WHERE user_id=? ORDER BY date DESC LIMIT 2", (user_id,))
        weights = [row[0] for row in c.fetchall()]
        weight_change = weights[1] - weights[0] if len(weights) == 2 else 0
        
        # Weekly workouts
        c.execute("SELECT COUNT(*) FROM workouts WHERE user_id=? AND date >= ?", (user_id, week_ago))
        workouts_count = c.fetchone()[0]
        
        # Weekly steps average
        c.execute("SELECT AVG(steps) FROM steps WHERE user_id=? AND date >= ?", (user_id, week_ago))
        avg_steps = c.fetchone()[0] or 0
        
        # Weekly sleep average
        c.execute("SELECT AVG(hours) FROM sleep WHERE user_id=? AND date >= ?", (user_id, week_ago))
        avg_sleep = c.fetchone()[0] or 0
        
        conn.close()
        
        return {
            "avg_calories": int(nut_avg[0] or 0),
            "avg_protein": round(nut_avg[1] or 0, 1),
            "avg_carbs": round(nut_avg[2] or 0, 1),
            "avg_fat": round(nut_avg[3] or 0, 1),
            "weight_change": round(weight_change, 2),
            "workouts": workouts_count,
            "avg_steps": int(avg_steps),
            "avg_sleep": round(avg_sleep, 1),
        }
    except Exception as e:
        logger.error(f"Error getting weekly report: {e}")
        return {}

def get_roadmap_progress(user_id: int):
    """Get 75-90 day roadmap progress"""
    goals = get_user_goals(user_id)
    
    if not goals["start_date"]:
        return None
    
    try:
        start = datetime.strptime(goals["start_date"], "%Y-%m-%d")
        days_elapsed = (datetime.now() - start).days
        total_days = goals["goal_days"]
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        # Get completed milestones
        c.execute("SELECT day_number, milestone, completed FROM roadmap_milestones WHERE user_id=? ORDER BY day_number", (user_id,))
        milestones = c.fetchall()
        
        conn.close()
        
        completed = sum(1 for m in milestones if m[2] == 1)
        
        return {
            "days_elapsed": days_elapsed,
            "total_days": total_days,
            "progress_pct": int((days_elapsed / total_days) * 100),
            "milestones": milestones,
            "completed": completed,
            "total_milestones": len(milestones),
        }
    except Exception as e:
        logger.error(f"Error in roadmap: {e}")
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    user_id = update.effective_user.id
    
    # Check if user has seen latest update (from database)
    seen_version = get_user_seen_version(user_id)
    
    # Show update notification if new version
    if seen_version != BOT_VERSION:
        latest = LATEST_UPDATES[0]
        update_msg = f"🆕 *Bot Updated to v{BOT_VERSION}!*\n\n"
        update_msg += f"*What's New:*\n"
        for change in latest['changes']:
            update_msg += f"{change}\n"
        update_msg += f"\nUse /updates to see all changes"
        
        await update.message.reply_text(update_msg, parse_mode="Markdown")
        set_user_seen_version(user_id, BOT_VERSION)
    
    keyboard = [
        [InlineKeyboardButton("📊 Today Summary", callback_data="today")],
        [InlineKeyboardButton("📈 Weekly Report", callback_data="weekly")],
        [InlineKeyboardButton("🎯 75-Day Roadmap", callback_data="roadmap")],
        [InlineKeyboardButton("🍎 Log Food", callback_data="log_food")],
        [InlineKeyboardButton("🏋️ Log Workout", callback_data="log_workout")],
        [InlineKeyboardButton("👟 Log Steps", callback_data="log_steps")],
        [InlineKeyboardButton("😴 Log Sleep", callback_data="log_sleep")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings")],
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🏋️ *Ultimate Fitness Tracker v" + BOT_VERSION + "*\n\n"
        "🍎 Macros • 💪 Workouts • 📈 Progress • 🎯 Goals",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle buttons"""
    query = update.callback_query
    user_id = update.effective_user.id
    await query.answer()
    
    try:
        if query.data == "today":
            stats = get_today_full_stats(user_id)
            message = "📊 *Today's Summary*\n\n"
            message += f"🍎 *Nutrition*\n"
            message += f"  Calories: {stats['calories_consumed']} / {stats['goals']['calories']}\n"
            message += f"  Protein: {stats['protein']}g / {stats['goals']['protein']}g\n"
            message += f"  Carbs: {stats['carbs']}g / {stats['goals']['carbs']}g\n"
            message += f"  Fat: {stats['fat']}g / {stats['goals']['fat']}g\n\n"
            message += f"🏋️ *Activity*\n"
            message += f"  Workouts: {stats['workouts']}\n"
            message += f"  Steps: {stats['steps']}\n"
            message += f"  Sleep: {stats['sleep']}h\n"
            if stats['weight']:
                message += f"\n⚖️ Weight: {stats['weight']}kg\n"
            
            keyboard = [[InlineKeyboardButton("Back", callback_data="back")]]
            await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
        elif query.data == "weekly":
            weekly = get_weekly_report(user_id)
            message = "📈 *Weekly Report (Last 7 Days)*\n\n"
            message += f"🍎 Average Daily:\n"
            message += f"  Calories: {weekly['avg_calories']}\n"
            message += f"  Protein: {weekly['avg_protein']}g\n"
            message += f"  Carbs: {weekly['avg_carbs']}g\n"
            message += f"  Fat: {weekly['avg_fat']}g\n\n"
            message += f"📊 Progress:\n"
            message += f"  Weight Change: {weekly['weight_change']:+.1f}kg\n"
            message += f"  Workouts: {weekly['workouts']}\n"
            message += f"  Avg Steps: {weekly['avg_steps']}\n"
            message += f"  Avg Sleep: {weekly['avg_sleep']}h\n"
            
            keyboard = [[InlineKeyboardButton("Back", callback_data="back")]]
            await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
        elif query.data == "roadmap":
            roadmap = get_roadmap_progress(user_id)
            if roadmap:
                progress_bar = "█" * int(roadmap['progress_pct'] / 5) + "░" * (20 - int(roadmap['progress_pct'] / 5))
                message = f"🎯 *75-Day Challenge*\n\n"
                message += f"{progress_bar}\n"
                message += f"{roadmap['progress_pct']}% Complete ({roadmap['days_elapsed']}/{roadmap['total_days']} days)\n\n"
                message += f"✅ Milestones: {roadmap['completed']}/{roadmap['total_milestones']}\n\n"
                
                for day, milestone, completed in roadmap['milestones'][:10]:  # Show first 10
                    check = "✅" if completed else "☐"
                    message += f"{check} Day {day}: {milestone}\n"
                
                if len(roadmap['milestones']) > 10:
                    message += f"\n... and {len(roadmap['milestones']) - 10} more milestones\n"
            else:
                message = "No roadmap set yet. Use Settings to create one!"
            
            keyboard = [[InlineKeyboardButton("Back", callback_data="back")]]
            await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
        elif query.data == "log_food":
            await query.edit_message_text("🍎 What did you eat? (e.g., 'chicken breast')")
            context.user_data['state'] = 'food_input'
        
        elif query.data == "log_workout":
            await query.edit_message_text("🏋️ What workout? (e.g., 'running')")
            context.user_data['state'] = 'workout_input'
        
        elif query.data == "log_steps":
            await query.edit_message_text("👟 How many steps?")
            context.user_data['state'] = 'steps_input'
        
        elif query.data == "log_sleep":
            await query.edit_message_text("😴 How many hours slept? (e.g., 7.5)")
            context.user_data['state'] = 'sleep_input'
        
        elif query.data == "settings":
            keyboard = [
                [InlineKeyboardButton("Set Calorie Goal", callback_data="set_cal_goal")],
                [InlineKeyboardButton("Set Protein Goal", callback_data="set_protein_goal")],
                [InlineKeyboardButton("Start 75-Day Challenge", callback_data="start_challenge")],
                [InlineKeyboardButton("Back", callback_data="back")],
            ]
            await query.edit_message_text("⚙️ Settings:", reply_markup=InlineKeyboardMarkup(keyboard))
        
        elif query.data == "set_cal_goal":
            await query.edit_message_text("Daily calorie goal? (e.g., 2000)")
            context.user_data['state'] = 'cal_goal_input'
        
        elif query.data == "set_protein_goal":
            await query.edit_message_text("Daily protein goal in grams? (e.g., 100)")
            context.user_data['state'] = 'protein_goal_input'
        
        elif query.data == "start_challenge":
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            today = datetime.now().strftime("%Y-%m-%d")
            
            # Create 75-day milestones
            milestones = [
                (7, "Complete first week"),
                (15, "Reach halfway to 30 days"),
                (30, "30 days strong! 🎉"),
                (45, "45 days - Habit forming"),
                (60, "60 days - Almost there!"),
                (75, "75 days - GOAL ACHIEVED! 🏆"),
            ]
            
            for day, milestone_text in milestones:
                c.execute("INSERT OR IGNORE INTO roadmap_milestones (user_id, day_number, milestone, completed) VALUES (?, ?, ?, ?)",
                         (user_id, day, milestone_text, 0))
            
            c.execute("INSERT OR REPLACE INTO user_settings (user_id, goal_days, start_date) VALUES (?, 75, ?)",
                     (user_id, today))
            
            conn.commit()
            conn.close()
            
            await query.edit_message_text("✅ 75-day challenge started! Track your progress daily.")
            context.user_data['state'] = None
        
        elif query.data == "back":
            # Go back to main menu
            keyboard = [
                [InlineKeyboardButton("📊 Today Summary", callback_data="today")],
                [InlineKeyboardButton("📈 Weekly Report", callback_data="weekly")],
                [InlineKeyboardButton("🎯 75-Day Roadmap", callback_data="roadmap")],
                [InlineKeyboardButton("🍎 Log Food", callback_data="log_food")],
                [InlineKeyboardButton("🏋️ Log Workout", callback_data="log_workout")],
                [InlineKeyboardButton("👟 Log Steps", callback_data="log_steps")],
                [InlineKeyboardButton("😴 Log Sleep", callback_data="log_sleep")],
                [InlineKeyboardButton("⚙️ Settings", callback_data="settings")],
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "🏋️ *Ultimate Fitness Tracker*\n\n"
                "🍎 Macros • 💪 Workouts • 📈 Progress • 🎯 Goals",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
    
    except Exception as e:
        logger.error(f"Error: {e}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text input"""
    state = context.user_data.get('state')
    user_id = update.effective_user.id
    text = update.message.text
    
    try:
        if state == 'food_input':
            food_lower = text.lower()
            if food_lower in FOODS_WITH_MACROS:
                cal, protein, carbs, fat = FOODS_WITH_MACROS[food_lower]
                
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                today = datetime.now().strftime("%Y-%m-%d")
                time = datetime.now().strftime("%H:%M")
                c.execute("INSERT INTO nutrition (user_id, date, time, food, calories, protein, carbs, fat) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (user_id, today, time, text, int(cal), protein, carbs, fat))
                conn.commit()
                conn.close()
                
                stats = get_today_full_stats(user_id)
                await update.message.reply_text(
                    f"✅ Logged {text}!\n\n"
                    f"  {int(cal)}cal | {protein}p | {carbs}c | {fat}f\n\n"
                    f"Today: {stats['calories_consumed']}/{stats['goals']['calories']} cal\n"
                    f"Protein: {stats['protein']}/{stats['goals']['protein']}g"
                )
                context.user_data['state'] = None
            else:
                await update.message.reply_text(f"Tell me macros! Format: '{text} 350 25 45 10' (cal protein carbs fat)")
                context.user_data['food_name'] = text
                context.user_data['state'] = 'food_macros_input'
        
        elif state == 'food_macros_input':
            try:
                parts = text.split()
                cal, protein, carbs, fat = int(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])
                food_name = context.user_data.get('food_name', 'food')
                
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                today = datetime.now().strftime("%Y-%m-%d")
                time = datetime.now().strftime("%H:%M")
                c.execute("INSERT INTO nutrition (user_id, date, time, food, calories, protein, carbs, fat) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (user_id, today, time, food_name, cal, protein, carbs, fat))
                conn.commit()
                conn.close()
                
                await update.message.reply_text(f"✅ Logged {food_name}!\n  {cal}cal | {protein}p | {carbs}c | {fat}f")
                context.user_data['state'] = None
            except:
                await update.message.reply_text("Format: calories protein carbs fat (e.g., '350 25 45 10')")
        
        elif state == 'workout_input':
            try:
                # Format: "running 30" or just "running"
                parts = text.split()
                exercise = parts[0]
                duration = int(parts[1]) if len(parts) > 1 else 30
                calories = duration * 7
                
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                today = datetime.now().strftime("%Y-%m-%d")
                time = datetime.now().strftime("%H:%M")
                c.execute("INSERT INTO workouts (user_id, date, time, exercise, duration, calories) VALUES (?, ?, ?, ?, ?, ?)",
                         (user_id, today, time, exercise, duration, calories))
                conn.commit()
                conn.close()
                
                await update.message.reply_text(f"✅ Logged {exercise} {duration}min\n🔥 ~{calories} cal burned")
                context.user_data['state'] = None
            except:
                await update.message.reply_text("Format: 'running 30' or 'gym 45'")
        
        elif state == 'steps_input':
            try:
                steps = int(text)
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                today = datetime.now().strftime("%Y-%m-%d")
                c.execute("INSERT INTO steps (user_id, date, steps) VALUES (?, ?, ?)", (user_id, today, steps))
                conn.commit()
                conn.close()
                
                await update.message.reply_text(f"✅ Logged {steps} steps!")
                context.user_data['state'] = None
            except:
                await update.message.reply_text("Enter a number!")
        
        elif state == 'sleep_input':
            try:
                hours = float(text)
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                today = datetime.now().strftime("%Y-%m-%d")
                c.execute("INSERT INTO sleep (user_id, date, hours) VALUES (?, ?, ?)", (user_id, today, hours))
                conn.commit()
                conn.close()
                
                await update.message.reply_text(f"✅ Logged {hours}h sleep!")
                context.user_data['state'] = None
            except:
                await update.message.reply_text("Enter a number (e.g., 7.5)")
        
        elif state == 'cal_goal_input':
            try:
                goal = int(text)
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("INSERT OR REPLACE INTO user_settings (user_id, daily_calories) VALUES (?, ?)", (user_id, goal))
                conn.commit()
                conn.close()
                
                await update.message.reply_text(f"✅ Calorie goal set to {goal}!")
                context.user_data['state'] = None
            except:
                await update.message.reply_text("Enter a number!")
        
        elif state == 'protein_goal_input':
            try:
                goal = float(text)
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("INSERT OR REPLACE INTO user_settings (user_id, daily_protein) VALUES (?, ?)", (user_id, goal))
                conn.commit()
                conn.close()
                
                await update.message.reply_text(f"✅ Protein goal set to {goal}g!")
                context.user_data['state'] = None
            except:
                await update.message.reply_text("Enter a number!")
    
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(f"Error: {str(e)[:50]}")

async def updates_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all updates"""
    message = "📋 *Bot Updates*\n\n"
    
    for update_info in LATEST_UPDATES:
        message += f"🆕 *v{update_info['version']}* - {update_info['date']}\n"
        for change in update_info['changes']:
            message += f"{change}\n"
        message += "\n"
    
    message += f"Current version: v{BOT_VERSION}"
    await update.message.reply_text(message, parse_mode="Markdown")

async def broadcast_update(application):
    """Broadcast update to all users who haven't seen it"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        # Get all unique user IDs
        c.execute("SELECT DISTINCT user_id FROM user_settings")
        users = [row[0] for row in c.fetchall()]
        conn.close()
        
        if not users:
            logger.info("No users to notify yet")
            return
        
        latest = LATEST_UPDATES[0]
        update_msg = f"🆕 *Bot Updated to v{BOT_VERSION}!*\n\n"
        update_msg += f"*What's New:*\n"
        for change in latest['changes']:
            update_msg += f"{change}\n"
        update_msg += f"\nUse /updates to see all changes"
        
        notified = 0
        for user_id in users:
            seen = get_user_seen_version(user_id)
            if seen != BOT_VERSION:
                try:
                    await application.bot.send_message(
                        chat_id=user_id,
                        text=update_msg,
                        parse_mode="Markdown"
                    )
                    set_user_seen_version(user_id, BOT_VERSION)
                    notified += 1
                except Exception as e:
                    logger.error(f"Could not notify user {user_id}: {e}")
        
        logger.info(f"📢 Notified {notified} users of v{BOT_VERSION}")
    except Exception as e:
        logger.error(f"Error broadcasting update: {e}")

async def send_morning_reminder(application):
    """Send morning reminder to all users - log sleep from last night"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT DISTINCT user_id FROM user_settings")
        users = [row[0] for row in c.fetchall()]
        conn.close()
        
        keyboard = [
            [InlineKeyboardButton("😴 Log Sleep (Last Night)", callback_data="log_sleep")],
            [InlineKeyboardButton("⚖️ Log Weight", callback_data="log_weight")],
            [InlineKeyboardButton("📊 View Yesterday", callback_data="today")],
        ]
        
        message = "🌅 *Good Morning!*\n\nDid you remember to log last night's sleep?\n\nTap below:"
        
        for user_id in users:
            try:
                await application.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Could not send morning reminder to {user_id}: {e}")
        
        logger.info(f"📢 Sent morning reminder to {len(users)} users")
    except Exception as e:
        logger.error(f"Error sending morning reminder: {e}")

async def send_night_reminder(application):
    """Send night reminder to all users - log food and workouts"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT DISTINCT user_id FROM user_settings")
        users = [row[0] for row in c.fetchall()]
        conn.close()
        
        keyboard = [
            [InlineKeyboardButton("🍎 Log Food", callback_data="log_food")],
            [InlineKeyboardButton("🏋️ Log Workout", callback_data="log_workout")],
            [InlineKeyboardButton("📊 View Today", callback_data="today")],
        ]
        
        message = "🌙 *Good Night!*\n\nDon't forget to log your meals and workouts from today!\n\nTap below:"
        
        for user_id in users:
            try:
                await application.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Could not send night reminder to {user_id}: {e}")
        
        logger.info(f"📢 Sent night reminder to {len(users)} users")
    except Exception as e:
        logger.error(f"Error sending night reminder: {e}")

async def post_init(application):
    """Run after bot is ready - broadcast updates and set up reminders"""
    await broadcast_update(application)
    
    # Set up scheduler for daily reminders
    scheduler = AsyncIOScheduler()
    
    # Morning reminder at 7:00 AM
    scheduler.add_job(
        send_morning_reminder,
        CronTrigger(hour=7, minute=0),
        args=[application],
        id='morning_reminder'
    )
    
    # Night reminder at 9:00 PM
    scheduler.add_job(
        send_night_reminder,
        CronTrigger(hour=21, minute=0),
        args=[application],
        id='night_reminder'
    )
    
    scheduler.start()
    logger.info("⏰ Daily reminders scheduled (7am & 9pm)")

def main():
    """Start bot"""
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        logger.error("No token!")
        return
    
    init_db()
    logger.info("🤖 Ultimate Fitness Bot Started!")
    
    app = Application.builder().token(token).build()
    
    # Set post_init to broadcast updates when bot starts
    app.post_init = post_init
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("updates", updates_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    logger.info("📢 Broadcasting updates to users...")
    app.run_polling(allowed_updates=['message', 'callback_query'])

if __name__ == '__main__':
    init_db()
    main()
