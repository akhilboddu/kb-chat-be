"""
KB Manager Factory - Thin re-export module for backward compatibility
This allows existing imports to work without modification
"""

from app.core.supabase_kb_manager import kb_manager

# Re-export the singleton instance
__all__ = ['kb_manager'] 