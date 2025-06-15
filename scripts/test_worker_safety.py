#!/usr/bin/env python3
"""
Worker Safety Test Script

This script tests the thread-based Celery workers with HuggingFace embeddings
to verify that no segmentation faults occur under concurrent load.

Usage:
    python scripts/test_worker_safety.py --iterations=100 --concurrent-workers=3
"""

import argparse
import os
import sys
import time
import logging
import multiprocessing
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any

# Add the app directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Set environment variables before importing any ML libraries
os.environ.update({
    'TOKENIZERS_PARALLELISM': 'false',
    'OMP_NUM_THREADS': '1',
    'MKL_NUM_THREADS': '1',
    'NUMEXPR_NUM_THREADS': '1',
    'USE_FLEXIBLE_EMBEDDINGS': 'true',
    'EMBEDDINGS_PROVIDER': 'huggingface',
    'HF_HUB_DISABLE_TELEMETRY': '1'
})

from app.core.embeddings_flexible import get_embeddings
from app.utils.logging import get_logger

logger = get_logger(__name__)


def test_embeddings_basic(iteration: int) -> Dict[str, Any]:
    """Test basic embeddings functionality"""
    start_time = time.time()
    try:
        # Get embeddings instance
        embeddings = get_embeddings()
        
        # Test query embedding
        query = f"Test query {iteration}: What is machine learning?"
        query_embedding = embeddings.embed_query(query)
        
        # Test document embeddings
        docs = [
            f"Document {iteration}.1: Machine learning is a subset of artificial intelligence.",
            f"Document {iteration}.2: It involves training algorithms on data.",
            f"Document {iteration}.3: The goal is to make predictions or decisions."
        ]
        doc_embeddings = embeddings.embed_texts(docs)
        
        # Verify results
        assert len(query_embedding) > 0, "Query embedding is empty"
        assert len(doc_embeddings) == len(docs), "Document embeddings count mismatch"
        assert all(len(emb) > 0 for emb in doc_embeddings), "Some document embeddings are empty"
        
        # Check dimensions consistency
        expected_dim = len(query_embedding)
        assert all(len(emb) == expected_dim for emb in doc_embeddings), "Dimension mismatch"
        
        elapsed = time.time() - start_time
        return {
            "iteration": iteration,
            "status": "success",
            "elapsed_time": elapsed,
            "query_dim": len(query_embedding),
            "doc_count": len(doc_embeddings),
            "model_info": embeddings.get_embedding_info()
        }
        
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"Iteration {iteration} failed: {e}")
        return {
            "iteration": iteration,
            "status": "error",
            "elapsed_time": elapsed,
            "error": str(e)
        }


def test_embeddings_stress(iteration: int) -> Dict[str, Any]:
    """Test embeddings under stress (larger documents)"""
    start_time = time.time()
    try:
        embeddings = get_embeddings()
        
        # Create larger test documents
        large_docs = []
        for i in range(10):
            doc = f"Iteration {iteration}, Document {i}: " + " ".join([
                "This is a longer document to test the embedding system under stress."
                "We want to ensure that the system can handle multiple large documents"
                "without causing segmentation faults or memory issues."
                "Machine learning models can be memory intensive."
                "Thread-based workers should handle this better than process-based ones."
            ] * 5)  # Repeat 5 times to make it longer
            large_docs.append(doc)
        
        # Test embedding generation
        doc_embeddings = embeddings.embed_texts(large_docs)
        
        # Verify results
        assert len(doc_embeddings) == len(large_docs), "Document count mismatch"
        assert all(len(emb) > 0 for emb in doc_embeddings), "Some embeddings are empty"
        
        elapsed = time.time() - start_time
        return {
            "iteration": iteration,
            "status": "success",
            "elapsed_time": elapsed,
            "doc_count": len(doc_embeddings),
            "avg_doc_length": sum(len(doc) for doc in large_docs) / len(large_docs)
        }
        
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"Stress test iteration {iteration} failed: {e}")
        return {
            "iteration": iteration,
            "status": "error",
            "elapsed_time": elapsed,
            "error": str(e)
        }


def run_concurrent_tests(num_iterations: int, num_workers: int, test_type: str = "basic") -> List[Dict[str, Any]]:
    """Run tests concurrently to simulate worker load"""
    test_function = test_embeddings_basic if test_type == "basic" else test_embeddings_stress
    
    logger.info(f"Starting {num_iterations} {test_type} tests with {num_workers} concurrent workers")
    
    results = []
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        # Submit all tasks
        futures = [executor.submit(test_function, i) for i in range(num_iterations)]
        
        # Collect results as they complete
        for future in as_completed(futures):
            try:
                result = future.result(timeout=300)  # 5 min timeout per test
                results.append(result)
                
                if result["status"] == "success":
                    logger.info(f"✅ Test {result['iteration']} completed in {result['elapsed_time']:.2f}s")
                else:
                    logger.error(f"❌ Test {result['iteration']} failed: {result.get('error', 'Unknown error')}")
                    
            except Exception as e:
                logger.error(f"❌ Test future failed: {e}")
                results.append({
                    "iteration": -1,
                    "status": "error",
                    "error": str(e)
                })
    
    return results


def analyze_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze test results and provide summary"""
    total_tests = len(results)
    successful_tests = [r for r in results if r["status"] == "success"]
    failed_tests = [r for r in results if r["status"] == "error"]
    
    success_rate = len(successful_tests) / total_tests * 100 if total_tests > 0 else 0
    
    if successful_tests:
        avg_time = sum(r["elapsed_time"] for r in successful_tests) / len(successful_tests)
        max_time = max(r["elapsed_time"] for r in successful_tests)
        min_time = min(r["elapsed_time"] for r in successful_tests)
    else:
        avg_time = max_time = min_time = 0
    
    analysis = {
        "total_tests": total_tests,
        "successful_tests": len(successful_tests),
        "failed_tests": len(failed_tests),
        "success_rate": success_rate,
        "avg_execution_time": avg_time,
        "max_execution_time": max_time,
        "min_execution_time": min_time,
        "errors": [r["error"] for r in failed_tests if "error" in r]
    }
    
    return analysis


def main():
    parser = argparse.ArgumentParser(description="Test worker safety with HuggingFace embeddings")
    parser.add_argument("--iterations", type=int, default=50, help="Number of test iterations")
    parser.add_argument("--concurrent-workers", type=int, default=3, help="Number of concurrent workers")
    parser.add_argument("--test-type", choices=["basic", "stress", "both"], default="basic", help="Type of test to run")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    
    args = parser.parse_args()
    
    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger.info("🚀 Starting Worker Safety Tests")
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Process ID: {os.getpid()}")
    logger.info(f"CPU count: {multiprocessing.cpu_count()}")
    
    # Check environment configuration
    logger.info("📋 Environment Configuration:")
    for key in ['TOKENIZERS_PARALLELISM', 'OMP_NUM_THREADS', 'EMBEDDINGS_PROVIDER']:
        logger.info(f"  {key}: {os.getenv(key, 'NOT SET')}")
    
    all_results = []
    
    try:
        if args.test_type in ["basic", "both"]:
            logger.info("\n🧪 Running Basic Tests")
            basic_results = run_concurrent_tests(args.iterations, args.concurrent_workers, "basic")
            all_results.extend(basic_results)
            
            basic_analysis = analyze_results(basic_results)
            logger.info(f"\n📊 Basic Test Results:")
            logger.info(f"  Success Rate: {basic_analysis['success_rate']:.1f}%")
            logger.info(f"  Average Time: {basic_analysis['avg_execution_time']:.2f}s")
            logger.info(f"  Failed Tests: {basic_analysis['failed_tests']}")
        
        if args.test_type in ["stress", "both"]:
            logger.info("\n💪 Running Stress Tests")
            stress_results = run_concurrent_tests(args.iterations, args.concurrent_workers, "stress")
            all_results.extend(stress_results)
            
            stress_analysis = analyze_results(stress_results)
            logger.info(f"\n📊 Stress Test Results:")
            logger.info(f"  Success Rate: {stress_analysis['success_rate']:.1f}%")
            logger.info(f"  Average Time: {stress_analysis['avg_execution_time']:.2f}s")
            logger.info(f"  Failed Tests: {stress_analysis['failed_tests']}")
        
        # Overall analysis
        overall_analysis = analyze_results(all_results)
        logger.info(f"\n🎯 Overall Results:")
        logger.info(f"  Total Tests: {overall_analysis['total_tests']}")
        logger.info(f"  Success Rate: {overall_analysis['success_rate']:.1f}%")
        logger.info(f"  Failed Tests: {overall_analysis['failed_tests']}")
        
        if overall_analysis['errors']:
            logger.error(f"\n❌ Errors encountered:")
            for error in set(overall_analysis['errors']):
                logger.error(f"  - {error}")
        
        # Determine overall result
        if overall_analysis['success_rate'] >= 95:
            logger.info("\n✅ WORKER SAFETY TEST PASSED")
            logger.info("Thread-based workers are stable with HuggingFace embeddings")
            return 0
        else:
            logger.error("\n❌ WORKER SAFETY TEST FAILED")
            logger.error("Significant failures detected - investigate before production deployment")
            return 1
            
    except KeyboardInterrupt:
        logger.info("\n⏹️ Tests interrupted by user")
        return 1
    except Exception as e:
        logger.error(f"\n💥 Test suite failed: {e}")
        return 1


if __name__ == "__main__":
    exit(main())