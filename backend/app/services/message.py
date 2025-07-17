"""Message service."""
import asyncio
import json
from typing import Optional, List
from datetime import datetime
from sqlalchemy import select, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload

from app.models.message import Message, MessageStatus, MessageVersion, MessageReaction
from app.models.user import User
from app.models.file import File
from app.core.redis import redis_client
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

class MessageService:
    """Message service for business logic."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_message(
        self,
        chat_id: int,
        sender_id: int,
        content: str,
        message_type: str = "text",
        reply_to_id: Optional[int] = None,
        file_id: Optional[int] = None
    ) -> Message:
        """Create a new message."""
        # Create message
        message = Message(
            conversation_id=chat_id,
            sender_id=sender_id,
            content=content,
            message_type=message_type,
            reply_to_id=reply_to_id
        )
        self.db.add(message)
        await self.db.flush()
        
        # Update file if provided
        if file_id:
            result = await self.db.execute(
                select(File).where(File.id == file_id)
            )
            file = result.scalar_one_or_none()
            if file:
                file.message_id = message.id
        
        # Create initial status (sent)
        status = MessageStatus(
            message_id=message.id,
            user_id=sender_id,
            status="sent"
        )
        self.db.add(status)
        
        await self.db.commit()
        await self.db.refresh(message)
        
        # Cache in Redis
        await self._cache_message(message)
        
        return message
    
    async def get_message(self, message_id: int) -> Optional[Message]:
        """Get message by ID."""
        result = await self.db.execute(
            select(Message)
            .options(
                joinedload(Message.sender),
                selectinload(Message.statuses),
                selectinload(Message.reactions),
                selectinload(Message.files),
                joinedload(Message.reply_to)
            )
            .where(Message.id == message_id)
        )
        return result.scalar_one_or_none()
    
    async def get_chat_messages(
        self,
        chat_id: int,
        user_id: int,
        limit: int = 50,
        before_id: Optional[int] = None
    ) -> List[Message]:
        """Get messages for a chat."""
        query = select(Message).options(
            joinedload(Message.sender),
            selectinload(Message.statuses),
            selectinload(Message.reactions),
            selectinload(Message.files),
            joinedload(Message.reply_to)
        ).where(
            and_(
                Message.conversation_id == chat_id,
                or_(
                    Message.deleted_at.is_(None),
                    Message.sender_id == user_id  # Show own deleted messages
                )
            )
        )
        
        if before_id:
            query = query.where(Message.id < before_id)
        
        query = query.order_by(desc(Message.created_at)).limit(limit)
        
        result = await self.db.execute(query)
        messages = result.scalars().unique().all()
        
        # Process messages
        processed_messages = []
        for msg in reversed(messages):  # Return in chronological order
            # Add sender info
            msg.sender_username = msg.sender.username
            msg.sender_avatar_url = msg.sender.avatar_url
            
            # Add file URLs
            if msg.files:
                file = msg.files[0]
                msg.file_url = f"/api/v1/files/{file.id}"
                if file.thumbnail_path:
                    msg.thumbnail_url = f"/api/v1/files/{file.id}/thumbnail"
            
            processed_messages.append(msg)
        
        return processed_messages
    
    async def update_message(
        self,
        message_id: int,
        user_id: int,
        content: str
    ) -> Optional[Message]:
        """Update message content."""
        message = await self.get_message(message_id)
        
        if not message or message.sender_id != user_id:
            return None
        
        # Save old version
        version = MessageVersion(
            message_id=message.id,
            version=message.version,
            content=message.content
        )
        self.db.add(version)
        
        # Update message
        message.content = content
        message.edited_at = datetime.utcnow()
        message.updated_at = datetime.utcnow()
        message.version += 1
        
        await self.db.commit()
        await self.db.refresh(message)
        
        # Update cache
        await self._cache_message(message)
        
        return message
    
    async def delete_message(
        self,
        message_id: int,
        user_id: int
    ) -> bool:
        """Soft delete a message."""
        result = await self.db.execute(
            select(Message).where(
                and_(
                    Message.id == message_id,
                    Message.sender_id == user_id
                )
            )
        )
        message = result.scalar_one_or_none()
        
        if not message:
            return False
        
        message.deleted_at = datetime.utcnow()
        await self.db.commit()
        
        # Update cache
        await self._remove_from_cache(message)
        
        return True
    
    async def mark_as_delivered(
        self,
        message_id: int,
        user_id: int
    ) -> bool:
        """Mark message as delivered."""
        # Check if status already exists
        result = await self.db.execute(
            select(MessageStatus).where(
                and_(
                    MessageStatus.message_id == message_id,
                    MessageStatus.user_id == user_id
                )
            )
        )
        status = result.scalar_one_or_none()
        
        if status:
            if status.status == "sent":
                status.status = "delivered"
                status.created_at = datetime.utcnow()
                await self.db.commit()
        else:
            # Create new status
            status = MessageStatus(
                message_id=message_id,
                user_id=user_id,
                status="delivered"
            )
            self.db.add(status)
            await self.db.commit()
        
        return True
    
    async def mark_as_read(
        self,
        message_id: int,
        user_id: int
    ) -> bool:
        """Mark message as read."""
        # Get message to check if user should mark it
        result = await self.db.execute(
            select(Message).where(Message.id == message_id)
        )
        message = result.scalar_one_or_none()
        
        if not message or message.sender_id == user_id:
            return False
        
        # Update or create status
        result = await self.db.execute(
            select(MessageStatus).where(
                and_(
                    MessageStatus.message_id == message_id,
                    MessageStatus.user_id == user_id
                )
            )
        )
        status = result.scalar_one_or_none()
        
        if status:
            status.status = "read"
            status.created_at = datetime.utcnow()
        else:
            status = MessageStatus(
                message_id=message_id,
                user_id=user_id,
                status="read"
            )
            self.db.add(status)
        
        await self.db.commit()
        return True
    
    async def add_reaction(
        self,
        message_id: int,
        user_id: int,
        emoji: str
    ) -> Optional[Message]:
        """Add reaction to message."""
        # Check if reaction already exists
        result = await self.db.execute(
            select(MessageReaction).where(
                and_(
                    MessageReaction.message_id == message_id,
                    MessageReaction.user_id == user_id,
                    MessageReaction.emoji == emoji
                )
            )
        )
        
        if result.scalar_one_or_none():
            # Reaction already exists
            return await self.get_message(message_id)
        
        # Add reaction
        reaction = MessageReaction(
            message_id=message_id,
            user_id=user_id,
            emoji=emoji
        )
        self.db.add(reaction)
        await self.db.commit()
        
        return await self.get_message(message_id)
    
    async def remove_reaction(
        self,
        message_id: int,
        user_id: int,
        emoji: str
    ) -> bool:
        """Remove reaction from message."""
        result = await self.db.execute(
            select(MessageReaction).where(
                and_(
                    MessageReaction.message_id == message_id,
                    MessageReaction.user_id == user_id,
                    MessageReaction.emoji == emoji
                )
            )
        )
        reaction = result.scalar_one_or_none()
        
        if not reaction:
            return False
        
        await self.db.delete(reaction)
        await self.db.commit()
        
        return True
    
    async def _cache_message(self, message: Message):
        """Cache message in Redis."""
        message_data = {
            "id": message.id,
            "conversation_id": message.conversation_id,
            "sender_id": message.sender_id,
            "content": message.content,
            "created_at": message.created_at.isoformat(),
            "edited_at": message.edited_at.isoformat() if message.edited_at else None,
            "deleted_at": message.deleted_at.isoformat() if message.deleted_at else None
        }
        
        # Add to chat messages cache
        key = f"chat_messages:{message.conversation_id}"
        await redis_client.client.rpush(key, json.dumps(message_data))
        await redis_client.client.ltrim(key, -50, -1)  # Keep last 50
        await redis_client.client.expire(key, 3600)
    
    async def _remove_from_cache(self, message: Message):
        """Remove message from cache."""
        # Update message in cache to show as deleted
        await self._cache_message(message)