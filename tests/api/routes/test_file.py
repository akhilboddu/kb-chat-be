import pytest
import os
import tempfile
from fastapi import status
import uuid

from tests.api.routes.test_agent import TestAgentEndpoints

class TestFileEndpoints:
    """Test suite for file-related endpoints"""
    
    @pytest.fixture(scope="class")
    def test_kb_id(self, client):
        """Create a test knowledge base for file tests"""
        agent_tests = TestAgentEndpoints()
        return agent_tests.test_create_agent(client)
    
    @pytest.fixture
    def test_text_file(self):
        """Create a temporary text file for testing"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            tmp.write(b"This is test content for file upload testing.\n")
            tmp.write(b"It contains multiple lines to test parsing.\n")
            tmp.write(b"This is the third line with some test data.")
            path = tmp.name
        
        yield path
        
        # Clean up after test
        if os.path.exists(path):
            os.unlink(path)
    
    def test_upload_to_kb(self, client, test_kb_id, test_text_file):
        """Test file upload to KB endpoint"""
        with open(test_text_file, "rb") as f:
            response = client.post(
                f"/agents/{test_kb_id}/upload",
                files={"files": ("test.txt", f, "text/plain")}
            )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] in ["success", "warning"]
        assert "Processed" in data["message"]
    
    def test_list_uploaded_files(self, client, test_kb_id, test_text_file):
        """Test list uploaded files endpoint"""
        # Upload a file first to ensure there's something to list
        with open(test_text_file, "rb") as f:
            client.post(
                f"/agents/{test_kb_id}/upload",
                files={"files": ("list_test.txt", f, "text/plain")}
            )
        
        response = client.get(f"/agents/{test_kb_id}/files")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "kb_id" in data
        assert "files" in data
        assert len(data["files"]) > 0
        
        # Verify file data structure
        file_info = data["files"][0]
        assert "filename" in file_info
        assert "file_size" in file_info
        assert "content_type" in file_info
        assert "upload_timestamp" in file_info
    
    def test_upload_multiple_files(self, client, test_kb_id, test_text_file):
        """Test uploading multiple files at once"""
        with open(test_text_file, "rb") as f1, open(test_text_file, "rb") as f2:
            response = client.post(
                f"/agents/{test_kb_id}/upload",
                files=[
                    ("files", ("multi1.txt", f1, "text/plain")),
                    ("files", ("multi2.txt", f2, "text/plain"))
                ]
            )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] in ["success", "warning"]
        assert "Processed" in data["message"]
        
        # Check that both files appear in the list
        response = client.get(f"/agents/{test_kb_id}/files")
        data = response.json()
        
        filenames = [file["filename"] for file in data["files"]]
        assert "multi1.txt" in filenames
        assert "multi2.txt" in filenames
    
    def test_upload_no_files(self, client, test_kb_id):
        """Test upload endpoint with no files"""
        response = client.post(
            f"/agents/{test_kb_id}/upload",
            files={}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_upload_to_invalid_kb(self, client, test_text_file):
        """Test upload to non-existent KB"""
        invalid_kb_id = str(uuid.uuid4())
        
        with open(test_text_file, "rb") as f:
            response = client.post(
                f"/agents/{invalid_kb_id}/upload",
                files={"files": ("test.txt", f, "text/plain")}
            )
        
        # This might return different status codes depending on how your API handles invalid KBs
        assert response.status_code in [
            status.HTTP_404_NOT_FOUND,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            status.HTTP_422_UNPROCESSABLE_ENTITY
        ]
    
    def test_list_files_invalid_kb(self, client):
        """Test listing files for non-existent KB"""
        invalid_kb_id = str(uuid.uuid4())
        
        response = client.get(f"/agents/{invalid_kb_id}/files")
        assert response.status_code in [
            status.HTTP_404_NOT_FOUND,
            status.HTTP_500_INTERNAL_SERVER_ERROR
        ]
    
    def test_bot_upload_endpoint(self, client, test_text_file):
        """Test bot upload endpoint"""
        # This test may fail if strict bot validation is in place
        test_bot_id = str(uuid.uuid4())
        
        with open(test_text_file, "rb") as f:
            response = client.post(
                f"/bots/{test_bot_id}/upload",
                files={"files": ("bot_test.txt", f, "text/plain")}
            )
        
        # The response status will depend on how your API handles unknown bot IDs
        # If it fails with a specific error code, adjust this assertion accordingly
        assert response.status_code in [
            status.HTTP_200_OK,
            status.HTTP_404_NOT_FOUND,
            status.HTTP_500_INTERNAL_SERVER_ERROR
        ] 