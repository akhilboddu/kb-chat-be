#!/usr/bin/env python3
"""
Embeddings Test Script

This script tests both Cohere and HuggingFace embeddings providers to ensure they work correctly.

Usage:
    python scripts/test_embeddings.py
    python scripts/test_embeddings.py --provider cohere
    python scripts/test_embeddings.py --provider huggingface
    python scripts/test_embeddings.py --model mixedbread-ai/mxbai-embed-large-v1
"""

import argparse
import os
import sys
import time
from typing import List

# Add the app directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv()

from app.core.embeddings_flexible import FlexibleEmbeddings


def test_embeddings(provider: str = None, model: str = None) -> bool:
    """Test embeddings provider with sample data"""
    
    print(f"Testing embeddings provider: {provider or 'auto-detect'}")
    if model:
        print(f"Using model: {model}")
    
    try:
        # Initialize embeddings
        if provider and model:
            embeddings = FlexibleEmbeddings.get_embeddings(provider, model_name=model)
        elif provider:
            embeddings = FlexibleEmbeddings.get_embeddings(provider)
        else:
            embeddings = FlexibleEmbeddings.get_embeddings()
        
        # Get model info
        info = embeddings.get_embedding_info()
        print(f"✅ Initialized {info['provider']} embeddings")
        print(f"   Model: {info['model']}")
        print(f"   Dimensions: {info['dimension']}")
        print(f"   Batch size: {info['batch_size']}")
        
        # Test data
        test_texts = [
            "The quick brown fox jumps over the lazy dog",
            "Artificial intelligence is transforming the world",
            "Python is a versatile programming language",
            "Machine learning enables computers to learn from data",
            ""  # Test empty string handling
        ]
        
        test_query = "What is artificial intelligence?"
        
        print(f"\n📝 Testing with {len(test_texts)} sample texts...")
        
        # Test document embedding
        start_time = time.time()
        document_embeddings = embeddings.embed_texts(test_texts)
        doc_time = time.time() - start_time
        
        print(f"✅ Document embeddings generated in {doc_time:.2f}s")
        print(f"   Generated {len(document_embeddings)} embeddings")
        
        # Verify dimensions
        for i, embedding in enumerate(document_embeddings):
            if len(embedding) != info['dimension']:
                print(f"❌ Dimension mismatch for text {i}: {len(embedding)} != {info['dimension']}")
                return False
        
        print(f"✅ All embeddings have correct dimensions ({info['dimension']})")
        
        # Test query embedding
        start_time = time.time()
        query_embedding = embeddings.embed_query(test_query)
        query_time = time.time() - start_time
        
        print(f"✅ Query embedding generated in {query_time:.2f}s")
        
        if len(query_embedding) != info['dimension']:
            print(f"❌ Query embedding dimension mismatch: {len(query_embedding)} != {info['dimension']}")
            return False
        
        # Test similarity (basic check)
        def cosine_similarity(a: List[float], b: List[float]) -> float:
            dot_product = sum(x * y for x, y in zip(a, b))
            norm_a = sum(x * x for x in a) ** 0.5
            norm_b = sum(x * x for x in b) ** 0.5
            return dot_product / (norm_a * norm_b) if norm_a > 0 and norm_b > 0 else 0
        
        # Find most similar document to query
        similarities = [
            cosine_similarity(query_embedding, doc_emb) 
            for doc_emb in document_embeddings[:-1]  # Exclude empty string
        ]
        
        max_sim_idx = similarities.index(max(similarities))
        max_similarity = similarities[max_sim_idx]
        
        print(f"📊 Similarity test:")
        print(f"   Query: '{test_query}'")
        print(f"   Most similar text: '{test_texts[max_sim_idx]}'")
        print(f"   Similarity score: {max_similarity:.3f}")
        
        if max_similarity < 0.1:
            print(f"⚠️  Low similarity score - embeddings might not be working correctly")
            return False
        
        # Test empty string handling
        empty_embedding = document_embeddings[-1]
        if all(x == 0.0 for x in empty_embedding):
            print(f"✅ Empty string correctly handled (zero embedding)")
        else:
            print(f"⚠️  Empty string not handled as expected")
        
        print(f"\n🎉 All tests passed for {info['provider']} provider!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_all_providers():
    """Test all available providers"""
    providers_to_test = []
    
    # Check if Cohere is available
    if os.getenv("COHERE_API_KEY"):
        providers_to_test.append(("cohere", None))
    else:
        print("⚠️  Cohere API key not found, skipping Cohere tests")
    
    # Test HuggingFace providers
    hf_models = [
        "mixedbread-ai/mxbai-embed-large-v1",
        "sentence-transformers/all-MiniLM-L6-v2"  # Smaller model for faster testing
    ]
    
    for model in hf_models:
        providers_to_test.append(("huggingface", model))
    
    # Run tests
    results = {}
    for provider, model in providers_to_test:
        test_name = f"{provider}:{model}" if model else provider
        print(f"\n{'='*60}")
        print(f"TESTING: {test_name}")
        print(f"{'='*60}")
        
        results[test_name] = test_embeddings(provider, model)
    
    # Summary
    print(f"\n{'='*60}")
    print("TEST SUMMARY")
    print(f"{'='*60}")
    
    for test_name, success in results.items():
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{test_name:<40} {status}")
    
    total_tests = len(results)
    passed_tests = sum(results.values())
    
    print(f"\nOverall: {passed_tests}/{total_tests} tests passed")
    
    return passed_tests == total_tests


def main():
    parser = argparse.ArgumentParser(description="Test embeddings providers")
    parser.add_argument("--provider", choices=["cohere", "huggingface"], 
                       help="Specific provider to test")
    parser.add_argument("--model", help="Specific model to test (for HuggingFace)")
    parser.add_argument("--all", action="store_true", help="Test all available providers")
    
    args = parser.parse_args()
    
    if args.all:
        success = test_all_providers()
        sys.exit(0 if success else 1)
    elif args.provider or args.model:
        success = test_embeddings(args.provider, args.model)
        sys.exit(0 if success else 1)
    else:
        # Test current configuration
        print("Testing current embeddings configuration...")
        success = test_embeddings()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()