from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse
from dotenv import load_dotenv
import os
from openai import OpenAI
from threading import Thread
import time
import json
from vonage import Vonage, Auth
from vonage_sms import SmsMessage, SmsResponse

# Load .env file
load_dotenv()

app = Flask(__name__)

# Example: read a variable from .env
openai_api_key = os.getenv("OPENAI_SECRET_KEY", "default_fallback")

client = OpenAI(api_key=openai_api_key)

VONAGE_API_SECRET = os.getenv("VONAGE_API_SECRET")
VONAGE_API_KEY = os.getenv("VONAGE_API_KEY")
VONAGE_FROM = os.getenv("VONAGE_FROM_NUMBER", "")
ALLOWED_NUMBER = os.getenv("ALLOWED_NUMBER", "")

vonage = None
if VONAGE_API_KEY and VONAGE_API_SECRET:
    auth = Auth(api_key=VONAGE_API_KEY, api_secret=VONAGE_API_SECRET)
    vonage = Vonage(auth=auth)

def send_sms(to_number: str, text: str):
    if not vonage:
        return {"status": "error", "message": "Vonage client not configured"}, 500
    if not VONAGE_FROM:
        return {"status": "error", "message": "VONAGE_FROM_NUMBER not set"}, 500

    message = SmsMessage(to=to_number, from_=VONAGE_FROM, text=text)
    response: SmsResponse = vonage.sms.send(message)
    return {"status": "ok", "response": response.model_dump(exclude_unset=True)}, 200


@app.route("/sms", methods=["GET", "POST"])
def sms_webhook():
    """
    Inbound SMS webhook (Vonage or Twilio).
    Uses the goon JSON flow and sends SMS replies.
    """
    incoming_msg = request.values.get("text") or request.form.get("Body", "")
    from_number = request.values.get("msisdn") or request.form.get("From", "")

    if ALLOWED_NUMBER and from_number and from_number != ALLOWED_NUMBER:
        return {"status": "forbidden"}, 403

    return test_goon_json(incoming_msg=incoming_msg, from_number=from_number)

def parse_reminder(incoming_msg: str) -> tuple[int | None, str]:
    """
    Use a cheap, non-fine-tuned model to parse the reminder text.
    Returns (seconds, message). seconds may be None if parsing fails.
    """
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        temperature=0,
        max_tokens=40,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "Parse reminder commands. Return ONLY JSON:\n"
                    '{"seconds": <int or null>, "message": "<string>"}'
                ),
            },
            {"role": "user", "content": incoming_msg},
        ],
    )

    data = json.loads(response.choices[0].message.content)

    seconds = data.get("seconds")
    message = data.get("message") or incoming_msg

    return seconds, message

GOON_MODEL = "ft:gpt-4.1-mini-2025-04-14:personal::Clp4wC0B"  # your FT id

def generate_verification(incoming_msg: str, seconds: int, message: str) -> str:
    """
    Use the fine-tuned mob goon model to generate a short, in-character
    confirmation line for the user.
    """
    res = client.chat.completions.create(
        model=GOON_MODEL,
        temperature=0.9,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an overworked but fiercely loyal mob boss's goon "
                    "who handles reminders. You sound aloof but devoted, "
                    "keep replies short, dry, and casual. Always call the user 'boss'. "
                    "Reply in 1–2 short sentences max."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"The boss said: '{incoming_msg}'.\n"
                    f"Parsed reminder: {seconds} seconds from now, "
                    f"message: '{message}'.\n"
                    "Confirm the reminder in your usual style."
                ),
            },
        ],
    )

    return res.choices[0].message.content.strip()

def send_reminder(delay_seconds, msg, to_number):
    time.sleep(delay_seconds)
    if to_number:
        send_sms(to_number, msg)
    else:
        print(f"REMINDER: {msg}")
    return

@app.route("/test-openai", methods=["POST"])
def openai_test():
    incoming_msg = request.form.get("Body", "")
    return test_goon_json(incoming_msg=incoming_msg, from_number=None)

@app.route("/test-goon-json", methods=["POST"])
def test_goon_json(incoming_msg=None, from_number=None):
    """
    Single-call version:
    - Uses the fine-tuned goon model
    - Parses seconds + message
    - Generates in-character verification
    - Returns JSON with those fields
    """
    if incoming_msg is None:
        incoming_msg = request.form.get("Body", "") or request.values.get("text", "")

    if not incoming_msg:
        return {
            "status": "error",
            "message": "Boss, you didn't tell me what to remember."
        }, 400

    # One call: parse + persona + verification
    response = client.chat.completions.create(
        model=GOON_MODEL,
        temperature=0.8,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an overworked but fiercely loyal mob boss's goon "
                    "who handles reminders. You sound aloof but devoted, "
                    "keep replies short, dry, and casual, and always call the user 'boss'.\n\n"
                    "Task:\n"
                    "- Read the boss's message asking for a reminder.\n"
                    "- Extract how many seconds from now to wait.\n"
                    "- Extract the reminder message.\n"
                    "- Create a short fun verification in your usual voice.\n\n"
                    "Return ONLY valid JSON with exactly these keys:\n"
                    "{\n"
                    '  "seconds": <integer or null>,\n'
                    '  "message": "<string>",\n'
                    '  "verification": "<string>"\n'
                    "}\n\n"
                    "- seconds: delay in seconds from now (integer). If you truly can't tell, use null.\n"
                    "- message: short reminder phrase.\n"
                    "- verification: 1–2 short sentences, talking to 'boss' in your style.\n"
                    "No extra keys. No extra text outside the JSON."
                ),
            },
            {"role": "user", "content": incoming_msg},
        ],
    )

    data = json.loads(response.choices[0].message.content)

    seconds = data.get("seconds")
    reminder_text = data.get("message") or incoming_msg
    verification_msg = data.get("verification") or ""

    # If we got a valid delay, schedule the reminder
    if isinstance(seconds, int) and seconds > 0:
        if from_number and verification_msg:
            send_sms(from_number, verification_msg)
        Thread(
            target=send_reminder,
            args=(seconds, reminder_text, from_number),
            daemon=True,
        ).start()
        status = "ok"
    else:
        # No valid time parsed – we still return the verification (likely asking for clarification)
        if from_number and verification_msg:
            send_sms(from_number, verification_msg)
        status = "needs_time"

    return {
        "status": status,
        "seconds": seconds,
        "message": reminder_text,
        "verification": verification_msg,
    }, 200


@app.route("/test", methods=["GET", "POST"])
def vonage_test():
    """
    Vonage inbound SMS webhook.
    If a user texts 'test', reply with 'Hello!'.
    """
    incoming_text = (request.values.get("text", "") or "").strip()
    from_number = (request.values.get("msisdn", "") or "").strip()

    if not incoming_text or not from_number:
        return {"status": "error", "message": "Missing text or msisdn"}, 400

    if ALLOWED_NUMBER and from_number != ALLOWED_NUMBER:
        return {"status": "forbidden"}, 403

    if incoming_text.lower() == "test":
        if not vonage:
            return {"status": "error", "message": "Vonage client not configured"}, 500
        if not VONAGE_FROM:
            return {"status": "error", "message": "VONAGE_FROM_NUMBER not set"}, 500

        message = SmsMessage(to=from_number, from_=VONAGE_FROM, text="Hello!")
        response: SmsResponse = vonage.sms.send(message)
        return {"status": "ok", "response": response.model_dump(exclude_unset=True)}, 200

    return {"status": "ignored"}, 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
