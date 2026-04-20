from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv()

# MongoDB Setup
client = AsyncIOMotorClient(os.getenv("MONGO_URL"))
db = client.cognipulse_db
users_col = db.get_collection("users")
history_col = db.get_collection("chat_history")