import time
import uuid
import asyncio
from typing import Dict, Any, List, Optional
from chromadb.errors import NotFoundError

from app.core import db_manager, kb_manager, data_processor
from app.models.agent import (
    CreateAgentResponse,
    KBInfo,
    KBContentItem,
    KBContentResponse,
    CleanupResponse,
    StatusResponse,
    AgentConfigResponse,
)


class AgentService:
    @staticmethod
    def create_agent(agent_name: Optional[str] = None) -> CreateAgentResponse:
        """
        Creates a new empty agent instance (knowledge base collection),
        optionally assigning it a name, and returns its unique ID.
        """
        if agent_name:
            print(f"Creating a new empty agent with name: '{agent_name}'...")
        else:
            print("Creating a new unnamed empty agent...")

        try:
            # 1. Generate a unique KB ID
            timestamp = int(time.time())
            short_uuid = str(uuid.uuid4())[:8]
            kb_id = f"kb_{timestamp}_{short_uuid}"
            print(f"Generated KB ID: {kb_id}")

            # 2. Create the empty KB collection using kb_manager, passing the name
            print(f"Creating empty KB collection: {kb_id}...")
            _ = kb_manager.create_or_get_kb(kb_id, name=agent_name)
            print(f"Empty KB collection {kb_id} created successfully.")

            return CreateAgentResponse(
                kb_id=kb_id,
                name=agent_name,
                message="Agent created successfully with an empty knowledge base.",
            )

        except Exception as e:
            print(f"Error creating agent KB: {e}")
            raise e

    @staticmethod
    def populate_agent_from_json(
        kb_id: str, json_data: Dict[str, Any]
    ) -> StatusResponse:
        """
        Populates an existing agent's knowledge base using provided JSON data.
        """
        print(f"Populating KB {kb_id} from JSON...")
        try:
            # 1. Verify KB exists (create_or_get_kb will retrieve it)
            kb_collection = kb_manager.create_or_get_kb(kb_id)
            print(f"Verified KB collection exists: {kb_id}")

            # 2. Store the original JSON payload in SQLite
            print(f"Storing original JSON payload for KB {kb_id} in metadata DB...")
            store_success = db_manager.add_json_payload(kb_id, json_data)
            if not store_success:
                print(
                    f"Warning: Failed to store original JSON payload for KB {kb_id} in metadata DB. Proceeding with KB population."
                )

            # 3. Process JSON data for ChromaDB
            print("Extracting text from JSON data...")
            extracted_text = data_processor.extract_text_from_json(json_data)
            if not extracted_text or not extracted_text.strip():
                print(f"Warning: No text extracted from JSON data for KB {kb_id}.")
                return StatusResponse(
                    status="success",
                    message="KB exists, but no text content found in JSON to add.",
                )

            # 4. Add extracted text to the KB (ChromaDB)
            print(f"Adding extracted text to KB {kb_id}...")
            success = kb_manager.add_to_kb(kb_id, extracted_text)

            if success:
                print(f"Successfully populated KB {kb_id} from JSON.")
                return StatusResponse(
                    status="success",
                    message=f"Knowledge base {kb_id} populated successfully from JSON data.",
                )
            else:
                print(
                    f"Failed to add content from JSON to KB {kb_id} (add_to_kb returned False)."
                )
                raise Exception(
                    "Failed to add extracted JSON content to the knowledge base."
                )

        except Exception as e:
            print(f"Error populating KB {kb_id} from JSON: {e}")
            import traceback

            traceback.print_exc()
            raise e

    @staticmethod
    def delete_agent(kb_id: str) -> StatusResponse:
        """
        Deletes an agent instance, its associated knowledge base (ChromaDB),
        stored original JSON payloads (SQLite), and uploaded file records (SQLite).
        """
        print(f"Deleting agent KB and associated data: {kb_id}")

        # --- Delete File Records (SQLite) ---
        file_records_deleted = False
        try:
            file_records_deleted = db_manager.delete_uploaded_files(kb_id)
            if file_records_deleted:
                print(f"SQLite file record deletion process completed for KB {kb_id}.")
            else:
                print(f"SQLite file record deletion failed internally for KB {kb_id}.")
        except Exception as e:
            print(
                f"Unexpected error during SQLite file record deletion for KB {kb_id}: {e}"
            )

        # --- Delete JSON Payloads (SQLite) ---
        payload_delete_success = False
        try:
            payload_delete_success = db_manager.delete_json_payloads(kb_id)
            if payload_delete_success:
                print(f"SQLite JSON payload deletion process completed for KB {kb_id}.")
            else:
                print(f"SQLite JSON payload deletion failed internally for KB {kb_id}.")
        except Exception as e:
            print(
                f"Unexpected error during SQLite JSON payload deletion for KB {kb_id}: {e}"
            )

        # --- Delete Knowledge Base (ChromaDB) ---
        kb_delete_success = False
        try:
            kb_delete_success = kb_manager.delete_kb(kb_id)
            if kb_delete_success:
                print(f"ChromaDB deletion process completed for KB {kb_id}.")
            else:
                print(f"ChromaDB deletion process failed internally for KB {kb_id}.")
        except Exception as e:
            print(f"Unexpected error during ChromaDB deletion of KB {kb_id}: {e}")

        # Determine overall status
        all_deleted = (
            kb_delete_success and payload_delete_success and file_records_deleted
        )
        any_deleted = (
            kb_delete_success or payload_delete_success or file_records_deleted
        )

        if all_deleted:
            return StatusResponse(
                status="success",
                message=f"Agent {kb_id} and all associated data deleted successfully (or did not exist).",
            )
        elif any_deleted:
            # Construct a more informative warning message
            deleted_parts = []
            failed_parts = []
            if kb_delete_success:
                deleted_parts.append("KB")
            else:
                failed_parts.append("KB")
            if payload_delete_success:
                deleted_parts.append("JSON metadata")
            else:
                failed_parts.append("JSON metadata")
            if file_records_deleted:
                deleted_parts.append("File records")
            else:
                failed_parts.append("File records")

            message = f"Partial deletion for Agent {kb_id}. Successfully deleted: {', '.join(deleted_parts)}. Failed to delete: {', '.join(failed_parts)}."
            return StatusResponse(status="warning", message=message)
        else:  # Nothing was deleted successfully
            raise Exception(
                f"Failed to delete knowledge base {kb_id} and all associated metadata due to internal errors."
            )

    @staticmethod
    def get_agent_json_payloads(kb_id: str) -> List[Dict[str, Any]]:
        """
        Retrieves all original JSON payloads that were uploaded
        to populate this agent's knowledge base.
        """
        print(f"Getting stored JSON payloads for KB: {kb_id}")
        try:
            payloads = db_manager.get_json_payloads(kb_id)
            return payloads
        except Exception as e:
            print(f"Unexpected error retrieving JSON payloads for KB {kb_id}: {e}")
            import traceback

            traceback.print_exc()
            raise e

    @staticmethod
    def list_kbs() -> List[KBInfo]:
        """
        Lists all available Knowledge Bases with a brief summary.
        """
        print("Listing all KBs...")
        try:
            kb_info_list = kb_manager.list_kbs()
            # Map the list of dicts to a list of KBInfo models
            return [KBInfo(**info) for info in kb_info_list]
        except Exception as e:
            print(f"Error listing KBs: {e}")
            raise e

    @staticmethod
    def get_kb_content(
        kb_id: str, limit: Optional[int] = None, offset: Optional[int] = None
    ) -> KBContentResponse:
        """
        Retrieves the documents stored within a specific knowledge base, with pagination.
        """
        print(f"Getting content for KB: {kb_id}, Limit: {limit}, Offset: {offset}")
        try:
            result = kb_manager.get_kb_content(kb_id, limit=limit, offset=offset)

            # Combine IDs and documents into KBContentItem objects
            content_items = [
                KBContentItem(id=doc_id, document=doc)
                for doc_id, doc in zip(
                    result.get("ids", []), result.get("documents", [])
                )
            ]

            return KBContentResponse(
                kb_id=kb_id,
                total_count=result["total_count"],
                limit=result["limit"],
                offset=result["offset"],
                content=content_items,
            )

        except Exception as e:
            print(f"Error getting content for KB {kb_id}: {e}")
            import traceback

            traceback.print_exc()
            raise e

    @staticmethod
    async def cleanup_kb_duplicates(kb_id: str) -> CleanupResponse:
        """
        Removes duplicate documents (based on exact text content) from the specified knowledge base.
        """
        print(f"Cleaning up duplicates in KB: {kb_id}")
        try:
            # Run the potentially long-running cleanup task in a separate thread
            deleted_count = await asyncio.to_thread(
                kb_manager.cleanup_duplicates, kb_id
            )

            message = f"Successfully removed {deleted_count} duplicate documents from KB {kb_id}."
            if deleted_count == 0:
                message = f"No duplicate documents found in KB {kb_id}."

            return CleanupResponse(
                kb_id=kb_id, deleted_count=deleted_count, message=message
            )

        except NotFoundError:
            print(f"Cleanup failed: Knowledge base {kb_id} not found.")
            raise NotFoundError(f"Knowledge base {kb_id} not found.")
        except Exception as e:
            print(f"Error during duplicate cleanup for KB {kb_id}: {e}")
            import traceback

            traceback.print_exc()
            raise e

    @staticmethod
    def get_agent_config(kb_id: str) -> AgentConfigResponse:
        """Retrieves the current configuration for a specific agent."""
        print(f"Getting agent config for KB: {kb_id}")
        try:
            config_data = db_manager.get_agent_config(kb_id)
            # Pydantic will use defaults if a key is missing from config_data
            return AgentConfigResponse(**config_data)
        except Exception as e:
            print(f"Error getting agent config for {kb_id}: {e}")
            import traceback

            traceback.print_exc()
            raise e

    @staticmethod
    def update_agent_config(kb_id: str, update_data: Dict[str, Any]) -> StatusResponse:
        """Updates the configuration for a specific agent."""
        print(f"Updating agent config for KB: {kb_id}")

        if not update_data:
            # No fields were provided in the request body
            raise ValueError("No configuration parameters provided for update.")

        try:
            success = db_manager.upsert_agent_config(kb_id, update_data)
            if success:
                return StatusResponse(
                    status="success",
                    message="Agent configuration updated successfully.",
                )
            else:
                # Check logs for specific upsert error
                raise Exception(
                    "Failed to update agent configuration due to an internal database error."
                )
        except Exception as e:
            print(f"Error updating agent config for {kb_id}: {e}")
            import traceback

            traceback.print_exc()
            raise e

