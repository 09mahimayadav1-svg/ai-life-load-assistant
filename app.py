import os
import json
from datetime import datetime, timezone, timedelta
from typing import List
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from pydantic import BaseModel


app = FastAPI(title="AI Life-Load Assistant API")

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

IST = ZoneInfo("Asia/Kolkata")
PREFERENCES_FILE = "preferences.json"
CHORES_FILE = "chores.json"
OAUTH_STATE_FILE = "oauth_states.json"


# =========================
# Helper Functions
# =========================

def require_env():
    missing = []
    if not CLIENT_ID:
        missing.append("GOOGLE_CLIENT_ID")
    if not CLIENT_SECRET:
        missing.append("GOOGLE_CLIENT_SECRET")
    if not REDIRECT_URI:
        missing.append("GOOGLE_REDIRECT_URI")

    if missing:
        raise HTTPException(
            status_code=500,
            detail=f"Missing environment variables: {', '.join(missing)}"
        )


def load_json_file(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json_file(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_oauth_states():
    return load_json_file(OAUTH_STATE_FILE, {})


def save_oauth_states(states):
    save_json_file(OAUTH_STATE_FILE, states)


def get_calendar_service():
    if not os.path.exists("token.json"):
        raise HTTPException(
            status_code=400,
            detail="token.json not found. First open /auth/google/start and complete Google login."
        )

    creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
        with open("token.json", "w", encoding="utf-8") as token_file:
            token_file.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def get_todays_calendar_events():
    service = get_calendar_service()

    now_ist = datetime.now(IST)
    start_of_day = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=start_of_day.isoformat(),
            timeMax=end_of_day.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = events_result.get("items", [])
    cleaned = []

    for event in events:
        start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
        end = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date")
        cleaned.append(
            {
                "summary": event.get("summary", "Untitled event"),
                "start": start,
                "end": end,
                "location": event.get("location"),
            }
        )

    return cleaned


def get_upcoming_calendar_events(max_results: int = 10):
    service = get_calendar_service()

    now = datetime.now(timezone.utc).isoformat()

    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = events_result.get("items", [])
    cleaned = []

    for event in events:
        cleaned.append(
            {
                "summary": event.get("summary", "Untitled event"),
                "start": event.get("start", {}).get("dateTime")
                or event.get("start", {}).get("date"),
                "end": event.get("end", {}).get("dateTime")
                or event.get("end", {}).get("date"),
                "location": event.get("location"),
            }
        )

    return cleaned


def calculate_workload_level(event_count: int):
    if event_count == 0:
        return "Free day", 1
    elif event_count <= 3:
        return "Light workload", 3
    elif event_count <= 6:
        return "Moderate workload", 6
    else:
        return "Heavy workload", 8


def build_meal_plan(workload_level: str, preferences: dict):
    food_type = preferences.get("food_type", "vegetarian")
    cuisine = preferences.get("preferred_cuisine", "Indian")

    if workload_level == "Heavy workload":
        breakfast = "Poha + curd"
        lunch = "Quick veg pulao + curd"
        dinner = "Khichdi + salad"
        grocery = ["poha", "curd", "rice", "mixed vegetables", "moong dal", "salad vegetables"]
    elif workload_level == "Moderate workload":
        breakfast = "Upma + tea"
        lunch = "Roti + paneer sabzi"
        dinner = "Dal rice + cucumber salad"
        grocery = ["suji", "tea", "atta", "paneer", "vegetables", "dal", "rice", "cucumber"]
    else:
        breakfast = "Stuffed paratha + curd"
        lunch = "Rajma rice"
        dinner = "Roti + mixed veg + dal"
        grocery = ["atta", "potato", "curd", "rajma", "rice", "mixed vegetables", "dal"]

    if food_type.lower() != "vegetarian":
        dinner = "Chicken rice bowl"
        grocery = ["chicken", "rice", "vegetables", "curd"]

    dislikes = set(x.lower() for x in preferences.get("dislikes", []))
    grocery = [item for item in grocery if item.lower() not in dislikes]

    return {
        "cuisine": cuisine,
        "breakfast": breakfast,
        "lunch": lunch,
        "dinner": dinner,
        "grocery_list": grocery
    }


def generate_breathing_reset(stress_score: int):
    
    if stress_score >= 8:
        duration = "2 minutes"
        pattern = "4-4-6"
        steps = [
            "Sit comfortably and relax your shoulders",
            "Inhale slowly through your nose for 4 seconds",
            "Hold your breath for 4 seconds",
            "Exhale slowly through your nose for 6 seconds",
            "Repeat this cycle for 2 minutes"
        ]
        reason = "Your schedule shows high workload. A breathing reset helps calm the nervous system."

    elif stress_score >= 6:
        duration = "90 seconds"
        pattern = "4-4-4"
        steps = [
            "Sit upright and relax",
            "Inhale for 4 seconds",
            "Hold for 4 seconds",
            "Exhale for 4 seconds",
            "Repeat for 90 seconds"
        ]
        reason = "Moderate meeting density detected. A short breathing break helps reset focus."

    else:
        duration = "60 seconds"
        pattern = "simple deep breathing"
        steps = [
            "Close your eyes",
            "Inhale slowly through the nose",
            "Exhale slowly",
            "Repeat for 1 minute"
        ]
        reason = "Low workload detected. A short pause still improves mental clarity."

    return {
        "duration": duration,
        "breathing_pattern": pattern,
        "steps": steps,
        "reason": reason
    }

# =========================
# Data Models
# =========================

class UserPreferences(BaseModel):
    food_type: str = "vegetarian"
    dislikes: List[str] = []
    preferred_cuisine: str = "Indian"
    breakfast_time: str = "08:30"
    lunch_time: str = "13:00"
    dinner_time: str = "20:00"


class ChoreItem(BaseModel):
    title: str
    category: str = "household"
    priority: str = "medium"
    estimated_minutes: int = 15
    due_today: bool = True


def build_daily_insight(workload_level, stress_score, events_count, chores_count):
    if stress_score >= 8:
        return (
            f"Today looks highly loaded with {events_count} calendar events and "
            f"{chores_count} household tasks. Protect recovery time, avoid adding "
            f"new tasks, and take a guided breathing reset."
        )
    elif stress_score >= 6:
        return (
            f"Today looks moderately busy with {events_count} calendar events and "
            f"{chores_count} household tasks. You should batch small tasks together "
            f"and take one short pause between high-focus activities."
        )
    else:
        return (
            f"Today looks manageable with {events_count} calendar events and "
            f"{chores_count} household tasks. This is a good day for focused work "
            f"and steady home planning."
        )



# =========================
# Basic Routes
# =========================

@app.get("/")
def home():
    return {
        "message": "AI Life-Load Assistant API is running",
        "status": "ok"
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/debug/env")
def debug_env():
    return {
        "client_id_prefix": (CLIENT_ID[:20] + "...") if CLIENT_ID else None,
        "redirect_uri": REDIRECT_URI
    }


# =========================
# Mental Wellbeing Routes
# =========================

@app.get("/wellbeing/breathing-reset")
def breathing_reset():
    
    events = get_todays_calendar_events()
    workload_level, stress_score = calculate_workload_level(len(events))

    breathing_plan = generate_breathing_reset(stress_score)

    return {
        "stress_score": stress_score,
        "workload_level": workload_level,
        "breathing_reset": breathing_plan
    }


@app.get("/ai/life-assistant")
def unified_life_assistant():
    events = get_todays_calendar_events()

    chores = load_json_file(CHORES_FILE, [])
    today_chores = [c for c in chores if c.get("due_today", True)]

    prefs = load_json_file(PREFERENCES_FILE, {
        "food_type": "vegetarian",
        "dislikes": [],
        "preferred_cuisine": "Indian",
        "breakfast_time": "08:30",
        "lunch_time": "13:00",
        "dinner_time": "20:00",
    })

    workload_level, stress_score = calculate_workload_level(len(events))
    meal_plan = build_meal_plan(workload_level, prefs)
    breathing_reset = generate_breathing_reset(stress_score)

    meal_planning_minutes_saved = 20 * 7
    grocery_minutes_saved = 15 * 2
    chore_planning_minutes_saved = 10 * 7
    schedule_interpretation_minutes_saved = 12 * 7

    total_minutes_saved = (
        meal_planning_minutes_saved
        + grocery_minutes_saved
        + chore_planning_minutes_saved
        + schedule_interpretation_minutes_saved
    )

    daily_insight = build_daily_insight(
        workload_level=workload_level,
        stress_score=stress_score,
        events_count=len(events),
        chores_count=len(today_chores)
    )

    return {
        "calendar_events_count": len(events),
        "household_chores_count": len(today_chores),
        "calendar_events": events,
        "household_chores": today_chores,
        "workload_level": workload_level,
        "stress_score": stress_score,
        "meal_plan": meal_plan,
        "breathing_reset": breathing_reset,
        "weekly_time_saved_minutes": total_minutes_saved,
        "weekly_time_saved_hours": round(total_minutes_saved / 60, 2),
        "daily_ai_insight": daily_insight
    }

# =========================
# Google OAuth Routes
# =========================

@app.get("/auth/google/start")
def google_auth():
    require_env()

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [REDIRECT_URI],
            }
        },
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )

    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    states = load_oauth_states()
    states[state] = {
        "code_verifier": flow.code_verifier
    }
    save_oauth_states(states)

    return RedirectResponse(auth_url)


@app.get("/auth/google/callback")
def google_callback(state: str, code: str):
    states = load_oauth_states()
    state_data = states.get(state)

    if not state_data:
        raise HTTPException(
            status_code=400,
            detail="OAuth session expired or state not found. Start login again."
        )

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [REDIRECT_URI],
            }
        },
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )

    flow.code_verifier = state_data["code_verifier"]
    flow.fetch_token(code=code)

    creds = flow.credentials

    with open("token.json", "w", encoding="utf-8") as token_file:
        token_file.write(creds.to_json())

    states.pop(state, None)
    save_oauth_states(states)

    return {
        "status": "success",
        "message": "Google Calendar connected successfully and token saved"
    }


# =========================
# Calendar Routes
# =========================

@app.get("/calendar/upcoming")
def get_upcoming_events():
    events = get_upcoming_calendar_events(10)
    return {"count": len(events), "events": events}


@app.get("/ai/workload")
def analyze_workload():
    events = get_todays_calendar_events()
    workload_level, stress_score = calculate_workload_level(len(events))

    if stress_score >= 8:
        suggestion = "Block a recovery break and postpone one non-urgent task."
    elif stress_score >= 6:
        suggestion = "Schedule a 2-minute breathing reset between meetings."
    elif stress_score >= 3:
        suggestion = "Take a short breathing break before the next event."
    else:
        suggestion = "Great day to focus on deep work."

    return {
        "meetings_today": len(events),
        "workload_level": workload_level,
        "stress_score": stress_score,
        "suggestion": suggestion
    }


# =========================
# User Preferences Routes
# =========================

@app.get("/user/preferences")
def get_user_preferences():
    prefs = load_json_file(PREFERENCES_FILE, {
        "food_type": "vegetarian",
        "dislikes": [],
        "preferred_cuisine": "Indian",
        "breakfast_time": "08:30",
        "lunch_time": "13:00",
        "dinner_time": "20:00",
    })
    return prefs


@app.post("/user/preferences")
def save_user_preferences(preferences: UserPreferences):
    save_json_file(PREFERENCES_FILE, preferences.dict())
    return {
        "status": "success",
        "message": "User preferences saved",
        "preferences": preferences.dict()
    }


# =========================
# Household Chores Routes
# =========================

@app.get("/chores")
def get_chores():
    chores = load_json_file(CHORES_FILE, [])
    return {"count": len(chores), "chores": chores}


@app.post("/chores")
def add_chore(chore: ChoreItem):
    chores = load_json_file(CHORES_FILE, [])
    chores.append(chore.dict())
    save_json_file(CHORES_FILE, chores)
    return {
        "status": "success",
        "message": "Chore added",
        "chore": chore.dict()
    }


@app.get("/chores/today")
def get_todays_chores():
    chores = load_json_file(CHORES_FILE, [])
    today_chores = [c for c in chores if c.get("due_today", True)]
    return {"count": len(today_chores), "chores": today_chores}


# =========================
# Meal Planning Routes
# =========================

@app.get("/meal/plan")
def get_meal_plan():
    prefs = load_json_file(PREFERENCES_FILE, {
        "food_type": "vegetarian",
        "dislikes": [],
        "preferred_cuisine": "Indian",
        "breakfast_time": "08:30",
        "lunch_time": "13:00",
        "dinner_time": "20:00",
    })

    events = get_todays_calendar_events()
    workload_level, stress_score = calculate_workload_level(len(events))

    plan = build_meal_plan(workload_level, prefs)

    return {
        "workload_level": workload_level,
        "stress_score": stress_score,
        "meal_plan": plan
    }



# =========================
# Mental Load reset
# =========================


def generate_breathing_reset(stress_score):

    if stress_score >= 8:
        return {
            "duration": "2 minutes",
            "pattern": "4-4-6 breathing",
            "steps": [
                "Sit comfortably",
                "Inhale through your nose for 4 seconds",
                "Hold your breath for 4 seconds",
                "Exhale slowly through your nose for 6 seconds",
                "Repeat for 2 minutes"
            ],
            "reason": "High workload detected. This breathing reset helps calm your nervous system."
        }

    elif stress_score >= 6:
        return {
            "duration": "90 seconds",
            "pattern": "4-4-4 breathing",
            "steps": [
                "Sit upright",
                "Inhale for 4 seconds",
                "Hold for 4 seconds",
                "Exhale for 4 seconds",
                "Repeat for 90 seconds"
            ],
            "reason": "Moderate workload detected. This breathing reset helps restore focus."
        }

    else:
        return {
            "duration": "1 minute",
            "pattern": "slow breathing",
            "steps": [
                "Close your eyes",
                "Take slow deep breaths",
                "Inhale slowly",
                "Exhale slowly",
                "Repeat for 1 minute"
            ],
            "reason": "Light workload. A short breathing reset improves mental clarity."
        }


# =========================
# Unified Dashboard Routes
# =========================

@app.get("/dashboard/today")
def get_today_dashboard():
    events = get_todays_calendar_events()
    chores = load_json_file(CHORES_FILE, [])
    today_chores = [c for c in chores if c.get("due_today", True)]

    prefs = load_json_file(PREFERENCES_FILE, {
        "food_type": "vegetarian",
        "dislikes": [],
        "preferred_cuisine": "Indian",
        "breakfast_time": "08:30",
        "lunch_time": "13:00",
        "dinner_time": "20:00",
    })

    workload_level, stress_score = calculate_workload_level(len(events))
    meal_plan = build_meal_plan(workload_level, prefs)
    breathing = generate_breathing_reset(stress_score)

    return {
        "calendar_events_count": len(events),
        "household_chores_count": len(today_chores),
        "calendar_events": events,
        "household_chores": today_chores,
        "workload_level": workload_level,
        "stress_score": stress_score,
        "meal_plan": meal_plan,
        "breathing_recommendation": breathing
    }


@app.get("/dashboard/weekly-summary")
def get_weekly_summary():
    todays_events = get_todays_calendar_events()
    workload_level, stress_score = calculate_workload_level(len(todays_events))

    meal_planning_minutes_saved = 20 * 7
    grocery_minutes_saved = 15 * 2
    chore_planning_minutes_saved = 10 * 7
    schedule_interpretation_minutes_saved = 12 * 7

    total_minutes_saved = (
        meal_planning_minutes_saved
        + grocery_minutes_saved
        + chore_planning_minutes_saved
        + schedule_interpretation_minutes_saved
    )

    return {
        "weekly_time_saved_minutes": total_minutes_saved,
        "weekly_time_saved_hours": round(total_minutes_saved / 60, 2),
        "current_workload_level": workload_level,
        "current_stress_score": stress_score,
        "insight": "The assistant reduces repetitive decision-making by converting schedule + home planning into actionable suggestions."
    }