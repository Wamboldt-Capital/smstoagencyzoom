import requests
import os
from dotenv import load_dotenv

load_dotenv()

# Load AgencyZoom API credentials from environment variables
AGENCY_ZOOM_BASE_URL = os.getenv("AGENCY_ZOOM_BASE_URL", "https://api.agencyzoom.com/v1")
AGENCY_ZOOM_API_KEY = os.getenv("AGENCY_ZOOM_API_KEY")

def get_text_messages(user_id=None, lead_id=None, customer_id=None):
    """
    Fetches text (SMS) messages from AgencyZoom for the specified user/lead/customer.
    At least one of user_id, lead_id, or customer_id must be provided.
    """
    headers = {
        "Authorization": f"Bearer {AGENCY_ZOOM_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Build the endpoint and payload based on what you want to fetch
    # Example: /messages?user_id=xxx OR /messages?lead_id=xxx OR /messages?customer_id=xxx
    params = {}
    if user_id:
        params['user_id'] = user_id
    if lead_id:
        params['lead_id'] = lead_id
    if customer_id:
        params['customer_id'] = customer_id

    # Adjust endpoint if your API documentation specifies differently
    url = f"{AGENCY_ZOOM_BASE_URL}/messages"
    
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    messages = response.json()

    print("Fetched Messages:")
    for msg in messages.get('messages', []):
        print(f"From: {msg.get('from')}, To: {msg.get('to')}, Date: {msg.get('date')}\nText: {msg.get('text')}\n---")

if __name__ == "__main__":
    # Example usage
    # Replace with actual IDs from your AgencyZoom account
    get_text_messages(user_id="YOUR_USER_ID")
    # or get_text_messages(lead_id="LEAD_ID")
    # or get_text_messages(customer_id="CUSTOMER_ID")
