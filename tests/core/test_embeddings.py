"""
Tests for Cohere embeddings module
"""

import os
import pytest
from unittest.mock import Mock, patch, MagicMock
from app.core.embeddings import CohereEmbeddings, get_embeddings


class TestCohereEmbeddings:
    """Test suite for CohereEmbeddings class"""
    
    @patch.dict(os.environ, {"COHERE_API_KEY": "test-api-key"})
    def test_initialization(self):
        """Test CohereEmbeddings initialization"""
        embeddings = CohereEmbeddings()
        assert embeddings.api_key == "test-api-key"
        assert embeddings.MODEL == "embed-english-v3.0"
        assert embeddings.EMBEDDING_DIM == 768
        assert embeddings.BATCH_SIZE == 96
    
    def test_initialization_no_api_key(self):
        """Test initialization fails without API key"""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="COHERE_API_KEY"):
                CohereEmbeddings()
    
    @patch('cohere.Client')
    @patch.dict(os.environ, {"COHERE_API_KEY": "test-api-key"})
    def test_embed_texts(self, mock_client_class):
        """Test embedding multiple texts"""
        # Mock the Cohere client and response
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        # Create mock embeddings (768-dim vectors)
        mock_embedding_1 = [0.1] * 768
        mock_embedding_2 = [0.2] * 768
        
        mock_response = Mock()
        mock_response.embeddings = [
            Mock(float_=mock_embedding_1),
            Mock(float_=mock_embedding_2)
        ]
        mock_client.embed.return_value = mock_response
        
        # Test embedding
        embeddings = CohereEmbeddings()
        result = embeddings.embed_texts(["text1", "text2"])
        
        # Verify
        assert len(result) == 2
        assert len(result[0]) == 768
        assert len(result[1]) == 768
        assert result[0] == mock_embedding_1
        assert result[1] == mock_embedding_2
        
        # Check API call
        mock_client.embed.assert_called_once_with(
            texts=["text1", "text2"],
            model="embed-english-v3.0",
            input_type="search_document"
        )
    
    @patch('cohere.Client')
    @patch.dict(os.environ, {"COHERE_API_KEY": "test-api-key"})
    def test_embed_query(self, mock_client_class):
        """Test embedding a single query"""
        # Mock setup
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        mock_embedding = [0.3] * 768
        mock_response = Mock()
        mock_response.embeddings = [Mock(float_=mock_embedding)]
        mock_client.embed.return_value = mock_response
        
        # Test
        embeddings = CohereEmbeddings()
        result = embeddings.embed_query("search query")
        
        # Verify
        assert len(result) == 768
        assert result == mock_embedding
        
        # Check API call used search_query type
        mock_client.embed.assert_called_once_with(
            texts=["search query"],
            model="embed-english-v3.0",
            input_type="search_query"
        )
    
    @patch('cohere.Client')
    @patch.dict(os.environ, {"COHERE_API_KEY": "test-api-key"})
    def test_batch_processing(self, mock_client_class):
        """Test that large lists are processed in batches"""
        # Mock setup
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        # Create response for each batch
        def create_batch_response(batch_size):
            embeddings = [Mock(float_=[0.1] * 768) for _ in range(batch_size)]
            response = Mock()
            response.embeddings = embeddings
            return response
        
        # Configure mock to return appropriate responses
        mock_client.embed.side_effect = [
            create_batch_response(96),  # First batch
            create_batch_response(54)   # Second batch
        ]
        
        # Test with 150 texts (should be split into 2 batches: 96 + 54)
        embeddings = CohereEmbeddings()
        texts = [f"text{i}" for i in range(150)]
        result = embeddings.embed_texts(texts)
        
        # Verify
        assert len(result) == 150
        assert all(len(emb) == 768 for emb in result)
        assert mock_client.embed.call_count == 2
        
        # Check batch sizes
        first_call_texts = mock_client.embed.call_args_list[0][1]['texts']
        second_call_texts = mock_client.embed.call_args_list[1][1]['texts']
        assert len(first_call_texts) == 96
        assert len(second_call_texts) == 54
    
    @patch('cohere.Client')
    @patch.dict(os.environ, {"COHERE_API_KEY": "test-api-key"})
    def test_empty_text_handling(self, mock_client_class):
        """Test handling of empty texts"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        embeddings = CohereEmbeddings()
        
        # Test completely empty list
        result = embeddings.embed_texts([])
        assert result == []
        
        # Test empty string
        result = embeddings.embed_query("")
        assert len(result) == 768
        assert all(v == 0.0 for v in result)
        
        # Test list with empty strings
        result = embeddings.embed_texts(["", "  ", None])
        assert len(result) == 3
        assert all(len(emb) == 768 for emb in result)
        assert all(all(v == 0.0 for v in emb) for emb in result)
    
    @patch('cohere.Client')
    @patch.dict(os.environ, {"COHERE_API_KEY": "test-api-key"})
    def test_mixed_empty_and_valid_texts(self, mock_client_class):
        """Test handling mix of empty and valid texts"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        mock_response = Mock()
        mock_response.embeddings = [Mock(float_=[0.5] * 768)]
        mock_client.embed.return_value = mock_response
        
        embeddings = CohereEmbeddings()
        result = embeddings.embed_texts(["", "valid text", "  ", None])
        
        # Verify
        assert len(result) == 4
        assert all(v == 0.0 for v in result[0])  # Empty string
        assert all(v == 0.5 for v in result[1])  # Valid text
        assert all(v == 0.0 for v in result[2])  # Whitespace
        assert all(v == 0.0 for v in result[3])  # None
        
        # Only "valid text" should be sent to API
        mock_client.embed.assert_called_once()
        call_texts = mock_client.embed.call_args[1]['texts']
        assert call_texts == ["valid text"]
    
    @patch.dict(os.environ, {"COHERE_API_KEY": "test-api-key"})
    def test_get_embedding_info(self):
        """Test getting embedding model info"""
        embeddings = CohereEmbeddings()
        info = embeddings.get_embedding_info()
        
        assert info == {
            "model": "embed-english-v3.0",
            "dimension": 768,
            "batch_size": 96,
            "provider": "cohere"
        }
    
    @patch('app.core.embeddings.CohereEmbeddings')
    def test_get_embeddings_singleton(self, mock_embeddings_class):
        """Test singleton pattern for get_embeddings"""
        mock_instance = Mock()
        mock_embeddings_class.return_value = mock_instance
        
        # First call creates instance
        instance1 = get_embeddings()
        assert instance1 == mock_instance
        mock_embeddings_class.assert_called_once()
        
        # Second call returns same instance
        instance2 = get_embeddings()
        assert instance2 == instance1
        assert mock_embeddings_class.call_count == 1  # Still only called once


@pytest.mark.integration
class TestCohereEmbeddingsIntegration:
    """Integration tests that actually call Cohere API (skipped by default)"""
    
    @pytest.mark.skipif(
        not os.getenv("COHERE_API_KEY"),
        reason="COHERE_API_KEY not set"
    )
    def test_real_embedding_generation(self):
        """Test actual embedding generation with Cohere API"""
        embeddings = CohereEmbeddings()
        
        # Test single text
        result = embeddings.embed_texts(["Hello, world!"])
        assert len(result) == 1
        assert len(result[0]) == 768
        assert all(isinstance(v, float) for v in result[0])
        
        # Test query embedding
        query_emb = embeddings.embed_query("search for hello")
        assert len(query_emb) == 768
        assert all(isinstance(v, float) for v in query_emb) 