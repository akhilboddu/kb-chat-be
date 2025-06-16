#!/usr/bin/env python3
"""
Embeddings Migration Script

This script helps migrate existing knowledge bases from one embeddings provider to another.
It re-embeds all documents in the knowledge bases with the new provider.

Usage:
    python scripts/migrate_embeddings.py --from-provider cohere --to-provider huggingface
    python scripts/migrate_embeddings.py --to-provider cohere  # Migrate all to Cohere
    python scripts/migrate_embeddings.py --list-kbs  # List all knowledge bases
"""

import argparse
import asyncio
import logging
import os
import sys
from typing import List, Dict, Any
from dotenv import load_dotenv

# Add the app directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Load environment variables
load_dotenv()

# Import our modules
from app.core.supabase_client import supabase
from app.core.embeddings_flexible import FlexibleEmbeddings
from app.core.contextualizer import contextualizer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EmbeddingsMigrator:
    """Handles migration between different embeddings providers"""
    
    def __init__(self, from_provider: str = None, to_provider: str = "huggingface"):
        self.from_provider = from_provider
        self.to_provider = to_provider
        
        # Initialize the target embeddings provider
        try:
            self.target_embeddings = FlexibleEmbeddings.get_embeddings(provider=to_provider)
            logger.info(f"Initialized target embeddings: {self.target_embeddings.get_embedding_info()}")
        except Exception as e:
            logger.error(f"Failed to initialize {to_provider} embeddings: {e}")
            sys.exit(1)
    
    def list_knowledge_bases(self) -> List[Dict[str, Any]]:
        """List all knowledge bases in the system"""
        try:
            response = supabase.table("knowledge_bases").select("*").execute()
            return response.data
        except Exception as e:
            logger.error(f"Failed to list knowledge bases: {e}")
            return []
    
    def get_kb_documents(self, kb_id: str) -> List[Dict[str, Any]]:
        """Get all documents for a specific knowledge base"""
        try:
            response = supabase.table("knowledge_base_documents").select("*").eq("kb_id", kb_id).execute()
            return response.data
        except Exception as e:
            logger.error(f"Failed to get documents for KB {kb_id}: {e}")
            return []
    
    async def migrate_kb(self, kb_id: str, dry_run: bool = False) -> bool:
        """Migrate a single knowledge base to the new embeddings provider"""
        logger.info(f"{'[DRY RUN] ' if dry_run else ''}Starting migration of KB: {kb_id}")
        
        # Get all documents
        documents = self.get_kb_documents(kb_id)
        if not documents:
            logger.warning(f"No documents found for KB {kb_id}")
            return True
        
        logger.info(f"Found {len(documents)} documents to migrate")
        
        # Process documents in batches
        batch_size = 50  # Adjust based on memory constraints
        total_batches = (len(documents) + batch_size - 1) // batch_size
        
        for batch_idx, i in enumerate(range(0, len(documents), batch_size)):
            batch = documents[i:i + batch_size]
            logger.info(f"Processing batch {batch_idx + 1}/{total_batches} ({len(batch)} documents)")
            
            if not await self._process_batch(batch, dry_run):
                logger.error(f"Failed to process batch {batch_idx + 1}")
                return False
        
        logger.info(f"{'[DRY RUN] ' if dry_run else ''}Successfully migrated KB: {kb_id}")
        return True
    
    async def _process_batch(self, batch: List[Dict[str, Any]], dry_run: bool) -> bool:
        """Process a batch of documents"""
        try:
            # Extract content for embedding
            texts_to_embed = []
            for doc in batch:
                # Use contextualized text if available, otherwise use original content
                text = doc.get('ctx_text') or doc.get('content', '')
                texts_to_embed.append(text)
            
            if not texts_to_embed:
                logger.warning("No text content found in batch")
                return True
            
            # Generate new embeddings
            logger.debug(f"Generating embeddings for {len(texts_to_embed)} texts")
            new_embeddings = self.target_embeddings.embed_texts(texts_to_embed)
            
            if len(new_embeddings) != len(batch):
                logger.error(f"Embedding count mismatch: {len(new_embeddings)} != {len(batch)}")
                return False
            
            # Update documents in database
            if not dry_run:
                for doc, new_embedding in zip(batch, new_embeddings):
                    try:
                        supabase.table("knowledge_base_documents").update({
                            "embedding": new_embedding
                        }).eq("id", doc["id"]).execute()
                    except Exception as e:
                        logger.error(f"Failed to update document {doc['id']}: {e}")
                        return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing batch: {e}")
            return False
    
    async def migrate_all_kbs(self, dry_run: bool = False) -> None:
        """Migrate all knowledge bases"""
        kbs = self.list_knowledge_bases()
        if not kbs:
            logger.info("No knowledge bases found")
            return
        
        logger.info(f"{'[DRY RUN] ' if dry_run else ''}Migrating {len(kbs)} knowledge bases")
        
        successful = 0
        failed = 0
        
        for kb in kbs:
            kb_id = kb["kb_id"]
            kb_name = kb.get("name", "Unknown")
            
            logger.info(f"Processing KB: {kb_id} ({kb_name})")
            
            try:
                if await self.migrate_kb(kb_id, dry_run):
                    successful += 1
                else:
                    failed += 1
                    logger.error(f"Migration failed for KB: {kb_id}")
            except Exception as e:
                failed += 1
                logger.error(f"Unexpected error migrating KB {kb_id}: {e}")
        
        logger.info(f"Migration summary: {successful} successful, {failed} failed")
    
    def verify_migration(self, kb_id: str) -> bool:
        """Verify that migration completed successfully"""
        try:
            documents = self.get_kb_documents(kb_id)
            if not documents:
                return True  # No documents to verify
            
            # Check that all documents have embeddings
            for doc in documents:
                if not doc.get("embedding"):
                    logger.error(f"Document {doc['id']} missing embedding")
                    return False
                
                # Check embedding dimensions
                embedding = doc["embedding"]
                expected_dim = self.target_embeddings.get_embedding_info()["dimension"]
                if len(embedding) != expected_dim:
                    logger.error(
                        f"Document {doc['id']} has {len(embedding)} dimensions, "
                        f"expected {expected_dim}"
                    )
                    return False
            
            logger.info(f"Verification passed for KB: {kb_id}")
            return True
            
        except Exception as e:
            logger.error(f"Verification failed for KB {kb_id}: {e}")
            return False


def main():
    parser = argparse.ArgumentParser(description="Migrate embeddings between providers")
    parser.add_argument("--from-provider", help="Source provider (cohere, huggingface)")
    parser.add_argument("--to-provider", required=True, help="Target provider (cohere, huggingface)")
    parser.add_argument("--kb-id", help="Migrate specific knowledge base only")
    parser.add_argument("--list-kbs", action="store_true", help="List all knowledge bases")
    parser.add_argument("--dry-run", action="store_true", help="Simulate migration without making changes")
    parser.add_argument("--verify", help="Verify migration for specific KB")
    
    args = parser.parse_args()
    
    # Initialize migrator
    migrator = EmbeddingsMigrator(
        from_provider=args.from_provider,
        to_provider=args.to_provider
    )
    
    # Handle different operations
    if args.list_kbs:
        kbs = migrator.list_knowledge_bases()
        if kbs:
            print(f"\nFound {len(kbs)} knowledge bases:")
            for kb in kbs:
                doc_count = len(migrator.get_kb_documents(kb["kb_id"]))
                print(f"  - {kb['kb_id']}: {kb.get('name', 'Unknown')} ({doc_count} documents)")
        else:
            print("No knowledge bases found")
        return
    
    if args.verify:
        success = migrator.verify_migration(args.verify)
        if success:
            print(f"✅ Verification passed for KB: {args.verify}")
        else:
            print(f"❌ Verification failed for KB: {args.verify}")
            sys.exit(1)
        return
    
    # Run migration
    async def run_migration():
        if args.kb_id:
            # Migrate specific KB
            success = await migrator.migrate_kb(args.kb_id, args.dry_run)
            if success:
                print(f"✅ {'[DRY RUN] ' if args.dry_run else ''}Migration completed for KB: {args.kb_id}")
                if not args.dry_run:
                    print("Running verification...")
                    if migrator.verify_migration(args.kb_id):
                        print("✅ Verification passed")
                    else:
                        print("❌ Verification failed")
                        sys.exit(1)
            else:
                print(f"❌ Migration failed for KB: {args.kb_id}")
                sys.exit(1)
        else:
            # Migrate all KBs
            await migrator.migrate_all_kbs(args.dry_run)
    
    # Run the migration
    asyncio.run(run_migration())


if __name__ == "__main__":
    main()