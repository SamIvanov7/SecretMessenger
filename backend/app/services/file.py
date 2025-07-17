"""File service."""
import os
import uuid
import aiofiles
import io
from typing import Optional
from datetime import datetime
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from PIL import Image

from app.models.file import File
from app.config import settings
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

class FileService:
    """File service for handling uploads."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def save_file(
        self,
        file: UploadFile,
        user_id: int,
        message_id: Optional[int] = None
    ) -> File:
        """Save uploaded file."""
        # Generate unique filename
        file_ext = os.path.splitext(file.filename)[1]
        unique_filename = f"{uuid.uuid4()}{file_ext}"
        
        # Create file path
        file_path = os.path.join(str(user_id), unique_filename)
        full_path = os.path.join(settings.UPLOAD_DIR, file_path)
        
        # Create directory if not exists
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        
        # Save file
        file_content = await file.read()
        async with aiofiles.open(full_path, "wb") as f:
            await f.write(file_content)
        
        # Reset file position
        await file.seek(0)
        
        # Create database record
        file_record = File(
            message_id=message_id,
            filename=unique_filename,
            original_filename=file.filename,
            file_path=file_path,
            file_size=len(file_content),
            mime_type=file.content_type
        )
        
        # Process image/video metadata
        if file.content_type.startswith("image/"):
            await self._process_image(file_record, file_content, full_path)
        
        self.db.add(file_record)
        await self.db.commit()
        await self.db.refresh(file_record)
        
        logger.info(f"File saved: {file_record.original_filename} ({file_record.file_size} bytes)")
        
        return file_record
    
    async def get_file(self, file_id: int) -> Optional[File]:
        """Get file by ID."""
        result = await self.db.execute(
            select(File).where(File.id == file_id)
        )
        return result.scalar_one_or_none()
    
    async def delete_file(self, file_id: int) -> bool:
        """Delete file."""
        file_record = await self.get_file(file_id)
        if not file_record:
            return False
        
        # Delete physical file
        full_path = os.path.join(settings.UPLOAD_DIR, file_record.file_path)
        if os.path.exists(full_path):
            os.remove(full_path)
        
        # Delete thumbnail if exists
        if file_record.thumbnail_path:
            thumb_path = os.path.join(settings.UPLOAD_DIR, file_record.thumbnail_path)
            if os.path.exists(thumb_path):
                os.remove(thumb_path)
        
        # Delete database record
        await self.db.delete(file_record)
        await self.db.commit()
        
        logger.info(f"File deleted: {file_record.original_filename}")
        
        return True
    
    async def _process_image(self, file_record: File, content: bytes, full_path: str):
        """Process image file - extract metadata and create thumbnail."""
        try:
            # Open image
            image = Image.open(io.BytesIO(content))
            
            # Get dimensions
            file_record.width = image.width
            file_record.height = image.height
            
            # Create thumbnail
            thumbnail = image.copy()
            thumbnail.thumbnail((200, 200), Image.Resampling.LANCZOS)
            
            # Save thumbnail
            thumb_filename = f"thumb_{file_record.filename}"
            thumb_path = os.path.join(
                os.path.dirname(file_record.file_path),
                thumb_filename
            )
            thumb_full_path = os.path.join(settings.UPLOAD_DIR, thumb_path)
            
            # Convert to RGB if necessary
            if thumbnail.mode in ("RGBA", "LA", "P"):
                rgb_thumbnail = Image.new("RGB", thumbnail.size, (255, 255, 255))
                rgb_thumbnail.paste(thumbnail, mask=thumbnail.split()[-1] if thumbnail.mode == "RGBA" else None)
                thumbnail = rgb_thumbnail
            
            thumbnail.save(thumb_full_path, "JPEG", quality=85)
            file_record.thumbnail_path = thumb_path
            
        except Exception as e:
            logger.error(f"Error processing image: {e}")