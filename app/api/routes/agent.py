from fastapi import APIRouter, Body, HTTPException, Query, status
from typing import Dict, Any, List, Optional
from chromadb.errors import NotFoundError

from app.services.agent_service import AgentService
from app.models.agent import (
    CreateNamedAgentRequest,
    CreateAgentResponse,
    PopulateAgentJSONRequest,
    StatusResponse,
    ListKBsResponse,
    KBContentResponse,
    CleanupResponse,
    AgentConfigResponse,
    UpdateAgentConfigRequest,
)

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post(
    "", response_model=CreateAgentResponse, status_code=status.HTTP_201_CREATED
)
async def create_agent(request: CreateNamedAgentRequest = Body(None)):
    """
    Creates a new empty agent instance (knowledge base collection),
    optionally assigning it a name, and returns its unique ID.
    If no request body is provided or name is null, creates an unnamed agent.
    """
    agent_name = request.name if request else None

    try:
        return AgentService.create_agent(agent_name)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create agent knowledge base: {str(e)}",
        )


@router.post(
    "/{kb_id}/json", response_model=StatusResponse, status_code=status.HTTP_200_OK
)
async def populate_agent_from_json(kb_id: str, request: PopulateAgentJSONRequest):
    """
    Populates an existing agent's knowledge base using provided JSON data.
    """
    try:
        return AgentService.populate_agent_from_json(kb_id, request.json_data)
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Knowledge base {kb_id} not found or inaccessible.",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to populate knowledge base from JSON: {str(e)}",
        )


@router.delete(
    "/{kb_id}", response_model=StatusResponse, status_code=status.HTTP_200_OK
)
async def delete_agent(kb_id: str):
    """
    Deletes an agent instance, its associated knowledge base (ChromaDB),
    stored original JSON payloads (SQLite), and uploaded file records (SQLite).
    """
    try:
        return AgentService.delete_agent(kb_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete knowledge base {kb_id} and associated metadata: {str(e)}",
        )


@router.get("/{kb_id}/json", response_model=List[Dict[str, Any]])
async def get_agent_json_payloads(kb_id: str):
    """
    Retrieves all original JSON payloads that were uploaded
    to populate this agent's knowledge base.
    Returns an empty list if no JSON payloads are found or if the KB ID doesn't exist.
    """
    try:
        return AgentService.get_agent_json_payloads(kb_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve JSON payloads for knowledge base {kb_id}: {str(e)}",
        )


@router.get("", response_model=ListKBsResponse)
async def list_kbs_endpoint():
    """
    Lists all available Knowledge Bases with a brief summary derived from their content.
    """
    try:
        kbs = AgentService.list_kbs()
        return ListKBsResponse(kbs=kbs)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list knowledge bases: {str(e)}",
        )


@router.get("/{kb_id}/content", response_model=KBContentResponse)
async def get_kb_content_endpoint(
    kb_id: str,
    limit: Optional[int] = Query(
        None, ge=1, description="Maximum number of documents to return"
    ),
    offset: Optional[int] = Query(
        None, ge=0, description="Number of documents to skip"
    ),
):
    """
    Retrieves the documents stored within a specific knowledge base, with pagination.
    """
    try:
        return AgentService.get_kb_content(kb_id, limit=limit, offset=offset)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve content for knowledge base {kb_id}: {str(e)}",
        )


@router.post(
    "/{kb_id}/cleanup", response_model=CleanupResponse, status_code=status.HTTP_200_OK
)
async def cleanup_kb_duplicates_endpoint(kb_id: str):
    """
    Removes duplicate documents (based on exact text content) from the specified knowledge base.
    """
    try:
        return await AgentService.cleanup_kb_duplicates(kb_id)
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Knowledge base {kb_id} not found.",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cleanup duplicates in knowledge base {kb_id}: {str(e)}",
        )


@router.get("/{kb_id}/config", response_model=AgentConfigResponse)
async def get_agent_config_endpoint(kb_id: str):
    """Retrieves the current configuration for a specific agent."""
    try:
        return AgentService.get_agent_config(kb_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve agent configuration: {str(e)}",
        )


@router.put("/{kb_id}/config", response_model=StatusResponse)
async def update_agent_config_endpoint(kb_id: str, request: UpdateAgentConfigRequest):
    """Updates the configuration for a specific agent."""
    # Convert Pydantic model to dict, excluding unset fields
    update_data = request.model_dump(exclude_unset=True)

    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No configuration parameters provided for update.",
        )

    try:
        return AgentService.update_agent_config(kb_id, update_data)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update agent configuration: {str(e)}",
        )
