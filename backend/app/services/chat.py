"""Chat service."""
from typing import Optional, List
from datetime import datetime
from sqlalchemy import select, and_, or_, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload

from app.models.chat import Conversation, ConversationParticipant
from app.models.message import Message, MessageStatus
from app.models.user import User
from app.core.redis import redis_client
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

class ChatService:
    """Chat service for business logic."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_conversation(
        self,
        creator_id: int,
        user_ids: List[int],
        type: str = "direct",
        name: Optional[str] = None,
        description: Optional[str] = None
    ) -> Conversation:
        """Create a new conversation."""
        # Create conversation
        conversation = Conversation(
            type=type,
            name=name,
            description=description
        )
        self.db.add(conversation)
        await self.db.flush()
        
        # Add participants
        for user_id in user_ids:
            participant = ConversationParticipant(
                conversation_id=conversation.id,
                user_id=user_id
            )
            self.db.add(participant)
        
        await self.db.commit()
        
        # Load with relationships
        result = await self.db.execute(
            select(Conversation)
            .options(
                selectinload(Conversation.participants)
                .selectinload(ConversationParticipant.user)
            )
            .where(Conversation.id == conversation.id)
        )
        conversation = result.scalar_one()
        
        return conversation
    
    async def get_conversation(self, conversation_id: int) -> Optional[Conversation]:
        """Get conversation by ID."""
        result = await self.db.execute(
            select(Conversation)
            .options(
                selectinload(Conversation.participants)
                .selectinload(ConversationParticipant.user)
            )
            .where(Conversation.id == conversation_id)
        )
        return result.scalar_one_or_none()
    
    async def get_direct_conversation(
        self,
        user1_id: int,
        user2_id: int
    ) -> Optional[Conversation]:
        """Get direct conversation between two users."""
        # Find conversations where both users are participants
        subquery = (
            select(ConversationParticipant.conversation_id)
            .where(ConversationParticipant.user_id.in_([user1_id, user2_id]))
            .group_by(ConversationParticipant.conversation_id)
            .having(func.count(ConversationParticipant.user_id) == 2)
        )
        
        result = await self.db.execute(
            select(Conversation)
            .options(
                selectinload(Conversation.participants)
                .selectinload(ConversationParticipant.user)
            )
            .where(
                and_(
                    Conversation.id.in_(subquery),
                    Conversation.type == "direct"
                )
            )
        )
        
        conversations = result.scalars().all()
        
        # Verify it has exactly these two users
        for conv in conversations:
            participant_ids = {p.user_id for p in conv.participants}
            if participant_ids == {user1_id, user2_id}:
                return conv
        
        return None
    
    async def get_user_conversations(
        self,
        user_id: int,
        limit: int = 20,
        offset: int = 0
    ) -> List[Conversation]:
        """Get user's conversations."""
        # Subquery for conversations with last message time
        last_message_subquery = (
            select(
                Message.conversation_id,
                func.max(Message.created_at).label('last_message_time')
            )
            .where(Message.deleted_at.is_(None))
            .group_by(Message.conversation_id)
            .subquery()
        )
        
        # Get conversations
        result = await self.db.execute(
            select(Conversation)
            .join(ConversationParticipant)
            .outerjoin(
                last_message_subquery,
                Conversation.id == last_message_subquery.c.conversation_id
            )
            .options(
                selectinload(Conversation.participants)
                .selectinload(ConversationParticipant.user)
            )
            .where(ConversationParticipant.user_id == user_id)
            .order_by(
                desc(func.coalesce(
                    last_message_subquery.c.last_message_time,
                    Conversation.created_at
                ))
            )
            .limit(limit)
            .offset(offset)
        )
        
        return result.scalars().unique().all()
    
    async def count_user_conversations(self, user_id: int) -> int:
        """Count user's conversations."""
        result = await self.db.execute(
            select(func.count(Conversation.id))
            .join(ConversationParticipant)
            .where(ConversationParticipant.user_id == user_id)
        )
        return result.scalar()
    
    async def get_last_message(self, conversation_id: int) -> Optional[Message]:
        """Get last message in conversation."""
        result = await self.db.execute(
            select(Message)
            .options(
                joinedload(Message.sender),
                selectinload(Message.files),
                selectinload(Message.reactions)
            )
            .where(
                and_(
                    Message.conversation_id == conversation_id,
                    Message.deleted_at.is_(None)
                )
            )
            .order_by(desc(Message.created_at))
            .limit(1)
        )
        
        message = result.scalar_one_or_none()
        if message:
            # Add sender info
            message.sender_username = message.sender.username
            message.sender_avatar_url = message.sender.avatar_url
        
        return message
    
    async def get_unread_count(self, conversation_id: int, user_id: int) -> int:
        """Get unread message count for user in conversation."""
        result = await self.db.execute(
            select(func.count(Message.id))
            .outerjoin(
                MessageStatus,
                and_(
                    MessageStatus.message_id == Message.id,
                    MessageStatus.user_id == user_id
                )
            )
            .where(
                and_(
                    Message.conversation_id == conversation_id,
                    Message.sender_id != user_id,
                    Message.deleted_at.is_(None),
                    or_(
                        MessageStatus.status.is_(None),
                        MessageStatus.status != "read"
                    )
                )
            )
        )
        return result.scalar()
    
    async def is_participant(self, conversation_id: int, user_id: int) -> bool:
        """Check if user is participant in conversation."""
        result = await self.db.execute(
            select(ConversationParticipant)
            .where(
                and_(
                    ConversationParticipant.conversation_id == conversation_id,
                    ConversationParticipant.user_id == user_id
                )
            )
        )
        return result.scalar_one_or_none() is not None
    
    async def get_participant_ids(self, conversation_id: int) -> List[int]:
        """Get all participant IDs for a conversation."""
        result = await self.db.execute(
            select(ConversationParticipant.user_id)
            .where(ConversationParticipant.conversation_id == conversation_id)
        )
        return [row[0] for row in result]
    
    async def add_participant(
        self,
        conversation_id: int,
        user_id: int
    ) -> bool:
        """Add participant to conversation."""
        # Check if already participant
        if await self.is_participant(conversation_id, user_id):
            return False
        
        participant = ConversationParticipant(
            conversation_id=conversation_id,
            user_id=user_id
        )
        self.db.add(participant)
        await self.db.commit()
        
        return True
    
    async def remove_participant(
        self,
        conversation_id: int,
        user_id: int
    ) -> bool:
        """Remove participant from conversation."""
        result = await self.db.execute(
            select(ConversationParticipant)
            .where(
                and_(
                    ConversationParticipant.conversation_id == conversation_id,
                    ConversationParticipant.user_id == user_id
                )
            )
        )
        participant = result.scalar_one_or_none()
        
        if not participant:
            return False
        
        await self.db.delete(participant)
        await self.db.commit()
        
        return True
    
    async def mute_conversation(
        self,
        conversation_id: int,
        user_id: int,
        muted_until: Optional[datetime] = None
    ) -> bool:
        """Mute conversation for user."""
        result = await self.db.execute(
            select(ConversationParticipant)
            .where(
                and_(
                    ConversationParticipant.conversation_id == conversation_id,
                    ConversationParticipant.user_id == user_id
                )
            )
        )
        participant = result.scalar_one_or_none()
        
        if not participant:
            return False
        
        participant.is_muted = True
        participant.muted_until = muted_until
        await self.db.commit()
        
        return True
    
    async def unmute_conversation(
        self,
        conversation_id: int,
        user_id: int
    ) -> bool:
        """Unmute conversation for user."""
        result = await self.db.execute(
            select(ConversationParticipant)
            .where(
                and_(
                    ConversationParticipant.conversation_id == conversation_id,
                    ConversationParticipant.user_id == user_id
                )
            )
        )
        participant = result.scalar_one_or_none()
        
        if not participant:
            return False
        
        participant.is_muted = False
        participant.muted_until = None
        await self.db.commit()
        
        return True