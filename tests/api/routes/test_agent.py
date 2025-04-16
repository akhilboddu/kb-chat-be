import pytest
from fastapi import status
import uuid

class TestAgentEndpoints:
    """Test suite for agent-related endpoints"""
    
    def test_create_agent(self, client):
        """Test create agent endpoint with name"""
        response = client.post("/agents", json={"name": "Test Agent"})
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert "kb_id" in data
        assert data["name"] == "Test Agent"
        assert "message" in data
        
        # Store kb_id for later tests
        return data["kb_id"]
    
    def test_create_agent_unnamed(self, client):
        """Test create agent endpoint without name"""
        response = client.post("/agents", json={})
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert "kb_id" in data
        assert data["name"] is None
    
    def test_populate_agent_from_json(self, client):
        """Test populate agent from JSON endpoint"""
        # First create a test agent
        kb_id = self.test_create_agent(client)
        
        # Test JSON data
        json_data = {
            "company_name": "Test Company",
            "product_details": {
                "name": "Test Product",
                "version": "1.0",
                "key_features": ["Feature 1", "Feature 2"]
            }
        }
        
        response = client.post(
            f"/agents/{kb_id}/json", 
            json={"json_data": json_data}
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "success"
    
    def test_get_agent_json_payloads(self, client):
        """Test get agent JSON payloads endpoint"""
        # First create and populate a test agent
        kb_id = self.test_create_agent(client)
        self.test_populate_agent_from_json(client)
        
        response = client.get(f"/agents/{kb_id}/json")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        # Should contain at least one JSON payload
        if data:
            assert "company_name" in data[0]
    
    def test_list_kbs(self, client):
        """Test list knowledge bases endpoint"""
        # Ensure at least one KB exists
        self.test_create_agent(client)
        
        response = client.get("/agents")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "kbs" in data
        assert isinstance(data["kbs"], list)
        assert len(data["kbs"]) > 0
        
        # Check structure of KB info
        kb = data["kbs"][0]
        assert "kb_id" in kb
        assert "summary" in kb
    
    def test_get_kb_content(self, client):
        """Test get KB content endpoint"""
        # Create and populate a KB
        kb_id = self.test_create_agent(client)
        self.test_populate_agent_from_json(client)
        
        # Test with default parameters
        response = client.get(f"/agents/{kb_id}/content")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "kb_id" in data
        assert "content" in data
        assert "total_count" in data
        
        # Test with pagination parameters
        response = client.get(f"/agents/{kb_id}/content?limit=2&offset=0")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["content"]) <= 2  # May be less if there aren't enough items
    
    def test_cleanup_kb_duplicates(self, client):
        """Test cleanup KB duplicates endpoint"""
        # Create a test agent
        kb_id = self.test_create_agent(client)
        
        response = client.post(f"/agents/{kb_id}/cleanup")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "kb_id" in data
        assert "deleted_count" in data
        assert "message" in data
    
    def test_get_agent_config(self, client):
        """Test get agent config endpoint"""
        # Create a test agent
        kb_id = self.test_create_agent(client)
        
        response = client.get(f"/agents/{kb_id}/config")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "system_prompt" in data
        assert "max_iterations" in data
    
    def test_update_agent_config(self, client):
        """Test update agent config endpoint"""
        # Create a test agent
        kb_id = self.test_create_agent(client)
        
        # Update config with new values
        update_data = {
            "system_prompt": "New test system prompt",
            "max_iterations": 5
        }
        
        response = client.put(f"/agents/{kb_id}/config", json=update_data)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "success"
        
        # Verify the updates were applied
        response = client.get(f"/agents/{kb_id}/config")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["system_prompt"] == "New test system prompt"
        assert data["max_iterations"] == 5
    
    def test_delete_agent(self, client):
        """Test delete agent endpoint"""
        # Create a test agent specifically for deletion
        response = client.post("/agents", json={"name": "Test Agent for Deletion"})
        kb_id = response.json()["kb_id"]
        
        # Delete the agent
        response = client.delete(f"/agents/{kb_id}")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "success"
        
        # Verify it's deleted by trying to get the config (should 404 or 500)
        # Note: This depends on how your API handles deleted KBs
        response = client.get(f"/agents/{kb_id}/config")
        assert response.status_code in (status.HTTP_404_NOT_FOUND, status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def test_invalid_kb_id(self, client):
        """Test endpoints with invalid KB ID"""
        invalid_kb_id = str(uuid.uuid4())  # Random UUID that shouldn't exist
        
        # Test various endpoints with invalid KB ID
        endpoints = [
            f"/agents/{invalid_kb_id}/json",
            f"/agents/{invalid_kb_id}/content",
            f"/agents/{invalid_kb_id}/cleanup",
            f"/agents/{invalid_kb_id}/config"
        ]
        
        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.status_code in (status.HTTP_404_NOT_FOUND, status.HTTP_500_INTERNAL_SERVER_ERROR) 