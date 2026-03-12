import os
import json
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

OAUTH_STATE_FILE = "oauth_states.json"

def load_oauth_states():
    if not os.path.exists(OAUTH_STATE_FILE):
        return {}
    with open(OAUTH_STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_oauth_states(states):
    with open(OAUTH_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(states, f)

app = FastAPI(title="AI Life-Load Assistant API")

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

ACTIVE_FLOWS = {}


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


@app.get("/")
def home():
    return {"message": "AI Life-Load Assistant API is running", "status": "ok"}


@app.get("/health")
def health():
    return {"status": "healthy"}


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


@app.get("/calendar/upcoming")
def get_upcoming_events():
    service = get_calendar_service()

    now = datetime.now(timezone.utc).isoformat()

    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now,
            maxResults=10,
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

    return {"count": len(cleaned), "events": cleaned}


@app.get("/ai/workload")
def analyze_workload():
    service = get_calendar_service()

    now = datetime.now(timezone.utc).isoformat()

    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now,
            maxResults=10,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = events_result.get("items", [])
    meeting_count = len(events)

    if meeting_count == 0:
        load = "Free day"
        advice = "Great day to focus on deep work."
        stress_score = 1
    elif meeting_count <= 3:
        load = "Light workload"
        advice = "Take a short breathing break before the next event."
        stress_score = 3
    elif meeting_count <= 6:
        load = "Moderate workload"
        advice = "Schedule a 2-minute breathing reset between meetings."
        stress_score = 6
    else:
        load = "Heavy workload"
        advice = "Block a recovery break and postpone one non-urgent task."
        stress_score = 8

    return {
        "meetings_today": meeting_count,
        "workload_level": load,
        "stress_score": stress_score,
        "suggestion": advice,
    }

@app.get("/debug/env")
def debug_env():
    return {
        "redirect_uri": REDIRECT_URI
    }