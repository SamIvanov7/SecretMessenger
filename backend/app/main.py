from fastapi import FastAPI, Depends, HTTPException, status, Header, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import List, Optional, Dict
from datetime import datetime
from passlib.context import CryptContext
import jwt
from jwt import PyJWTError
import os
import json

from .database import engine, get_db
from .models import Base, User, Chat, ChatParticipant, Message, Contact

# Create tables only if they don't exist
# This is handled automatically by SQLAlchemy with create_all()
# which checks for table existence before creating
try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    # Log but don't crash if tables already exist
    print(f"Table creation skipped or failed: {e}")

app = FastAPI(title="SecretMessenger API")

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here")
ALGORITHM = "HS256"

# Security
security = HTTPBearer()

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)

    def disconnect(self, websocket: WebSocket, user_id: int):
        if user_id in self.active_connections:
            self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def send_to_user(self, user_id: int, message: dict):
        if user_id in self.active_connections:
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_json(message)
                except:
                    pass

    async def send_to_chat(self, chat_id: int, message: dict, db: Session, exclude_user_id: int = None):
        participants = db.query(ChatParticipant).filter(ChatParticipant.chat_id == chat_id).all()
        for participant in participants:
            if participant.user_id != exclude_user_id:
                await self.send_to_user(participant.user_id, message)

manager = ConnectionManager()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models
class UserCreate(BaseModel):
    username: str
    email: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    created_at: datetime

class ChatCreate(BaseModel):
    name: str
    participant_ids: List[int]

class ChatResponse(BaseModel):
    id: int
    name: str
    created_at: datetime

class MessageCreate(BaseModel):
    content: str

class MessageResponse(BaseModel):
    id: int
    chat_id: int
    sender_id: int
    sender_username: str
    content: str
    created_at: datetime

class ContactCreate(BaseModel):
    contact_username: str
    nickname: Optional[str] = None

class ContactResponse(BaseModel):
    id: int
    user_id: int
    contact_id: int
    contact_username: str
    contact_email: str
    nickname: Optional[str]
    created_at: datetime

class UserSearchResponse(BaseModel):
    id: int
    username: str

# Helper functions
def get_password_hash(password):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict):
    to_encode = data.copy()
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user

# Routes
@app.get("/")
async def root():
    return {"message": "SecretMessenger API is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/api/health")
async def api_health_check():
    return {"status": "healthy"}

@app.post("/api/register", response_model=UserResponse)
def register(user: UserCreate, db: Session = Depends(get_db)):
    # Check if user exists
    db_user = db.query(User).filter(
        (User.username == user.username) | (User.email == user.email)
    ).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username or email already registered")
    
    # Create new user
    hashed_password = get_password_hash(user.password)
    db_user = User(
        username=user.username,
        email=user.email,
        password_hash=hashed_password
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    return UserResponse(
        id=db_user.id,
        username=db_user.username,
        email=db_user.email,
        created_at=db_user.created_at
    )

@app.post("/api/login")
def login(user: UserLogin, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if not db_user or not verify_password(user.password, db_user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    access_token = create_access_token(data={"sub": db_user.id})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": UserResponse(
            id=db_user.id,
            username=db_user.username,
            email=db_user.email,
            created_at=db_user.created_at
        )
    }

@app.get("/api/users", response_model=List[UserResponse])
def get_users(db: Session = Depends(get_db)):
    users = db.query(User).all()
    return [
        UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            created_at=user.created_at
        ) for user in users
    ]

@app.post("/api/chats", response_model=ChatResponse)
def create_chat(chat: ChatCreate, db: Session = Depends(get_db)):
    # Create chat
    db_chat = Chat(name=chat.name)
    db.add(db_chat)
    db.commit()
    db.refresh(db_chat)
    
    # Add participants
    for user_id in chat.participant_ids:
        participant = ChatParticipant(
            chat_id=db_chat.id,
            user_id=user_id
        )
        db.add(participant)
    db.commit()
    
    return ChatResponse(
        id=db_chat.id,
        name=db_chat.name,
        created_at=db_chat.created_at
    )

@app.get("/api/chats", response_model=List[ChatResponse])
def get_user_chats(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Get all chats where user is a participant
    participants = db.query(ChatParticipant).filter(
        ChatParticipant.user_id == current_user.id
    ).all()
    
    chats = []
    for participant in participants:
        chat = db.query(Chat).filter(Chat.id == participant.chat_id).first()
        if chat:
            chats.append(ChatResponse(
                id=chat.id,
                name=chat.name,
                created_at=chat.created_at
            ))
    
    return chats

@app.post("/api/chats/{chat_id}/messages", response_model=MessageResponse)
async def send_message(chat_id: int, message: MessageCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Verify user is a participant in the chat
    participant = db.query(ChatParticipant).filter(
        ChatParticipant.chat_id == chat_id,
        ChatParticipant.user_id == current_user.id
    ).first()
    
    if not participant:
        raise HTTPException(status_code=403, detail="You are not a participant in this chat")
    
    # Create message
    db_message = Message(
        chat_id=chat_id,
        sender_id=current_user.id,
        content=message.content
    )
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    
    # Send via WebSocket to all chat participants
    await manager.send_to_chat(chat_id, {
        "type": "message",
        "chatId": chat_id,
        "message": {
            "id": db_message.id,
            "sender_id": current_user.id,
            "sender_username": current_user.username,
            "content": db_message.content,
            "created_at": db_message.created_at.isoformat()
        }
    }, db)
    
    return MessageResponse(
        id=db_message.id,
        chat_id=db_message.chat_id,
        sender_id=db_message.sender_id,
        sender_username=current_user.username,
        content=db_message.content,
        created_at=db_message.created_at
    )

@app.get("/api/chats/{chat_id}/messages", response_model=List[MessageResponse])
def get_messages(chat_id: int, db: Session = Depends(get_db)):
    messages = db.query(Message).filter(Message.chat_id == chat_id).order_by(Message.created_at).all()
    
    response = []
    for msg in messages:
        sender = db.query(User).filter(User.id == msg.sender_id).first()
        response.append(MessageResponse(
            id=msg.id,
            chat_id=msg.chat_id,
            sender_id=msg.sender_id,
            sender_username=sender.username if sender else "Unknown",
            content=msg.content,
            created_at=msg.created_at
        ))
    
    return response

# Contact Management Routes
@app.post("/api/contacts", response_model=ContactResponse)
def add_contact(contact: ContactCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Find the contact user by username
    contact_user = db.query(User).filter(User.username == contact.contact_username).first()
    if not contact_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check if contact already exists
    existing_contact = db.query(Contact).filter(
        Contact.user_id == current_user.id,
        Contact.contact_id == contact_user.id
    ).first()
    if existing_contact:
        raise HTTPException(status_code=400, detail="Contact already exists")
    
    # Create new contact
    db_contact = Contact(
        user_id=current_user.id,
        contact_id=contact_user.id,
        nickname=contact.nickname
    )
    db.add(db_contact)
    db.commit()
    db.refresh(db_contact)
    
    return ContactResponse(
        id=db_contact.id,
        user_id=db_contact.user_id,
        contact_id=db_contact.contact_id,
        contact_username=contact_user.username,
        contact_email=contact_user.email,
        nickname=db_contact.nickname,
        created_at=db_contact.created_at
    )

@app.get("/api/contacts", response_model=List[ContactResponse])
def get_contacts(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    contacts = db.query(Contact).filter(Contact.user_id == current_user.id).all()
    
    response = []
    for contact in contacts:
        contact_user = db.query(User).filter(User.id == contact.contact_id).first()
        if contact_user:
            response.append(ContactResponse(
                id=contact.id,
                user_id=contact.user_id,
                contact_id=contact.contact_id,
                contact_username=contact_user.username,
                contact_email=contact_user.email,
                nickname=contact.nickname,
                created_at=contact.created_at
            ))
    
    return response

@app.delete("/api/contacts/{contact_id}")
def remove_contact(contact_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    contact = db.query(Contact).filter(
        Contact.id == contact_id,
        Contact.user_id == current_user.id
    ).first()
    
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    
    db.delete(contact)
    db.commit()
    
    return {"message": "Contact removed successfully"}

# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...), db: Session = Depends(get_db)):
    try:
        # Verify token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("sub")
        if user_id is None:
            await websocket.close(code=4001, reason="Invalid token")
            return
            
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            await websocket.close(code=4001, reason="User not found")
            return
            
        # Connect
        await manager.connect(websocket, user_id)
        
        try:
            while True:
                # Receive message
                data = await websocket.receive_json()
                message_type = data.get("type")
                
                if message_type == "message":
                    # Handle new message
                    chat_id = data.get("chatId")
                    content = data.get("content")
                    
                    # Verify user is in chat
                    participant = db.query(ChatParticipant).filter(
                        ChatParticipant.chat_id == chat_id,
                        ChatParticipant.user_id == user_id
                    ).first()
                    
                    if not participant:
                        await websocket.send_json({
                            "type": "error",
                            "message": "You are not a participant in this chat"
                        })
                        continue
                    
                    # Create message in DB
                    db_message = Message(
                        chat_id=chat_id,
                        sender_id=user_id,
                        content=content
                    )
                    db.add(db_message)
                    db.commit()
                    db.refresh(db_message)
                    
                    # Send to all chat participants
                    await manager.send_to_chat(chat_id, {
                        "type": "message",
                        "chatId": chat_id,
                        "message": {
                            "id": db_message.id,
                            "sender_id": user_id,
                            "sender_username": user.username,
                            "content": content,
                            "created_at": db_message.created_at.isoformat()
                        }
                    }, db)
                    
                elif message_type == "typing":
                    # Handle typing indicator
                    chat_id = data.get("chatId")
                    is_typing = data.get("isTyping", False)
                    
                    # Send to other chat participants
                    await manager.send_to_chat(chat_id, {
                        "type": "typing",
                        "chatId": chat_id,
                        "userId": user_id,
                        "username": user.username,
                        "isTyping": is_typing
                    }, db, exclude_user_id=user_id)
                    
                elif message_type == "read":
                    # Handle read receipt
                    chat_id = data.get("chatId")
                    message_id = data.get("messageId")
                    
                    # You could update read status in DB here
                    # For now, just broadcast to chat participants
                    await manager.send_to_chat(chat_id, {
                        "type": "read",
                        "chatId": chat_id,
                        "messageId": message_id,
                        "userId": user_id
                    }, db, exclude_user_id=user_id)
                    
        except WebSocketDisconnect:
            manager.disconnect(websocket, user_id)
            
    except PyJWTError:
        await websocket.close(code=4001, reason="Invalid token")
    except Exception as e:
        print(f"WebSocket error: {e}")
        manager.disconnect(websocket, user_id)

@app.get("/api/users/search", response_model=List[UserSearchResponse])
def search_users(username: str, db: Session = Depends(get_db)):
    if len(username) < 2:
        raise HTTPException(status_code=400, detail="Search query must be at least 2 characters")
    
    users = db.query(User).filter(User.username.contains(username)).limit(10).all()
    
    return [
        UserSearchResponse(id=user.id, username=user.username)
        for user in users
    ]

# Private messaging route - create or get direct chat
@app.post("/api/chats/direct/{contact_id}", response_model=ChatResponse)
def create_or_get_direct_chat(contact_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Check if direct chat already exists
    existing_chat = db.query(Chat).join(
        ChatParticipant, Chat.id == ChatParticipant.chat_id
    ).filter(
        ChatParticipant.user_id.in_([current_user.id, contact_id])
    ).group_by(Chat.id).having(
        func.count(ChatParticipant.id) == 2
    ).first()
    
    if existing_chat:
        return ChatResponse(
            id=existing_chat.id,
            name=existing_chat.name,
            created_at=existing_chat.created_at
        )
    
    # Create new direct chat
    contact_user = db.query(User).filter(User.id == contact_id).first()
    
    if not contact_user:
        raise HTTPException(status_code=404, detail="Contact user not found")
    
    chat_name = f"Chat: {current_user.username} & {contact_user.username}"
    db_chat = Chat(name=chat_name)
    db.add(db_chat)
    db.commit()
    db.refresh(db_chat)
    
    # Add both participants
    for user_id in [current_user.id, contact_id]:
        participant = ChatParticipant(
            chat_id=db_chat.id,
            user_id=user_id
        )
        db.add(participant)
    db.commit()
    
    return ChatResponse(
        id=db_chat.id,
        name=db_chat.name,
        created_at=db_chat.created_at
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)