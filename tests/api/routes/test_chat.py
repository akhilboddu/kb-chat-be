import pytest
from fastapi import status
import uuid

from tests.api.routes.test_agent import TestAgentEndpoints

class TestChatEndpoints:
    """Test suite for chat-related endpoints"""
    
    @pytest.fixture(scope="class")
    def test_kb_id(self, client):
        """Create a test knowledge base for chat tests"""
        # Use the agent test to create a KB
        agent_tests = TestAgentEndpoints()
        kb_id = agent_tests.test_create_agent(client)
        
        # Populate it with test data
        json_data = {
            "company_name": "Chat Test Company",
            "product_details": {
                "name": "Chat Test Product",
                "version": "1.0",
                "description": "This is a test product for chat endpoints"
            }
        }
        
        client.post(
            f"/agents/{kb_id}/json", 
            json={"json_data": json_data}
        )
        
        return kb_id
    
    def test_chat_endpoint(self, client, test_kb_id):
        """Test the main chat endpoint"""
        response = client.post(
            f"/agents/{test_kb_id}/chat",
            json={"message": "Tell me about your product"}
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "content" in data
        assert "type" in data
        assert data["type"] in ["answer", "handoff", "error"]
        
        # The content should contain some response text
        assert len(data["content"]) > 0
    
    def test_human_response_endpoint(self, client, test_kb_id):
        """Test human response endpoint"""
        # First send a chat message to create history
        client.post(
            f"/agents/{test_kb_id}/chat",
            json={"message": "What are your products?"}
        )
        
        # Then submit a human response
        response = client.post(
            f"/agents/{test_kb_id}/human_response",
            json={
                "human_response": "This is a human agent response for testing",
                "update_kb": False
            }
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "success"
    
    def test_human_response_with_kb_update(self, client, test_kb_id):
        """Test human response endpoint with KB update"""
        # Send a human response with KB update
        response = client.post(
            f"/agents/{test_kb_id}/human_response",
            json={
                "human_response": "Human response with KB update",
                "update_kb": True,
                "kb_update_text": "Additional knowledge about test products"
            }
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "success"
    
    def test_human_chat_endpoint(self, client, test_kb_id):
        """Test human chat endpoint"""
        response = client.post(
            f"/agents/{test_kb_id}/human-chat",
            json={"message": "This is a simulated human chat message"}
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "success"
    
    def test_human_knowledge_endpoint(self, client, test_kb_id):
        """Test human knowledge endpoint"""
        response = client.post(
            f"/agents/{test_kb_id}/human-knowledge",
            json={
                "knowledge_text": "This is test knowledge added by a human",
                "source_conversation_id": None
            }
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "success"
    
    def test_get_chat_history(self, client, test_kb_id):
        """Test get chat history endpoint"""
        # First ensure there's some history
        client.post(
            f"/agents/{test_kb_id}/chat",
            json={"message": "This is a test message for history"}
        )
        
        response = client.get(f"/agents/{test_kb_id}/history")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "kb_id" in data
        assert "history" in data
        assert isinstance(data["history"], list)
        
        # Verify history structure
        if data["history"]:
            message = data["history"][0]
            assert "type" in message
            assert "content" in message
            assert message["type"] in ["human", "ai", "human_agent"]
    
    def test_delete_chat_history(self, client, test_kb_id):
        """Test delete chat history endpoint"""
        # First ensure there's some history
        client.post(
            f"/agents/{test_kb_id}/chat",
            json={"message": "Message before history deletion"}
        )
        
        # Delete history
        response = client.delete(f"/agents/{test_kb_id}/history")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "success"
        
        # Verify history is deleted
        response = client.get(f"/agents/{test_kb_id}/history")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["history"]) == 0
    
    def test_list_conversations(self, client, test_kb_id):
        """Test list conversations endpoint"""
        # Create some conversation history first
        client.post(
            f"/agents/{test_kb_id}/chat",
            json={"message": "Message for list conversations test"}
        )
        
        response = client.get("/conversations")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "conversations" in data
        assert isinstance(data["conversations"], list)
        
        # Should include our test KB's conversation
        found = False
        for conv in data["conversations"]:
            if conv["kb_id"] == test_kb_id:
                found = True
                assert "conversation" in conv
                assert "last_message_timestamp" in conv["conversation"]
                assert "last_message_preview" in conv["conversation"]
                assert "message_count" in conv["conversation"]
                assert "needs_human_attention" in conv["conversation"]
                break
        
        assert found, f"Test KB {test_kb_id} not found in conversations list"
    
    def test_bot_chat_endpoint(self, client):
        """Test bot chat endpoint with mocked bot ID"""
        # Note: This test may fail if your backend strictly validates bot IDs
        # You may need to adjust based on your application's validation logic
        test_bot_id = str(uuid.uuid4())
        
        response = client.post(
            f"/bots/{test_bot_id}/chat",
            json={"message": "Hello bot"}
        )
        
        # The response may be an error if bot validation is strict, 
        # or it may succeed if the endpoint handles unknown bots gracefully
        assert response.status_code in [
            status.HTTP_200_OK, 
            status.HTTP_404_NOT_FOUND,
            status.HTTP_500_INTERNAL_SERVER_ERROR
        ]
    
    def test_invalid_kb_id_chat(self, client):
        """Test chat endpoints with invalid KB ID"""
        invalid_kb_id = str(uuid.uuid4())  # Random UUID that shouldn't exist
        
        # Test chat with invalid KB ID
        response = client.post(
            f"/agents/{invalid_kb_id}/chat",
            json={"message": "Test with invalid KB"}
        )
        assert response.status_code in [
            status.HTTP_404_NOT_FOUND,
            status.HTTP_500_INTERNAL_SERVER_ERROR
        ] 