from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse
from dotenv import load_dotenv
import os
from openai import OpenAI
from threading import Thread
import time
import json

# Load .env file
load_dotenv()

app = Flask(__name__)

# Example: read a variable from .env
openai_api_key = os.getenv("OPENAI_SECRET_KEY", "default_fallback")

client = OpenAI(api_key=openai_api_key)

@app.route("/sms", methods=["POST"])
def sms_webhook():
    """
    Twilio will POST incoming SMS here.
    We respond with simple TwiML that says 'hello'.
    """

    incoming_msg = request.form.get("Body", "")
    from_number = request.form.get("From", "")

    print("Received message:", incoming_msg)
    print("From number:", from_number)

    resp = MessagingResponse()
    resp.message("hello")
    return str(resp)

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

def send_reminder(delay_seconds, msg, verification):
    print(verification)
    time.sleep(delay_seconds)
    print(f"REMINDER: {msg}")
    return

@app.route("/test-openai", methods=["POST"])
def openai_test():
    incoming_msg = (request.form.get("Body", "") or "").strip()

    if not incoming_msg:
        return {"status": "error", "message": "Boss, you didn't tell me anything to remember."}, 400

    # 1) Parse the reminder
    seconds, reminder_text = parse_reminder(incoming_msg)

    # Basic validation
    if seconds is None or not isinstance(seconds, int) or seconds <= 0:
        # Let the goon complain politely about missing time
        goon_res = client.chat.completions.create(
            model=GOON_MODEL,
            temperature=0.7,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an overworked but loyal mob boss's goon who "
                        "handles reminders. Keep replies short, dry, casual. "
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"The boss said: '{incoming_msg}'. "
                        "You couldn't figure out when they want the reminder. "
                        "Ask them to give you a time in seconds or a clear duration."
                    ),
                },
            ],
        )
        msg = goon_res.choices[0].message.content.strip()
        return {"status": "error", "message": msg}, 200

    # 2) Generate in-character verification
    verification_msg = generate_verification(incoming_msg, seconds, reminder_text)

    # 3) Schedule the reminder in the background
    Thread(
        target=send_reminder,
        args=(seconds, reminder_text, verification_msg),
        daemon=True,
    ).start()

    # 4) Respond to the user (e.g. Twilio will send this back as SMS body if you format TwiML)
    return {"status": "ok", "message": verification_msg}, 200

@app.route("/test-goon-json", methods=["POST"])
def test_goon_json():
    """
    Single-call version:
    - Uses the fine-tuned goon model
    - Parses seconds + message
    - Generates in-character verification
    - Returns JSON with those fields
    """
    incoming_msg = (request.form.get("Body", "") or "").strip()

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
        Thread(
            target=send_reminder,
            args=(seconds, reminder_text, verification_msg),
            daemon=True,
        ).start()
        status = "ok"
    else:
        # No valid time parsed – we still return the verification (likely asking for clarification)
        status = "needs_time"

    return {
        "status": status,
        "seconds": seconds,
        "message": reminder_text,
        "verification": verification_msg,
    }, 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)