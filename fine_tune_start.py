from dotenv import load_dotenv
import os
from openai import OpenAI

load_dotenv()

openai_api_key = os.getenv("OPENAI_SECRET_KEY", "default_fallback")

client = OpenAI(api_key=openai_api_key)

training_file_id = "file-RkYCKQGifhhT5BhQJr2y3M"  # <-- paste from previous step

job = client.fine_tuning.jobs.create(
    training_file=training_file_id,
    model="gpt-4.1-mini-2025-04-14"
)

print("Fine-tune job ID:", job.id)
