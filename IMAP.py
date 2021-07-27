from imapclient import IMAPClient
import email
import time
from datetime import datetime
from html.parser import HTMLParser
from apns2.client import APNsClient, Notification, NotificationPriority
from apns2.payload import Payload, PayloadAlert
from apns2.credentials import TokenCredentials
from bs4 import BeautifulSoup
import threading
import pickle
import pytz
from pathlib import Path
from Config import *

pst = pytz.timezone("America/Los_Angeles")
plain = ""
html = ""
encrypted = ""

lastUID = 0
last_notification_count = 0
notification_count = 0

lastLogin = 0

# create folder
Path("emails").mkdir(parents=False, exist_ok=True)


def reset():
    global plain
    global html
    global encrypted
    plain = ""
    html = ""
    encrypted = ""


def handleMessage(part):
    if part.get_content_type() == "text/plain":
        return 1, part.get_payload(decode=True)
    if part.get_content_type() == "text/html":
        return 2, part.get_payload(decode=True)
    if part.get_filename() != None:
        if part.get_filename() == "encrypted.asc":
            return 3, part.get_payload(decode=True)
    return 0, ""


def getMessage(email_message):
    global plain
    global html
    global encrypted

    if email_message.is_multipart():
        for part in email_message.get_payload():
            getMessage(part)
    else:
        type, msg = handleMessage(email_message)
        if type == 1:
            plain = msg
        elif type == 2:
            html = msg
        elif type == 3:
            encrypted = msg


def pushNotification(subject, from_address, uid, text, encrypted):
    # push notification
    token_credentials = TokenCredentials(
        auth_key_path=AUTH_KEY_PATH, auth_key_id=AUTH_KEY_ID, team_id=TEAM_ID
    )
    notification_client = APNsClient(credentials=token_credentials, use_sandbox=True)

    payload = PayloadAlert(title=subject, body=text)
    custom = {"from": from_address, "uid": uid, "encrypted": encrypted}
    payload = Payload(
        alert=payload,
        sound="default",
        badge=notification_count,
        mutable_content=encrypted,
        custom=custom,
    )

    notifications = []
    for token in APNS_TOKENS:
        notifications.append(Notification(payload=payload, token=token))
    notification_client.send_notification_batch(
        notifications=notifications, topic=APNS_TOPIC
    )
    print("Sent Notifications")


def sendBadge(badge):
    # push notification
    token_credentials = TokenCredentials(
        auth_key_path=AUTH_KEY_PATH, auth_key_id=AUTH_KEY_ID, team_id=TEAM_ID
    )
    notification_client = APNsClient(credentials=token_credentials, use_sandbox=True)
    payload = Payload(badge=badge)

    notifications = []
    for token in APNS_TOKENS:
        notifications.append(Notification(payload=payload, token=token))
    notification_client.send_notification_batch(
        notifications=notifications, topic=APNS_TOPIC
    )
    print("Sent Badge Notifications")


def prepareForAPNs(subject, from_address, uid):
    if encrypted != "":
        # save PGP and push PGP message location
        try:
            with open("emails/" + str(uid), "w") as f:
                f.write(encrypted.decode("utf-8"))
            pushNotification(subject, from_address, uid, "", True)
        except Exception as e:
            print(e)
            pushNotification(subject, from_address, uid, "Unable to save data", False)
    elif plain != "":
        # push plain text
        text = " ".join(plain.decode("utf-8").replace(">", "").split())[:160]
        pushNotification(subject, from_address, uid, text, False)
    elif html != "":
        # push html
        bs = BeautifulSoup(html)
        text = bs.get_text()[:160]
        pushNotification(subject, from_address, uid, text, False)
    else:
        # push empty email?
        pushNotification(
            subject, from_address, uid, "This email doesn't have a body", False
        )
    reset()


def fetchLatest():
    print("Fetching at " + datetime.now(pst).strftime("%m/%d/%Y %H:%M:%S"))
    result = server.search("UNSEEN")
    sentMessage = False
    global lastUID
    global notification_count
    global last_notification_count

    if result != None and len(result) > 0:
        notification_count = len(result)
        if notification_count < 0:
            notification_count = 0
        last_notification_count = notification_count

        result = server.fetch([result[-1]], ["BODY.PEEK[]"])
        for uid, message_data in result.items():
            if lastUID < uid:
                email_message = email.message_from_bytes(message_data[b"BODY[]"])
                getMessage(email_message)
                prepareForAPNs(
                    email_message.get("Subject"), email_message.get("From"), uid
                )
                lastUID = uid
                sentMessage = True
    if not sentMessage and notification_count != last_notification_count:
        last_notification_count = notification_count
        sendBadge(last_notification_count)


def pause():
    if datetime.now(pst).hour < 8:
        return 3600
    else:
        return 120


def login():
    print("Login")
    global server
    global lastLogin
    server = IMAPClient(HOST)
    server.login(USERNAME, PASSWORD)
    server.select_folder("INBOX")
    lastLogin = time.time()


def logout():
    print("Logout")
    try:
        with open("record.txt", "wb") as f:
            pickle.dump([lastUID, last_notification_count], f)
    except:
        print("Cannot write")

    try:
        server.logout()
    except Exception as e:
        print("Unable to logout")
        print(e)


def start():
    try:
        starttime = time.time()
        while True:
            if time.time() - lastLogin > 3600:
                logout()
                login()

            fetchLatest()
            wait = pause()
            time.sleep(wait - ((time.time() - starttime) % wait))
    except KeyboardInterrupt:
        logout()
    except Exception as e:
        print(e)
        login()
        start()


try:
    with open("record.txt", "rb") as f:
        x = pickle.load(f)
        lastUID = x[0]
        last_notification_count = int(x[1])
except:
    print("Cannot read")


login()
start()
