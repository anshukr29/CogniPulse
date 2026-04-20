import os
import base64
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from groq import Groq
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId  
from datetime import datetime  
import google.generativeai as genai

app = FastAPI()

# 1. CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Database & Groq Setup
MONGO_URL = "mongodb://localhost:27017" 
client = AsyncIOMotorClient(MONGO_URL)
db = client.cognipulse

groq_client = Groq(api_key="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")

 
genai.configure(api_key="AIzaSyAY88OIu6fhDOa5wIBh-A2HsQJN0FZhMko")

 
def get_working_vision_model():
    try:
        available_models = [m.name for m in genai.list_models()]
        if 'models/gemini-1.5-flash' in available_models:
            return 'gemini-1.5-flash'
        elif 'models/gemini-1.5-pro' in available_models:
            return 'gemini-1.5-pro'
        elif 'models/gemini-pro-vision' in available_models:
            return 'gemini-pro-vision'
        else:
            return 'gemini-1.5-flash' # Default fallback
    except Exception as e:
        return 'gemini-1.5-flash'

 
selected_model_name = get_working_vision_model()
print(f"🚀 AI Engine initialized with Vision Model: {selected_model_name}")
gemini_model = genai.GenerativeModel(selected_model_name)

 
class SignupRequest(BaseModel):
    name: str
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class ChatRequest(BaseModel):
    message: str
    user_id: str
    image_data: str = None 

 
@app.post("/api/signup")
async def signup(request: SignupRequest):
    existing_user = await db.users.find_one({"email": request.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="User already exists")
    
    user_data = {
        "name": request.name,
        "email": request.email,
        "password": request.password  
    }
    result = await db.users.insert_one(user_data)
    return {"user_id": str(result.inserted_id), "name": request.name}

@app.post("/api/login")
async def login(request: LoginRequest):
    user = await db.users.find_one({"email": request.email, "password": request.password})
    if user:
        return {"user_id": str(user["_id"]), "name": user["name"]}
    raise HTTPException(status_code=401, detail="Invalid credentials")

# --- HINDSIGHT LOGIC ---
async def get_hindsight_memory(user_id: str):
    cursor = db.chat_history.find({"user_id": user_id}).sort("_id", -1).limit(5)
    history = await cursor.to_list(length=5)
    memory_text = ""
    for chat in reversed(history):
        memory_text += f"User: {chat['user_msg']}\nAI: {chat['ai_msg']}\n"
    return memory_text

# --- CHAT ENDPOINT ---
@app.post("/api/chat")
async def chat_with_ai(request: ChatRequest):
    try:
        now = datetime.now()
        current_dt = now.strftime("%A, %B %d, %Y - %I:%M %p")
        memory = await get_hindsight_memory(request.user_id)
        
        ai_reply = ""

        # 🖼️ CASE 1: Agar user ne Image bheji hai
        if request.image_data:
            header, encoded_data = request.image_data.split(',', 1)
            mime_type = header.split(';')[0].replace('data:', '')
            image_bytes = base64.b64decode(encoded_data)
            
            image_part = {
                "mime_type": mime_type,
                "data": image_bytes
            }
            
            gemini_prompt = f"System Context: You are CogniPulse AI. Today is {current_dt}.\nUser Memory:\n{memory}\n\nUser Question: {request.message}"
            
            # Agar user ne sirf photo bheji bina text ke
            if not request.message:
                gemini_prompt = "Describe this image in detail."

            print("🖼️ Analyzing Image with Gemini...")
            response = gemini_model.generate_content([gemini_prompt, image_part])
            ai_reply = response.text

        # 💬 CASE 2: Agar sirf normal text hai (Groq)
        else:
            print("💬 Processing Text with Groq Llama 3.1...")
            system_prompt = f"You are CogniPulse AI. Today is {current_dt}. Context: {memory}"
            chat_completion = groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": request.message}
                ],
                model="llama-3.1-8b-instant",
            )
            ai_reply = chat_completion.choices[0].message.content

        # Save to MongoDB
        user_msg_log = request.message if request.message else "📸 [Image Uploaded]"
        await db.chat_history.insert_one({
            "user_id": request.user_id,
            "user_msg": user_msg_log,
            "ai_msg": ai_reply,
            "timestamp": now
        })
        
        return {"reply": ai_reply}
        
    except Exception as e:
        print(f"🔴 Error in /api/chat: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- LOGS & DELETE ---
@app.get("/api/logs/{user_id}")
async def get_logs(user_id: str):
    cursor = db.chat_history.find({"user_id": user_id}).sort("_id", -1)
    history = await cursor.to_list(length=100)
    return [{"user": c["user_msg"], "ai": c["ai_msg"], "id": str(c["_id"])} for c in history]

@app.delete("/api/logs/{log_id}")
async def delete_memory(log_id: str):
    await db.chat_history.delete_one({"_id": ObjectId(log_id)})
    return {"message": "Neural record erased"}

@app.delete("/api/chat/clear/{user_id}")
async def clear_chat(user_id: str):
    await db.chat_history.delete_many({"user_id": user_id})
    return {"message": "Memory wiped"}