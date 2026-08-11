import os
import requests
from dotenv import load_dotenv

load_dotenv()

class TBAClient:
    BASE_URL = "https://www.thebluealliance.com/api/v3"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("TBA_AUTH_KEY", "")
        self.headers = {"X-TBA-Auth-Key": self.api_key}

    def get_team(self, team_key: str):
        """Fetches general team info (e.g. team_key='frc254')."""
        response = requests.get(f"{self.BASE_URL}/team/{team_key}", headers=self.headers)
        return response.json() if response.status_code == 200 else None

    def get_event_matches(self, event_key: str):
        """Fetches matches for a given event (e.g., event_key='2026cmp')."""
        response = requests.get(f"{self.BASE_URL}/event/{event_key}/matches", headers=self.headers)
        return response.json() if response.status_code == 200 else None