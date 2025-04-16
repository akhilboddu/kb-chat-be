import pytest
from fastapi import status
import uuid
import time

from tests.api.routes.test_agent import TestAgentEndpoints

class TestScrapeEndpoints:
    """Test suite for scraping-related endpoints"""
    
    @pytest.fixture(scope="class")
    def test_kb_id(self, client):
        """Create a test knowledge base for scrape tests"""
        agent_tests = TestAgentEndpoints()
        return agent_tests.test_create_agent(client)
    
    def test_scrape_url_endpoint(self, client, test_kb_id):
        """Test scrape URL endpoint"""
        # Use a reliable test URL
        test_url = "https://example.com"
        
        response = client.post(
            f"/agents/{test_kb_id}/scrape-url",
            json={"url": test_url, "max_pages": 1}
        )
        
        assert response.status_code == status.HTTP_202_ACCEPTED
        data = response.json()
        assert "kb_id" in data
        assert data["kb_id"] == test_kb_id
        assert "status" in data
        assert data["status"] == "processing"
        assert "submitted_url" in data
        assert data["submitted_url"] == test_url
    
    def test_get_scrape_status(self, client, test_kb_id):
        """Test get scrape status endpoint"""
        # Start a scrape first
        test_url = "https://example.com"
        client.post(
            f"/agents/{test_kb_id}/scrape-url",
            json={"url": test_url, "max_pages": 1}
        )
        
        # Allow a bit of time for processing to start
        time.sleep(1)
        
        response = client.get(f"/agents/{test_kb_id}/scrape-status")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert "kb_id" in data
        assert data["kb_id"] == test_kb_id
        assert "status" in data
        assert data["status"] in ["processing", "completed", "failed"]
        assert "submitted_url" in data
        assert data["submitted_url"] == test_url
        assert "progress" in data
    
    def test_invalid_kb_id_scrape(self, client):
        """Test scrape endpoints with invalid KB ID"""
        invalid_kb_id = str(uuid.uuid4())  # Random UUID that shouldn't exist
        
        # Test scrape-url with invalid KB ID
        response = client.post(
            f"/agents/{invalid_kb_id}/scrape-url",
            json={"url": "https://example.com", "max_pages": 1}
        )
        assert response.status_code in [
            status.HTTP_404_NOT_FOUND,
            status.HTTP_500_INTERNAL_SERVER_ERROR
        ]
        
        # Test get-status with invalid KB ID
        response = client.get(f"/agents/{invalid_kb_id}/scrape-status")
        assert response.status_code in [
            status.HTTP_404_NOT_FOUND,
            status.HTTP_500_INTERNAL_SERVER_ERROR
        ]
    
    def test_invalid_url_scrape(self, client, test_kb_id):
        """Test scrape endpoint with invalid URL"""
        # This should be caught by Pydantic validation
        response = client.post(
            f"/agents/{test_kb_id}/scrape-url",
            json={"url": "not-a-valid-url", "max_pages": 1}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    
    def test_scrape_with_custom_settings(self, client, test_kb_id):
        """Test scrape URL with custom max_pages setting"""
        test_url = "https://example.com"
        custom_max_pages = 5
        
        response = client.post(
            f"/agents/{test_kb_id}/scrape-url",
            json={"url": test_url, "max_pages": custom_max_pages}
        )
        
        assert response.status_code == status.HTTP_202_ACCEPTED
        data = response.json()
        assert data["kb_id"] == test_kb_id
        
        # Allow a bit of time for processing to start
        time.sleep(1)
        
        # Check that the status reflects our custom setting
        response = client.get(f"/agents/{test_kb_id}/scrape-status")
        data = response.json()
        
        # The total_pages should match our custom setting
        # (If this field is named differently in your API, adjust accordingly)
        assert "total_pages" in data
        assert data["total_pages"] == custom_max_pages 