import os, json
from datetime import datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from pydantic import BaseModel
from openai import OpenAI

from inventory_engine import get_inventory_driven_meal_plan, apply_recipe_to_inventory
from wellbeing_engine import get_wellbeing_activity
from memory_engine import get_habit_memory, update_habit_memory

app = FastAPI(title='AI Life-Load Assistant API')

CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
REDIRECT_URI = os.getenv('GOOGLE_REDIRECT_URI')
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

IST = ZoneInfo('Asia/Kolkata')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PREFERENCES_FILE = os.path.join(BASE_DIR, 'preferences.json')
CHORES_FILE = os.path.join(BASE_DIR, 'chores.json')
MANDATORY_TASKS_FILE = os.path.join(BASE_DIR, 'mandatory_tasks.json')
OAUTH_STATE_FILE = os.path.join(BASE_DIR, 'oauth_states.json')
TOKEN_FILE = os.path.join(BASE_DIR, 'token.json')
MEAL_LOG_FILE = os.path.join(BASE_DIR, 'meal_log.json')
HABIT_MEMORY_FILE = os.path.join(BASE_DIR, 'habit_memory.json')
DATA_FILE = os.path.abspath(os.path.join(BASE_DIR, '..', 'data', 'meal_inventory_data.xlsx'))
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')

class UserPreferences(BaseModel):
    food_type: str = 'vegetarian'
    dislikes: List[str] = []
    preferred_cuisine: str = 'Indian'
    breakfast_time: str = '08:30'
    lunch_time: str = '13:00'
    dinner_time: str = '20:00'

class ChoreItem(BaseModel):
    title: str
    preferred_time: str = '18:00'
    duration_min: int = 15
    due_today: bool = True
    priority: str = 'medium'

class MandatoryTask(BaseModel):
    title: str
    start_time: str
    duration_min: int = 30
    category: str = 'personal'

class MealDecision(BaseModel):
    recipe_name: str
    members: int = 2
    meal_slot: str = 'Any'
    made_recipe: bool = True
    custom_cooked: str = ''
    actual_time_min: Optional[int] = None

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    members: int = 2
    meal_type: str = 'Any'
    history: List[ChatMessage] = []

def load_json_file(path, default):
    if not os.path.exists(path):
        return default
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json_file(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

def load_oauth_states():
    return load_json_file(OAUTH_STATE_FILE, {})

def save_oauth_states(states):
    save_json_file(OAUTH_STATE_FILE, states)

def require_env():
    missing = []
    if not CLIENT_ID: missing.append('GOOGLE_CLIENT_ID')
    if not CLIENT_SECRET: missing.append('GOOGLE_CLIENT_SECRET')
    if not REDIRECT_URI: missing.append('GOOGLE_REDIRECT_URI')
    if missing:
        raise HTTPException(status_code=500, detail=f"Missing environment variables: {', '.join(missing)}")

def get_calendar_service():
    if not os.path.exists(TOKEN_FILE):
        raise HTTPException(status_code=400, detail='token.json not found. First open /auth/google/start and complete Google login.')
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
        with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
            f.write(creds.to_json())
    return build('calendar', 'v3', credentials=creds)

def classify_event_priority(event):
    title = str(event.get('summary', '')).lower()
    optional_keywords = ['optional','fyi','townhall','drop-in','awareness','open house']
    return 'optional' if any(k in title for k in optional_keywords) else 'mandatory'

def _calendar_events_for_day(day_offset=0):
    service = get_calendar_service()
    now_ist = datetime.now(IST) + timedelta(days=day_offset)
    start_of_day = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)
    events = service.events().list(calendarId='primary', timeMin=start_of_day.isoformat(), timeMax=end_of_day.isoformat(), singleEvents=True, orderBy='startTime').execute().get('items', [])
    cleaned = []
    for event in events:
        cleaned.append({'summary': event.get('summary', 'Untitled event'), 'start': event.get('start', {}).get('dateTime') or event.get('start', {}).get('date'), 'end': event.get('end', {}).get('dateTime') or event.get('end', {}).get('date'), 'location': event.get('location'), 'priority': classify_event_priority(event)})
    return cleaned

def _evening_events(events, cutoff_hour=17):
    filtered = []
    for event in events:
        start = str(event.get('start', ''))
        if 'T' in start:
            try:
                hour_part = int(start.split('T')[1][:2])
                if hour_part >= cutoff_hour:
                    filtered.append(event)
            except Exception:
                pass
    return filtered

def get_todays_calendar_events():
    return _calendar_events_for_day(0)

def calculate_workload_level(event_count):
    if event_count == 0: return 'Free day', 1
    if event_count <= 3: return 'Light workload', 3
    if event_count <= 6: return 'Moderate workload', 6
    return 'Heavy workload', 8

def build_daily_ai_summary(events_count, chores_count, mandatory_tasks_count, workload_level, stress_score):
    if workload_level == 'Heavy workload':
        headline = 'High-demand day. Prioritize essentials and keep decisions simple.'
    elif workload_level == 'Moderate workload':
        headline = 'Balanced but busy day. Quick meals and short resets will help.'
    else:
        headline = 'Lighter day. Good time for focused work and family routines.'
    return {'headline': headline, 'events_count': events_count, 'chores_count': chores_count, 'mandatory_tasks_count': mandatory_tasks_count, 'workload_level': workload_level, 'stress_score': stress_score}

def build_tomorrow_prep(events, workload_level):
    mandatory = [e for e in events if e.get('priority') == 'mandatory']
    ideas = []
    if len(mandatory) >= 4:
        ideas.append('Keep clothes, charger, laptop, and meeting notes ready tonight.')
    if len(events) >= 1:
        ideas.append('Prepare breakfast ingredients tonight to reduce the morning rush.')
    if workload_level in {'Moderate workload', 'Heavy workload'}:
        ideas.append('Plan one quick backup meal for tomorrow.')
    ideas.append('Review calendar conflicts tonight and decide what can be optional.')
    return ideas[:4]


def _require_openai():
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail='OPENAI_API_KEY is missing in backend environment.')

def _build_chat_context(members: int = 2, meal_type: str = 'Any'):
    prefs = load_json_file(PREFERENCES_FILE, {'food_type':'vegetarian','dislikes':[],'preferred_cuisine':'Indian','breakfast_time':'08:30','lunch_time':'13:00','dinner_time':'20:00'})
    events = get_todays_calendar_events()
    chores = load_json_file(CHORES_FILE, [])
    mandatory_tasks = load_json_file(MANDATORY_TASKS_FILE, [])
    workload_level, stress_score = calculate_workload_level(len(events))
    evening_events = _evening_events(events)
    evening_workload_level, evening_stress_score = calculate_workload_level(len(evening_events))
    general_plan = get_inventory_driven_meal_plan(DATA_FILE, meal_type, members, prefs, workload_level, stress_score)
    dinner_plan = get_inventory_driven_meal_plan(DATA_FILE, 'Dinner', members, prefs, evening_workload_level, evening_stress_score, context_label='evening')
    tomorrow_events = _calendar_events_for_day(1)
    tomorrow_workload_level, tomorrow_stress_score = calculate_workload_level(len(tomorrow_events))
    tomorrow_breakfast = get_inventory_driven_meal_plan(DATA_FILE, 'Breakfast', members, prefs, tomorrow_workload_level, tomorrow_stress_score)
    wellbeing_day = get_wellbeing_activity(activity_type='breathing', stress_score=stress_score, context='day', events=events)
    wellbeing_bed = get_wellbeing_activity(activity_type='breathing', stress_score=stress_score, context='bedtime', events=events)
    meal_history = load_json_file(MEAL_LOG_FILE, [])[-5:]
    return {
        'members': members,
        'meal_type': meal_type,
        'today': {
            'meetings_count': len(events),
            'mandatory_meetings': len([e for e in events if e.get('priority') == 'mandatory']),
            'optional_meetings': len([e for e in events if e.get('priority') == 'optional']),
            'workload_level': workload_level,
            'stress_score': stress_score,
            'evening_workload_level': evening_workload_level,
            'evening_stress_score': evening_stress_score,
            'calendar_events': events,
            'chores': chores,
            'fixed_routines': mandatory_tasks,
        },
        'meal_plan': general_plan,
        'dinner_plan': dinner_plan,
        'tomorrow': {
            'events': tomorrow_events,
            'workload_level': tomorrow_workload_level,
            'stress_score': tomorrow_stress_score,
            'prep_ideas': build_tomorrow_prep(tomorrow_events, tomorrow_workload_level),
            'breakfast_options': tomorrow_breakfast.get('recommended_meals', []),
        },
        'wellbeing': {'day': wellbeing_day, 'bedtime': wellbeing_bed},
        'recent_meal_history': meal_history,
        'habit_memory': get_habit_memory(HABIT_MEMORY_FILE),
    }

def _call_openai_chat(user_message: str, members: int = 2, meal_type: str = 'Any', history=None):
    _require_openai()
    client = OpenAI(api_key=OPENAI_API_KEY)
    context = _build_chat_context(members=members, meal_type=meal_type)

    items = []
    if history:
        for m in history[-8:]:
            role = 'assistant' if m.role == 'assistant' else 'user'
            items.append({'role': role, 'content': m.content})

    items.append({'role': 'user', 'content': user_message})

    instructions = f"""You are an AI Life-Load Assistant for a working parent.
Be practical, warm, and concise.
Use the app context to give personalized suggestions.
Prefer inventory-aware meal suggestions and evening-load-based dinner ideas.
If asked what to cook, suggest 2-4 options with a short reason.
If asked about groceries, use missing ingredients and suggested_purchase_items.
If asked about tomorrow, use prep_ideas and breakfast_options.
Use habit_memory to personalize time estimates and future suggestions when relevant.
Do not output raw JSON.

APP CONTEXT:
{context}
"""

    response = client.responses.create(
        model=OPENAI_MODEL,
        instructions=instructions,
        input=items,
    )

    answer = ""
    try:
        answer = response.output_text
    except Exception:
        answer = ""

    if not answer:
        try:
            parts = []
            for item in response.output:
                for content in getattr(item, "content", []):
                    text_obj = getattr(content, "text", None)
                    text_value = getattr(text_obj, "value", None)
                    if text_value:
                        parts.append(text_value)
            answer = "\n".join(parts).strip()
        except Exception:
            answer = ""

    if not answer:
        answer = "I understood your question, but I could not generate a visible response. Please try again."

    print("OPENAI ANSWER:", answer)
    return answer

@app.get('/')
def home():
    return {'message': 'AI Life-Load Assistant API is running'}

@app.get('/health')
def health():
    return {'status': 'ok'}

@app.get('/auth/google/start')
def auth_google_start():
    require_env()

    flow = Flow.from_client_config(
        {
            'web': {
                'client_id': CLIENT_ID,
                'client_secret': CLIENT_SECRET,
                'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                'token_uri': 'https://oauth2.googleapis.com/token'
            }
        },
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
        autogenerate_code_verifier=True
    )

    auth_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )

    states = {}
    states[state] = {
        'created_at': datetime.now(IST).isoformat(),
        'code_verifier': flow.code_verifier
    }
    print("DEBUG START BASE_DIR:", BASE_DIR)
    print("DEBUG START OAUTH_STATE_FILE:", OAUTH_STATE_FILE)
    print("DEBUG START STATE:", state)
    print("DEBUG START CODE_VERIFIER:", flow.code_verifier)
    print("DEBUG START STATES TO SAVE:", states)

    save_oauth_states(states)

    print("DEBUG START SAVED FILE EXISTS:", os.path.exists(OAUTH_STATE_FILE))
    if os.path.exists(OAUTH_STATE_FILE):
        with open(OAUTH_STATE_FILE, "r", encoding="utf-8") as f:
            print("DEBUG START FILE CONTENT:", f.read())

    return RedirectResponse(auth_url)


@app.get('/auth/google/callback')
def auth_google_callback(state: str, code: str):
    require_env()

    print("DEBUG CALLBACK BASE_DIR:", BASE_DIR)
    print("DEBUG CALLBACK OAUTH_STATE_FILE:", OAUTH_STATE_FILE)
    print("DEBUG CALLBACK FILE EXISTS:", os.path.exists(OAUTH_STATE_FILE))
    if os.path.exists(OAUTH_STATE_FILE):
        with open(OAUTH_STATE_FILE, "r", encoding="utf-8") as f:
            print("DEBUG CALLBACK FILE CONTENT:", f.read())
    print("DEBUG CALLBACK RECEIVED STATE:", state)
    print("DEBUG CALLBACK RECEIVED CODE:", code[:20] if code else None)

    states = load_oauth_states()
    print("DEBUG CALLBACK LOADED STATES:", states)

    if state not in states:
        raise HTTPException(status_code=400, detail='Invalid OAuth state.')

    saved = states[state]
    code_verifier = saved.get('code_verifier')
    if not code_verifier:
        raise HTTPException(status_code=400, detail='Missing code verifier for OAuth flow.')

    flow = Flow.from_client_config(
        {
            'web': {
                'client_id': CLIENT_ID,
                'client_secret': CLIENT_SECRET,
                'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                'token_uri': 'https://oauth2.googleapis.com/token'
            }
        },
        scopes=SCOPES,
        state=state,
        redirect_uri=REDIRECT_URI
    )

    flow.code_verifier = code_verifier
    flow.fetch_token(code=code)

    with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
        f.write(flow.credentials.to_json())

    states.pop(state, None)
    save_oauth_states(states)

    return HTMLResponse("""
    <html>
      <body>
        <h3>Google Calendar connected successfully.</h3>
        <p>You can close this tab and return to the app.</p>
      </body>
    </html>
    """)


@app.get('/chores')
def get_chores():
    chores = load_json_file(CHORES_FILE, [])
    return {'count': len(chores), 'chores': chores}

@app.post('/chores')
def add_chore(chore: ChoreItem):
    chores = load_json_file(CHORES_FILE, [])
    chores.append(chore.dict())
    save_json_file(CHORES_FILE, chores)
    return {'status': 'success'}

@app.delete('/chores/{index}')
def delete_chore(index: int):
    chores = load_json_file(CHORES_FILE, [])
    if index < 0 or index >= len(chores):
        raise HTTPException(status_code=404, detail='Chore not found')
    chores.pop(index)
    save_json_file(CHORES_FILE, chores)
    return {'status': 'success'}

@app.get('/mandatory-tasks')
def get_mandatory_tasks():
    tasks = load_json_file(MANDATORY_TASKS_FILE, [])
    return {'count': len(tasks), 'tasks': tasks}

@app.post('/mandatory-tasks')
def add_mandatory_task(task: MandatoryTask):
    tasks = load_json_file(MANDATORY_TASKS_FILE, [])
    tasks.append(task.dict())
    save_json_file(MANDATORY_TASKS_FILE, tasks)
    return {'status': 'success'}

@app.delete('/mandatory-tasks/{index}')
def delete_mandatory_task(index: int):
    tasks = load_json_file(MANDATORY_TASKS_FILE, [])
    if index < 0 or index >= len(tasks):
        raise HTTPException(status_code=404, detail='Mandatory task not found')
    tasks.pop(index)
    save_json_file(MANDATORY_TASKS_FILE, tasks)
    return {'status': 'success'}

@app.get('/user/preferences')
def get_user_preferences():
    return load_json_file(PREFERENCES_FILE, {'food_type':'vegetarian','dislikes':[],'preferred_cuisine':'Indian','breakfast_time':'08:30','lunch_time':'13:00','dinner_time':'20:00'})

@app.get('/inventory')
def get_inventory():
    import pandas as pd
    df = pd.read_excel(DATA_FILE, sheet_name='Inventory')
    return {'items': df.fillna('').to_dict(orient='records')}

@app.get('/meal/plan')
def get_meal_plan(meal_type: str = Query('Any'), members: int = Query(2, ge=1, le=8)):
    prefs = load_json_file(PREFERENCES_FILE, {'food_type':'vegetarian','dislikes':[],'preferred_cuisine':'Indian','breakfast_time':'08:30','lunch_time':'13:00','dinner_time':'20:00'})
    events = get_todays_calendar_events()
    workload_level, stress_score = calculate_workload_level(len(events))
    if meal_type.lower() == 'dinner':
        evening_events = _evening_events(events)
        evening_workload_level, evening_stress_score = calculate_workload_level(len(evening_events))
        plan = get_inventory_driven_meal_plan(DATA_FILE, meal_type, members, prefs, evening_workload_level, evening_stress_score, context_label='evening')
        return {'workload_level': evening_workload_level, 'stress_score': evening_stress_score, 'meal_plan': plan}
    plan = get_inventory_driven_meal_plan(DATA_FILE, meal_type, members, prefs, workload_level, stress_score)
    return {'workload_level': workload_level, 'stress_score': stress_score, 'meal_plan': plan}

@app.post('/meal/confirm')
def confirm_meal(decision: MealDecision):
    log = load_json_file(MEAL_LOG_FILE, [])
    entry = {
        'timestamp': datetime.now(IST).isoformat(),
        'recipe_name': decision.recipe_name,
        'meal_slot': decision.meal_slot,
        'members': decision.members,
        'made_recipe': decision.made_recipe,
        'custom_cooked': decision.custom_cooked,
        'actual_time_min': decision.actual_time_min,
    }
    if decision.made_recipe:
        result = apply_recipe_to_inventory(DATA_FILE, decision.recipe_name, decision.members)
        entry['inventory_result'] = result
        log.append(entry)
        save_json_file(MEAL_LOG_FILE, log)
        memory = update_habit_memory(HABIT_MEMORY_FILE, entry)
        return {'status': 'success', 'message': f"Inventory updated for {decision.recipe_name}.", 'result': result, 'habit_memory': memory}
    entry['inventory_result'] = {'status': 'skipped', 'message': 'Inventory not changed because suggested recipe was not made.'}
    log.append(entry)
    save_json_file(MEAL_LOG_FILE, log)
    memory = update_habit_memory(HABIT_MEMORY_FILE, entry)
    return {'status': 'success', 'message': 'Saved your meal choice without inventory changes.', 'result': entry['inventory_result'], 'habit_memory': memory}

@app.post('/chat/assistant')
def chat_assistant(request: ChatRequest):
    answer = _call_openai_chat(
        user_message=request.message,
        members=request.members,
        meal_type=request.meal_type,
        history=request.history,
    )
    return {'answer': answer}

@app.get('/memory/habits')
def memory_habits():
    return get_habit_memory(HABIT_MEMORY_FILE)

@app.get('/wellbeing/activity')
def wellbeing_activity(activity_type: str = Query('breathing'), stress_score: Optional[int] = Query(None, ge=1, le=10), context: str = Query('day')):
    if stress_score is None:
        _, stress_score = calculate_workload_level(len(get_todays_calendar_events()))
    today_events = get_todays_calendar_events()
    return get_wellbeing_activity(activity_type=activity_type, stress_score=stress_score, context=context, events=today_events)

@app.get('/dashboard/today')
def get_today_dashboard():
    events = get_todays_calendar_events()
    chores = load_json_file(CHORES_FILE, [])
    mandatory_tasks = load_json_file(MANDATORY_TASKS_FILE, [])
    prefs = load_json_file(PREFERENCES_FILE, {'food_type':'vegetarian','dislikes':[],'preferred_cuisine':'Indian','breakfast_time':'08:30','lunch_time':'13:00','dinner_time':'20:00'})
    workload_level, stress_score = calculate_workload_level(len(events))
    meal_plan = get_inventory_driven_meal_plan(DATA_FILE, 'Any', 2, prefs, workload_level, stress_score)
    wellbeing = get_wellbeing_activity(activity_type='breathing', stress_score=stress_score, context='day', events=events)
    mandatory = len([e for e in events if e.get('priority') == 'mandatory'])
    optional = len([e for e in events if e.get('priority') == 'optional'])
    ai_summary = build_daily_ai_summary(len(events), len(chores), len(mandatory_tasks), workload_level, stress_score)
    evening_events = _evening_events(events)
    evening_workload_level, evening_stress_score = calculate_workload_level(len(evening_events))
    dinner_plan = get_inventory_driven_meal_plan(DATA_FILE, 'Dinner', 2, prefs, evening_workload_level, evening_stress_score, context_label='evening')
    return {'calendar_events_count': len(events), 'mandatory_meetings': mandatory, 'optional_meetings': optional, 'household_chores_count': len(chores), 'mandatory_tasks_count': len(mandatory_tasks), 'calendar_events': events, 'household_chores': chores, 'mandatory_tasks': mandatory_tasks, 'workload_level': workload_level, 'stress_score': stress_score, 'meal_plan': meal_plan, 'dinner_plan': dinner_plan, 'evening_workload_level': evening_workload_level, 'evening_stress_score': evening_stress_score, 'wellbeing_recommendation': wellbeing, 'ai_summary': ai_summary}

@app.get('/dashboard/yesterday')
def dashboard_yesterday():
    events = _calendar_events_for_day(-1)
    workload_level, stress_score = calculate_workload_level(len(events))
    mandatory = len([e for e in events if e.get('priority') == 'mandatory'])
    optional = len([e for e in events if e.get('priority') == 'optional'])
    return {'calendar_events_count': len(events), 'mandatory_meetings': mandatory, 'optional_meetings': optional, 'workload_level': workload_level, 'stress_score': stress_score, 'quick_summary': f'Yesterday had {len(events)} meetings with {mandatory} mandatory and {optional} optional items.'}

@app.get('/dashboard/tomorrow')
def dashboard_tomorrow():
    events = _calendar_events_for_day(1)
    prefs = load_json_file(PREFERENCES_FILE, {'food_type':'vegetarian','dislikes':[],'preferred_cuisine':'Indian','breakfast_time':'08:30','lunch_time':'13:00','dinner_time':'20:00'})
    workload_level, stress_score = calculate_workload_level(len(events))
    mandatory = len([e for e in events if e.get('priority') == 'mandatory'])
    optional = len([e for e in events if e.get('priority') == 'optional'])
    ideas = build_tomorrow_prep(events, workload_level)
    breakfast_plan = get_inventory_driven_meal_plan(DATA_FILE, 'Breakfast', 2, prefs, workload_level, stress_score)
    return {'calendar_events_count': len(events), 'mandatory_meetings': mandatory, 'optional_meetings': optional, 'workload_level': workload_level, 'stress_score': stress_score, 'prep_ideas': ideas, 'events': events, 'tomorrow_breakfast': breakfast_plan.get('recommended_meals', [])}

@app.get('/dashboard/weekly-summary')
def get_weekly_summary():
    events = get_todays_calendar_events()
    workload_level, stress_score = calculate_workload_level(len(events))
    total_minutes_saved = 324
    return {'weekly_time_saved_minutes': total_minutes_saved, 'weekly_time_saved_hours': round(total_minutes_saved/60, 2), 'current_workload_level': workload_level, 'current_stress_score': stress_score, 'insight': 'The assistant reduces repetitive decision-making by converting schedule and home planning into actionable suggestions.'}
