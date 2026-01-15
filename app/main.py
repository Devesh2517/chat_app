from fastapi import FastAPI
from .user.api import router as user_router
from .chat.api import router as chat_router

import os
import asyncio
import random
import uuid
from datetime import datetime, timezone

import socketio
from socketio import ASGIApp
import motor.motor_asyncio

fastapi_app = FastAPI(title="Chat Application", version="1.0.0")

fastapi_app.include_router(user_router, prefix="/users", tags=["users"])
fastapi_app.include_router(chat_router, prefix="/chat", tags=["chat"])

# DB (used by realtime handlers)
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = mongo_client.chat_app
users_col = db.users
messages_col = db.messages

# Socket.IO setup
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
app = ASGIApp(sio, other_asgi_app=fastapi_app)  # exported ASGI app for Uvicorn

# In-memory routing maps
sid_to_user = {}
user_last_sid = {}

def now_ts():
    return datetime.now(timezone.utc).isoformat()

async def get_user_by_token(token: str):
    if not token:
        return None
    return await users_col.find_one({"token": token})

@sio.event
async def connect(sid, environ, auth):
    token = auth.get("token") if isinstance(auth, dict) else None
    user = await get_user_by_token(token)
    if not user:
        guest_id = f"guest_{int(datetime.now().timestamp()*1000)}"
        user = {"user_id": guest_id, "display_name": guest_id, "identity_version": 1}
    sid_to_user[sid] = {"user": user, "connected_at": now_ts()}
    user_last_sid[str(user.get("user_id"))] = sid
    await sio.emit("system", {"msg": f"{user.get('display_name')} connected"}, to=sid)

@sio.event
async def disconnect(sid):
    info = sid_to_user.pop(sid, None)
    if info:
        u = info["user"]
        await sio.emit("system", {"msg": f"{u.get('display_name')} disconnected"})

@sio.on("send_message")
async def handle_send_message(sid, data):
    info = sid_to_user.get(sid)
    if not info:
        return
    sender = info["user"]
    recipient = data.get("to")
    text = data.get("text", "")
    msg = {
        "sender_id": str(sender.get("user_id")),
        "recipient_id": str(recipient),
        "text": text,
        "ts": now_ts(),
        "delivered": False,
        "read": False,
    }
    res = await messages_col.insert_one(msg)
    msg["_id"] = str(res.inserted_id)

    # Latency illusion (temporal wobble)
    wobble = random.uniform(0, 0.6)
    if random.random() < 0.02:
        wobble += random.uniform(0.6, 1.4)
    await asyncio.sleep(wobble)

    target_sid = user_last_sid.get(str(recipient))
    if target_sid:
        await sio.emit("message", msg, to=target_sid)
        await messages_col.update_one({"_id": res.inserted_id}, {"$set": {"delivered": True, "delivered_at": now_ts()}})
        await sio.emit("delivered", {"message_id": msg["_id"]}, to=sid)

@sio.on("read")
async def handle_read(sid, data):
    mid = data.get("message_id")
    if not mid:
        return
    await messages_col.update_one({"_id": mid}, {"$set": {"read": True, "read_at": now_ts()}})
    await sio.emit("read_ack", {"message_id": mid}, to=sid)

@sio.on("typing")
async def handle_typing(sid, data):
    info = sid_to_user.get(sid)
    if not info:
        return
    recipient = data.get("to")
    typing = bool(data.get("typing"))
    target_sid = user_last_sid.get(str(recipient))
    payload = {"from": str(info["user"].get("user_id")), "typing": typing}
    if target_sid:
        await sio.emit("typing", payload, to=target_sid)


phantom_task = None
async def phantom_typing_loop():
    while True:
        await asyncio.sleep(random.uniform(3, 8))
        if random.random() < 0.12:
            sids = list(sid_to_user.keys())
            if len(sids) >= 2:
                a, b = random.sample(sids, 2)
                ua = sid_to_user.get(a)["user"]
                await sio.emit("typing", {"from": str(ua.get("user_id")), "typing": True}, to=b)
                await asyncio.sleep(random.uniform(1.0, 3.0))
                await sio.emit("typing", {"from": str(ua.get("user_id")), "typing": False}, to=b)

@fastapi_app.on_event("startup")
async def _startup():
    global phantom_task
    if phantom_task is None:
        phantom_task = asyncio.create_task(phantom_typing_loop())
