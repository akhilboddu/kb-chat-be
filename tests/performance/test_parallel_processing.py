"""
Performance tests for parallel processing pipeline.
Tests concurrent context generation, embeddings, and database operations.
"""

import time
import pytest
import asyncio
import os
from typing import List
import statistics

from app.core.supabase_kb_manager import KBManager
from app.core.parallel_processor import get_parallel_processor
from app.core.smart_batcher import get_smart_batcher


def generate_test_chunks(count: int, avg_size: int = 1000) -> List[str]:
    """Generate test text chunks for performance testing."""
    chunks = []
    for i in range(count):
        # Vary chunk sizes around the average
        size_variation = int(avg_size * 0.2)  # 20% variation
        chunk_size = avg_size + (i % 5 - 2) * size_variation
        
        chunk = f"Test chunk {i}. " + "This is test content. " * (chunk_size // 25)
        chunks.append(chunk[:chunk_size])
    
    return chunks


class TestParallelProcessingPerformance:
    """Performance benchmarks for parallel processing pipeline"""
    
    @pytest.fixture
    def kb_manager(self):
        """Create KB manager instance"""
        return KBManager()
    
    @pytest.fixture
    def test_kb_id(self):
        """Test knowledge base ID"""
        return f"test-parallel-{int(time.time())}"
    
    def test_parallel_vs_sequential_performance(self, kb_manager, test_kb_id):
        """Compare parallel vs sequential processing performance"""
        # Generate test data
        chunks = generate_test_chunks(100, avg_size=1000)
        full_document = "\n\n".join(chunks)
        
        # Test sequential processing (Phase 1 optimizations)
        os.environ["ENABLE_PARALLEL_PROCESSING"] = "false"
        
        start_time = time.time()
        success = kb_manager.add_to_kb(
            kb_id=f"{test_kb_id}_sequential",
            text_to_add=full_document,
            metadata={"test": "sequential"}
        )
        sequential_time = time.time() - start_time
        
        assert success, "Sequential processing should succeed"
        print(f"\nSequential processing: {sequential_time:.2f}s ({sequential_time/100:.3f}s per chunk)")
        
        # Test parallel processing (Phase 2 optimizations)
        os.environ["ENABLE_PARALLEL_PROCESSING"] = "true"
        
        start_time = time.time()
        success = kb_manager.add_to_kb(
            kb_id=f"{test_kb_id}_parallel",
            text_to_add=full_document,
            metadata={"test": "parallel"}
        )
        parallel_time = time.time() - start_time
        
        assert success, "Parallel processing should succeed"
        print(f"Parallel processing: {parallel_time:.2f}s ({parallel_time/100:.3f}s per chunk)")
        
        # Calculate improvement
        improvement = (sequential_time - parallel_time) / sequential_time * 100
        speedup = sequential_time / parallel_time
        
        print(f"\nPerformance improvement: {improvement:.1f}%")
        print(f"Speedup factor: {speedup:.2f}x")
        
        # Assert significant improvement (at least 30%)
        assert improvement > 30, f"Parallel processing should be at least 30% faster, got {improvement:.1f}%"
    
    @pytest.mark.asyncio
    async def test_parallel_processor_stages(self):
        """Test individual stages of parallel processing"""
        processor = get_parallel_processor()
        chunks = generate_test_chunks(50, avg_size=800)
        full_document = "\n\n".join(chunks)
        
        progress_updates = []
        
        def progress_callback(percent, message):
            progress_updates.append((percent, message, time.time()))
            print(f"Progress: {percent}% - {message}")
        
        start_time = time.time()
        documents, success = await processor.process_chunks_parallel(
            chunks=chunks,
            full_document=full_document,
            kb_id="test-stages",
            progress_callback=progress_callback
        )
        elapsed = time.time() - start_time
        
        assert success, "Parallel processing should succeed"
        assert len(documents) > 0, "Should produce documents"
        assert len(progress_updates) > 0, "Should have progress updates"
        
        # Analyze stage timings
        print(f"\nTotal processing time: {elapsed:.2f}s")
        print("Stage breakdown:")
        
        last_time = start_time
        for percent, message, timestamp in progress_updates:
            stage_time = timestamp - last_time
            print(f"  {percent}% - {message} ({stage_time:.2f}s)")
            last_time = timestamp
        
        # Performance assertions
        assert elapsed < 30.0, f"Processing 50 chunks should take < 30s, took {elapsed:.2f}s"
        per_chunk_time = elapsed / len(chunks)
        assert per_chunk_time < 0.6, f"Per-chunk time should be < 0.6s, was {per_chunk_time:.3f}s"
    
    def test_smart_batching(self):
        """Test smart batching system"""
        batcher = get_smart_batcher()
        
        # Test with different scenarios
        scenarios = [
            (100, 500, "Small chunks, small batch"),
            (1000, 1000, "Medium chunks, medium batch"),
            (5000, 2000, "Large chunks, large batch"),
        ]
        
        for total_chunks, avg_size, description in scenarios:
            config = batcher.get_optimal_batch_sizes(total_chunks, avg_size)
            
            print(f"\n{description}:")
            print(f"  Total chunks: {total_chunks}, Avg size: {avg_size}")
            print(f"  Context batch: {config.context_batch_size}")
            print(f"  Embeddings batch: {config.embeddings_batch_size}")
            print(f"  DB batch: {config.db_batch_size}")
            print(f"  Reason: {config.reason}")
            
            # Validate batch sizes are within limits
            assert 10 <= config.context_batch_size <= 100
            assert 20 <= config.embeddings_batch_size <= 200
            assert 50 <= config.db_batch_size <= 500
    
    def test_concurrent_operations(self, kb_manager):
        """Test multiple concurrent KB operations"""
        import concurrent.futures
        
        def add_to_kb(kb_id: str, chunks: List[str]) -> float:
            """Add chunks to KB and return processing time"""
            start = time.time()
            success = kb_manager.add_to_kb(
                kb_id=kb_id,
                text_to_add="\n\n".join(chunks)
            )
            elapsed = time.time() - start
            return elapsed if success else -1
        
        # Enable parallel processing
        os.environ["ENABLE_PARALLEL_PROCESSING"] = "true"
        
        # Create test data
        num_operations = 5
        chunks_per_op = 20
        all_chunks = [generate_test_chunks(chunks_per_op, 800) for _ in range(num_operations)]
        
        # Run concurrent operations
        print(f"\nRunning {num_operations} concurrent KB operations...")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            start_time = time.time()
            futures = [
                executor.submit(add_to_kb, f"test-concurrent-{i}", chunks)
                for i, chunks in enumerate(all_chunks)
            ]
            
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
            total_time = time.time() - start_time
        
        # Analyze results
        successful_times = [r for r in results if r > 0]
        assert len(successful_times) == num_operations, "All operations should succeed"
        
        avg_time = statistics.mean(successful_times)
        print(f"Total time: {total_time:.2f}s")
        print(f"Average per operation: {avg_time:.2f}s")
        print(f"Theoretical sequential time: {sum(successful_times):.2f}s")
        print(f"Concurrency speedup: {sum(successful_times)/total_time:.2f}x")
        
        # Assert good concurrency
        assert total_time < sum(successful_times) * 0.7, "Should show concurrency benefits"


@pytest.mark.benchmark
class TestPerformanceBenchmarks:
    """Detailed performance benchmarks"""
    
    def test_scaling_performance(self, kb_manager):
        """Test how performance scales with chunk count"""
        os.environ["ENABLE_PARALLEL_PROCESSING"] = "true"
        
        chunk_counts = [10, 50, 100, 200, 500]
        results = []
        
        print("\nScaling performance test:")
        print("Chunks | Time (s) | Per chunk (s) | Throughput (chunks/s)")
        print("-" * 60)
        
        for count in chunk_counts:
            chunks = generate_test_chunks(count, 1000)
            text = "\n\n".join(chunks)
            
            start_time = time.time()
            success = kb_manager.add_to_kb(
                kb_id=f"test-scaling-{count}",
                text_to_add=text
            )
            elapsed = time.time() - start_time
            
            if success:
                per_chunk = elapsed / count
                throughput = count / elapsed
                results.append((count, elapsed, per_chunk, throughput))
                
                print(f"{count:6d} | {elapsed:8.2f} | {per_chunk:13.3f} | {throughput:21.1f}")
        
        # Verify scaling efficiency
        if len(results) >= 2:
            # Check that per-chunk time doesn't increase significantly
            first_per_chunk = results[0][2]
            last_per_chunk = results[-1][2]
            scaling_degradation = (last_per_chunk - first_per_chunk) / first_per_chunk * 100
            
            print(f"\nScaling degradation: {scaling_degradation:.1f}%")
            assert scaling_degradation < 50, "Per-chunk time shouldn't degrade by more than 50%"