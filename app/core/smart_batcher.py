"""
Smart batching system that dynamically adjusts batch sizes based on system resources
and document characteristics for optimal performance.
"""

import os
import psutil
import logging
from typing import List, Tuple, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class BatchConfig:
    """Configuration for batch processing"""
    context_batch_size: int
    embeddings_batch_size: int
    db_batch_size: int
    reason: str


class SmartBatcher:
    """
    Dynamic batch sizing based on system resources and document characteristics.
    Optimizes for memory usage, CPU availability, and processing speed.
    """
    
    def __init__(self):
        # Thresholds and limits
        self.memory_threshold = float(os.getenv("SMART_BATCH_MEMORY_THRESHOLD", "0.8"))  # 80% memory usage threshold
        self.cpu_threshold = float(os.getenv("SMART_BATCH_CPU_THRESHOLD", "0.9"))  # 90% CPU usage threshold
        
        # Base batch sizes from environment or defaults
        self.base_context_batch_size = int(os.getenv("CONTEXT_BATCH_SIZE", "50"))
        self.base_embeddings_batch_size = int(os.getenv("EMBEDDINGS_BATCH_SIZE", "96"))
        self.base_db_batch_size = int(os.getenv("DB_BATCH_SIZE", "100"))
        
        # Min/max limits
        self.min_context_batch = 10
        self.max_context_batch = 100
        self.min_embeddings_batch = 20
        self.max_embeddings_batch = 200
        self.min_db_batch = 50
        self.max_db_batch = 500
        
        # Performance history for adaptive learning
        self.performance_history = []
        self.max_history_size = 100
        
        logger.info(
            f"Initialized SmartBatcher with base sizes: "
            f"context={self.base_context_batch_size}, "
            f"embeddings={self.base_embeddings_batch_size}, "
            f"db={self.base_db_batch_size}"
        )
    
    def get_optimal_batch_sizes(
        self, 
        total_chunks: int, 
        avg_chunk_size: int,
        operation_type: str = "full_pipeline"
    ) -> BatchConfig:
        """
        Calculate optimal batch sizes based on system resources and document characteristics.
        
        Args:
            total_chunks: Total number of chunks to process
            avg_chunk_size: Average size of chunks in characters
            operation_type: Type of operation (full_pipeline, embeddings_only, etc.)
            
        Returns:
            BatchConfig with optimal batch sizes and reasoning
        """
        # Get current system resources
        memory = psutil.virtual_memory()
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_count = psutil.cpu_count()
        
        # Calculate available resources
        available_memory_percent = (100 - memory.percent) / 100
        available_cpu_percent = (100 - cpu_percent) / 100
        
        # Resource factors (0.0 to 1.0)
        memory_factor = min(1.0, available_memory_percent / (1.0 - self.memory_threshold))
        cpu_factor = min(1.0, available_cpu_percent / (1.0 - self.cpu_threshold))
        resource_factor = min(memory_factor, cpu_factor)
        
        # Document complexity factor based on chunk size
        if avg_chunk_size > 2000:  # Large chunks
            complexity_factor = 0.7
            complexity_reason = "large chunks"
        elif avg_chunk_size < 500:  # Small chunks
            complexity_factor = 1.3
            complexity_reason = "small chunks"
        else:
            complexity_factor = 1.0
            complexity_reason = "medium chunks"
        
        # Scale factor based on total chunks
        if total_chunks > 1000:
            scale_factor = 1.2  # Larger batches for big jobs
            scale_reason = "large document set"
        elif total_chunks < 100:
            scale_factor = 0.8  # Smaller batches for small jobs
            scale_reason = "small document set"
        else:
            scale_factor = 1.0
            scale_reason = "medium document set"
        
        # Calculate optimal sizes
        combined_factor = resource_factor * complexity_factor * scale_factor
        
        context_batch_size = self._calculate_batch_size(
            self.base_context_batch_size,
            combined_factor,
            self.min_context_batch,
            self.max_context_batch
        )
        
        embeddings_batch_size = self._calculate_batch_size(
            self.base_embeddings_batch_size,
            combined_factor,
            self.min_embeddings_batch,
            self.max_embeddings_batch
        )
        
        db_batch_size = self._calculate_batch_size(
            self.base_db_batch_size,
            combined_factor * 1.5,  # DB can handle larger batches
            self.min_db_batch,
            self.max_db_batch
        )
        
        # Adjust based on operation type
        if operation_type == "embeddings_only":
            # Focus resources on embeddings
            embeddings_batch_size = int(embeddings_batch_size * 1.5)
            context_batch_size = self.min_context_batch
        elif operation_type == "context_only":
            # Focus resources on context generation
            context_batch_size = int(context_batch_size * 1.5)
            embeddings_batch_size = self.min_embeddings_batch
        
        # Build reasoning string
        reasons = [
            f"memory={memory.percent:.1f}%",
            f"cpu={cpu_percent:.1f}%",
            complexity_reason,
            scale_reason,
            f"factor={combined_factor:.2f}"
        ]
        
        config = BatchConfig(
            context_batch_size=context_batch_size,
            embeddings_batch_size=embeddings_batch_size,
            db_batch_size=db_batch_size,
            reason=", ".join(reasons)
        )
        
        logger.info(
            f"Smart batching config: context={context_batch_size}, "
            f"embeddings={embeddings_batch_size}, db={db_batch_size} "
            f"({config.reason})"
        )
        
        return config
    
    def record_performance(
        self,
        batch_config: BatchConfig,
        duration: float,
        chunks_processed: int,
        success: bool
    ):
        """
        Record performance metrics for adaptive learning.
        
        Args:
            batch_config: The batch configuration used
            duration: Time taken in seconds
            chunks_processed: Number of chunks successfully processed
            success: Whether the operation succeeded
        """
        metric = {
            'context_batch': batch_config.context_batch_size,
            'embeddings_batch': batch_config.embeddings_batch_size,
            'db_batch': batch_config.db_batch_size,
            'duration': duration,
            'chunks_processed': chunks_processed,
            'throughput': chunks_processed / duration if duration > 0 else 0,
            'success': success,
            'timestamp': psutil.time.time()
        }
        
        self.performance_history.append(metric)
        
        # Keep history size manageable
        if len(self.performance_history) > self.max_history_size:
            self.performance_history = self.performance_history[-self.max_history_size:]
        
        # Log performance
        if success:
            logger.info(
                f"Performance recorded: {chunks_processed} chunks in {duration:.2f}s "
                f"({metric['throughput']:.1f} chunks/s) with batch sizes "
                f"context={batch_config.context_batch_size}, "
                f"embeddings={batch_config.embeddings_batch_size}"
            )
    
    def get_adaptive_batch_sizes(
        self,
        total_chunks: int,
        avg_chunk_size: int
    ) -> BatchConfig:
        """
        Get batch sizes with adaptive learning from performance history.
        Falls back to get_optimal_batch_sizes if insufficient history.
        
        Args:
            total_chunks: Total number of chunks to process
            avg_chunk_size: Average size of chunks in characters
            
        Returns:
            BatchConfig with adaptive batch sizes
        """
        # Need at least 10 successful runs for adaptive learning
        successful_runs = [m for m in self.performance_history if m['success']]
        
        if len(successful_runs) < 10:
            # Not enough history, use standard optimization
            return self.get_optimal_batch_sizes(total_chunks, avg_chunk_size)
        
        # Find the configuration with best throughput in recent history
        recent_runs = successful_runs[-20:]  # Last 20 successful runs
        best_run = max(recent_runs, key=lambda x: x['throughput'])
        
        # Use best configuration as base, then apply current resource adjustments
        self.base_context_batch_size = best_run['context_batch']
        self.base_embeddings_batch_size = best_run['embeddings_batch']
        self.base_db_batch_size = best_run['db_batch']
        
        # Get optimized sizes based on current resources
        config = self.get_optimal_batch_sizes(total_chunks, avg_chunk_size)
        config.reason += f", adaptive from {best_run['throughput']:.1f} chunks/s"
        
        return config
    
    def _calculate_batch_size(
        self,
        base_size: int,
        factor: float,
        min_size: int,
        max_size: int
    ) -> int:
        """Calculate batch size with bounds checking."""
        size = int(base_size * factor)
        return max(min_size, min(max_size, size))
    
    def get_system_info(self) -> Dict[str, Any]:
        """Get current system resource information."""
        memory = psutil.virtual_memory()
        return {
            'memory_percent': memory.percent,
            'memory_available_gb': memory.available / (1024**3),
            'cpu_percent': psutil.cpu_percent(interval=0.1),
            'cpu_count': psutil.cpu_count(),
            'performance_history_size': len(self.performance_history),
            'successful_runs': len([m for m in self.performance_history if m['success']])
        }


# Global instance
_smart_batcher = None

def get_smart_batcher() -> SmartBatcher:
    """
    Get or create the singleton SmartBatcher instance.
    
    Returns:
        SmartBatcher instance
    """
    global _smart_batcher
    if _smart_batcher is None:
        _smart_batcher = SmartBatcher()
    return _smart_batcher