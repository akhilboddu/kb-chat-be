"""
Learning Database Manager
Manages AI-generated learnings from conversations in Supabase database
"""

import json
from typing import List, Optional, Dict, Any, Tuple
from uuid import UUID, uuid4
from datetime import datetime

from app.core.supabase_client import supabase
from app.models.learning import Learning, CreateLearningRequest


class LearningManager:
    """
    Manages AI-generated learnings in Supabase database.
    Handles CRUD operations for learnings generated from conversations.
    """
    
    def __init__(self):
        self.supabase = supabase
        print("Initialized Learning Manager")
    
    def save_learning(self, learning_data: Dict[str, Any]) -> Optional[Learning]:
        """
        Saves a new learning to the database.
        
        Args:
            learning_data: Dictionary containing learning information
            
        Returns:
            Learning object if successful, None if failed
        """
        try:
            # Prepare data for database insertion
            db_data = {
                'bot_id': str(learning_data['bot_id']),
                'title': learning_data['title'],
                'content': learning_data['content'],
                'source': learning_data.get('source'),
                'confidence_score': learning_data.get('confidence_score'),
                'conversation_id': learning_data.get('conversation_id'),
                'gap_summary': learning_data.get('gap_summary'),
                'metadata': json.dumps(learning_data.get('metadata', {})),
                'status': 'pending'  # Default status
            }
            
            # Insert into database
            result = self.supabase.table('learnings').insert(db_data).execute()
            
            if result.data:
                learning_record = result.data[0]
                print(f"Saved learning: {learning_record['title']} for bot {learning_record['bot_id']}")
                
                # Convert back to Learning model
                return Learning(
                    id=learning_record['id'],
                    bot_id=learning_record['bot_id'],
                    title=learning_record['title'],
                    content=learning_record['content'],
                    source=learning_record.get('source'),
                    confidence_score=learning_record.get('confidence_score'),
                    status=learning_record['status'],
                    conversation_id=learning_record.get('conversation_id'),
                    gap_summary=learning_record.get('gap_summary'),
                    metadata=json.loads(learning_record.get('metadata', '{}')),
                    created_at=learning_record.get('created_at'),
                    updated_at=learning_record.get('updated_at')
                )
            
            return None
            
        except Exception as e:
            print(f"Error saving learning: {e}")
            return None
    
    def list_learnings(self, bot_id: str, status: Optional[str] = None, 
                      page: int = 1, page_size: int = 50) -> Tuple[List[Learning], Dict[str, int]]:
        """
        Lists learnings for a bot with optional filtering and pagination.
        
        Args:
            bot_id: Bot ID to filter learnings
            status: Optional status filter ('pending', 'approved', 'rejected')
            page: Page number (1-based)
            page_size: Number of items per page
            
        Returns:
            Tuple of (learnings list, stats dict)
        """
        try:
            # Build query
            query = self.supabase.table('learnings').select('*').eq('bot_id', bot_id)
            
            if status:
                query = query.eq('status', status)
            
            # Get total count and status counts
            all_result = self.supabase.table('learnings').select('id, status').eq('bot_id', bot_id).execute()
            total_count = len(all_result.data)
            
            # Count by status
            pending_count = len([r for r in all_result.data if r['status'] == 'pending'])
            approved_count = len([r for r in all_result.data if r['status'] == 'approved'])
            rejected_count = len([r for r in all_result.data if r['status'] == 'rejected'])
            
            # Get paginated results
            offset = (page - 1) * page_size
            result = query.order('created_at', desc=True).range(offset, offset + page_size - 1).execute()
            
            learnings = []
            for record in result.data:
                learnings.append(Learning(
                    id=record['id'],
                    bot_id=record['bot_id'],
                    title=record['title'],
                    content=record['content'],
                    source=record.get('source'),
                    confidence_score=record.get('confidence_score'),
                    status=record['status'],
                    conversation_id=record.get('conversation_id'),
                    gap_summary=record.get('gap_summary'),
                    metadata=json.loads(record.get('metadata', '{}')),
                    created_at=record.get('created_at'),
                    updated_at=record.get('updated_at')
                ))
            
            stats = {
                'total_count': total_count,
                'pending_count': pending_count,
                'approved_count': approved_count,
                'rejected_count': rejected_count
            }
            
            return learnings, stats
            
        except Exception as e:
            print(f"Error listing learnings for bot {bot_id}: {e}")
            return [], {
                'total_count': 0,
                'pending_count': 0,
                'approved_count': 0,
                'rejected_count': 0
            }
    
    def update_learning_status(self, learning_id: str, status: str) -> bool:
        """
        Updates the status of a learning.
        
        Args:
            learning_id: ID of the learning to update
            status: New status ('pending', 'approved', 'rejected')
            
        Returns:
            Success status
        """
        try:
            result = self.supabase.table('learnings').update({
                'status': status,
                'updated_at': datetime.utcnow().isoformat()
            }).eq('id', learning_id).execute()
            
            if result.data:
                print(f"Updated learning {learning_id} status to {status}")
                return True
            
            return False
            
        except Exception as e:
            print(f"Error updating learning {learning_id} status: {e}")
            return False
    
    def bulk_update_status(self, learning_ids: List[str], status: str) -> int:
        """
        Updates the status of multiple learnings.
        
        Args:
            learning_ids: List of learning IDs to update
            status: New status ('pending', 'approved', 'rejected')
            
        Returns:
            Number of successfully updated learnings
        """
        try:
            updated_count = 0
            for learning_id in learning_ids:
                if self.update_learning_status(learning_id, status):
                    updated_count += 1
            
            print(f"Bulk updated {updated_count}/{len(learning_ids)} learnings to status {status}")
            return updated_count
            
        except Exception as e:
            print(f"Error in bulk update: {e}")
            return 0
    
    def delete_learning(self, learning_id: str) -> bool:
        """
        Deletes a learning from the database.
        
        Args:
            learning_id: ID of the learning to delete
            
        Returns:
            Success status
        """
        try:
            result = self.supabase.table('learnings').delete().eq('id', learning_id).execute()
            
            if result.data:
                print(f"Deleted learning {learning_id}")
                return True
            
            return False
            
        except Exception as e:
            print(f"Error deleting learning {learning_id}: {e}")
            return False
    
    def get_learning_by_id(self, learning_id: str) -> Optional[Learning]:
        """
        Gets a specific learning by ID.
        
        Args:
            learning_id: ID of the learning to retrieve
            
        Returns:
            Learning object if found, None otherwise
        """
        try:
            result = self.supabase.table('learnings').select('*').eq('id', learning_id).single().execute()
            
            if result.data:
                record = result.data
                return Learning(
                    id=record['id'],
                    bot_id=record['bot_id'],
                    title=record['title'],
                    content=record['content'],
                    source=record.get('source'),
                    confidence_score=record.get('confidence_score'),
                    status=record['status'],
                    conversation_id=record.get('conversation_id'),
                    gap_summary=record.get('gap_summary'),
                    metadata=json.loads(record.get('metadata', '{}')),
                    created_at=record.get('created_at'),
                    updated_at=record.get('updated_at')
                )
            
            return None
            
        except Exception as e:
            print(f"Error getting learning {learning_id}: {e}")
            return None


# Global instance
learning_manager = LearningManager() 