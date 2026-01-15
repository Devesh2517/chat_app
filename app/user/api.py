from fastapi import APIRouter, Body, HTTPException, Request
import random
import uuid
from datetime import datetime, timezone
import os
import motor.motor_asyncio
from .schema import *
router = APIRouter()
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = client.chat_app
users_col = db.users

def now_ts():
    return datetime.now(timezone.utc).isoformat()

@router.post("/auth/request_otp")
async def request_otp(payload: OtpSentPayload):
    #to convert payload from object form to dict
    payload_dict = payload.model_dump()
    mobile = payload_dict.get("mobile")

    if not mobile:
        raise HTTPException(status_code=400, detail="mobile required")
    user = await users_col.find_one({"mobile": mobile})


    if not user:
        new = {"mobile": mobile, "display_name": mobile, "identity_version": 1, "created_at": now_ts()}
        res = await users_col.insert_one(new)
        uid = str(res.inserted_id)
        await users_col.update_one({"_id": res.inserted_id}, {"$set": {"user_id": uid}})
        user = await users_col.find_one({"_id": res.inserted_id})
    otp = str(random.randint(100000, 999999))

    await users_col.update_one({"_id": user["_id"]}, {"$set": {"last_otp": otp, "otp_at": now_ts()}})
    
    return {"otp": otp, "message": "OTP returned (emulated)"}

@router.post("/auth/verify")
async def verify_otp(payload: OtpVerifyPayload):

    #to convert payload from object form to dict
    payload_dict = payload.model_dump()
    mobile = payload_dict.get("mobile")
    otp = payload_dict.get("otp")


    if not mobile or not otp:
        raise HTTPException(status_code=400, detail="mobile and otp required")
    

    user = await users_col.find_one({"mobile": mobile})
    if not user or user.get("last_otp") != otp:
        raise HTTPException(status_code=401, detail="invalid otp")
    
    if random.random() < 0.03:
        new_ver = (user.get("identity_version", 1) or 1) + 1
        await users_col.update_one({"_id": user["_id"]}, {"$set": {"identity_version": new_ver, "display_name": f"{user.get('display_name')}_{new_ver}"}})
    
    token = uuid.uuid4().hex
    await users_col.update_one({"_id": user["_id"]}, {"$set": {"token": token, "last_login": now_ts()}})
    user = await users_col.find_one({"_id": user["_id"]})
    
    return {"token": token, "user_id": user.get("user_id"), "display_name": user.get("display_name")}

@router.get("/me")
async def read_users_me(request: Request):

    
    token = request.headers.get("Authorization")
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = await users_col.find_one({"token": token})
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {
        "user_id": user.get("user_id"),
        "display_name": user.get("display_name"),
        "mobile": user.get("mobile"),
        "identity_version": user.get("identity_version"),
        "last_login": user.get("last_login"),
    }
