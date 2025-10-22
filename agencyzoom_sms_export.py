import requests
import os

AGENCYZOOM_USERNAME = os.environ["AGENCY_ZOOM_USERNAME"]
AGENCYZOOM_PASSWORD = os.environ["AGENCY_ZOOM_PASSWORD"]

def login_agencyzoom(username, password):
    url = "https://api.agencyzoom.com/v1/api/auth/login"
    data = {"username": username, "password": password}
    resp = requests.post(url, json=data)
    print(resp.text)  # Debug output for login errors
    resp.raise_for_status()
    return resp.json()["jwt"]

def get_sms_threads(token, page_size=10):
    url = "https://api.agencyzoom.com/v1/api/text-thread/list"
    headers = {"Authorization": f"Bearer {token}"}
    data = {
        "pageSize": page_size,
        "page": 0,
        "sort": "lastMessageDate",
        "order": "desc"
    }
    resp = requests.post(url, json=data, headers=headers)
    resp.raise_for_status()
    return resp.json().get("threadInfo", [])

def get_thread_messages(token, thread_id, page_size=3):
    url = "https://api.agencyzoom.com/v1/api/text-thread/text-thread-detail"
    headers = {"Authorization": f"Bearer {token}"}
    data = {
        "threadId": thread_id,
        "pageSize": page_size,
        "page": 0
    }
    resp = requests.post(url, json=data, headers=headers)
    resp.raise_for_status()
    return resp.json().get("messageInfo", [])

def main():
    token = login_agencyzoom(AGENCYZOOM_USERNAME, AGENCYZOOM_PASSWORD)
    threads = get_sms_threads(token, page_size=5)
    
    with open("agencyzoom_sms_export.txt", "w", encoding="utf-8") as f:
        for thread in threads:
            thread_id = thread.get("id", "")
            subject = thread.get("subject", "")
            snippet = thread.get("snippet", "")
            contact_name = thread.get("contactName", "")
            phone_number = thread.get("phoneNumber", "")
            last_date = thread.get("lastMessageDate", "")
            
            messages = get_thread_messages(token, thread_id, page_size=2)
            for message in messages:
                date = message.get("messageDate", "")
                body = message.get("body", "")
                sender = message.get("senderName", "")
                f.write("========================================\n")
                f.write(f"Thread Subject: {subject}\n")
                f.write(f"Thread Snippet: {snippet}\n")
                f.write(f"Contact Name: {contact_name}\n")
                f.write(f"Phone Number: {phone_number}\n")
                f.write(f"Date: {date}\n")
                f.write(f"Sender: {sender}\n")
                f.write(f"Message: {body}\n")
                f.write("========================================\n\n")

    print("Export complete! Open 'agencyzoom_sms_export.txt' to view your messages.")

if __name__ == "__main__":
    main()
