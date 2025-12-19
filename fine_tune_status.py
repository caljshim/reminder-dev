from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()

openai_api_key = os.getenv("OPENAI_SECRET_KEY", "default_fallback")

client = OpenAI(api_key=openai_api_key)

job_id = "ftjob-nTFd3MJhF8WGWRfgkqdyBAxt"  # from previous step

job = client.fine_tuning.jobs.retrieve(job_id)
print("Status:", job.status)
print("Result:", job)
