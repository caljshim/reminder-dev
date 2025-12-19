from dotenv import load_dotenv
import os
from openai import OpenAI

load_dotenv()

openai_api_key = os.getenv("OPENAI_SECRET_KEY", "default_fallback")

client = OpenAI(api_key=openai_api_key)

# Upload the JSONL file
training_file = client.files.create(
    file=open("reminder_goon.jsonl", "rb"),
    purpose="fine-tune"
)

print("Training file ID:", training_file.id)
