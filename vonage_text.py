from fastapi import FastAPI
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import os
from vonage import Vonage, Auth
from vonage_sms import SmsMessage, SmsResponse

load_dotenv()

VONAGE_API_SECRET = os.getenv("VONAGE_API_SECRET")
VONAGE_API_KEY = os.getenv("VONAGE_API_KEY")

auth = Auth(api_key=VONAGE_API_KEY, api_secret=VONAGE_API_SECRET)
vonage = Vonage(auth=auth)


message = SmsMessage(to='15038064409', from_='14142847579', text='Hello, World!')
response: SmsResponse = vonage.sms.send(message)

print(response.model_dump(exclude_unset=True))


print(response)