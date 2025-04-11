import os
import datetime
import pickle
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

SCOPES = ['https://www.googleapis.com/auth/calendar']
TOKEN_PATH = 'token.pkl'
CREDENTIALS_PATH = 'credentials.json'
REDIRECT_URI = 'http://localhost:5000/oauth2callback'


def get_calendar_service():
    creds = None
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = Flow.from_client_secrets_file(
                CREDENTIALS_PATH,
                scopes=SCOPES,
                redirect_uri=REDIRECT_URI
            )
            auth_url, _ = flow.authorization_url(prompt='consent')
            return auth_url  # Return OAuth2 URL to handle login

    return build('calendar', 'v3', credentials=creds)


def save_token_from_flow(flow, authorization_response_url):
    flow.fetch_token(authorization_response=authorization_response_url)
    with open(TOKEN_PATH, 'wb') as token:
        pickle.dump(flow.credentials, token)
    return True



def add_event_to_calendar(task):
    service = get_calendar_service()
    if isinstance(service, str):
        return service  # Still needs authentication

    event = {
        'summary': task['task'],
        'start': {
            'dateTime': task['start'],
            'timeZone': 'Asia/Kolkata'
        },
        'end': {
            'dateTime': task['end'],
            'timeZone': 'Asia/Kolkata'
        }
    }

    created_event = service.events().insert(calendarId='primary', body=event).execute()
    return {
        'htmlLink': created_event.get('htmlLink'),
        'id': created_event.get('id')
    }