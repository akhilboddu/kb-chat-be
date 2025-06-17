"""
Performance monitoring utility for tracking embeddings and processing performance.
Provides decorators and utilities to monitor system performance in production.
"""

import os
import time
import logging
from functools import wraps
from typing import Dict, Any, List, Optional
import json
from collections import defaultdict

logger = logging.getLogger(__name__)


class PerformanceMonitor:
    """Monitor and log performance metrics for system optimization"""
    
    def __init__(self):
        self.metrics = defaultdict(list)
        self.enabled = os.getenv("ENABLE_PERFORMANCE_MONITORING", "false").lower() == "true"
        self.log_to_file = os.getenv("PERFORMANCE_LOG_FILE", "false").lower() == "true"
        self.log_file_path = os.getenv("PERFORMANCE_LOG_PATH", "/app/logs/performance.json")
        
        if self.enabled:
            logger.info("🔍 Performance monitoring enabled")
        else:
            logger.info("⚪ Performance monitoring disabled")
    
    def time_operation(self, operation_name: str):
        """Decorator to time operations and log performance metrics"""
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                if not self.enabled:
                    return func(*args, **kwargs)
                
                start_time = time.time()
                start_memory = self._get_memory_usage()
                
                try:
                    result = func(*args, **kwargs)
                    elapsed = time.time() - start_time
                    end_memory = self._get_memory_usage()
                    memory_delta = end_memory - start_memory if end_memory and start_memory else 0
                    
                    self._record_metric(
                        operation=operation_name,
                        duration=elapsed,
                        status="success",
                        memory_delta=memory_delta,
                        args_count=len(args),
                        kwargs_keys=list(kwargs.keys())
                    )
                    return result
                    
                except Exception as e:
                    elapsed = time.time() - start_time
                    end_memory = self._get_memory_usage()
                    memory_delta = end_memory - start_memory if end_memory and start_memory else 0
                    
                    self._record_metric(
                        operation=operation_name,
                        duration=elapsed,
                        status="error",
                        error=str(e),
                        memory_delta=memory_delta,
                        args_count=len(args),
                        kwargs_keys=list(kwargs.keys())
                    )
                    raise
            return wrapper
        return decorator
    
    def time_batch_operation(self, operation_name: str, batch_size: int):
        """Decorator specifically for batch operations (embeddings, context generation)"""
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                if not self.enabled:
                    return func(*args, **kwargs)
                
                start_time = time.time()
                start_memory = self._get_memory_usage()
                
                try:
                    result = func(*args, **kwargs)
                    elapsed = time.time() - start_time
                    end_memory = self._get_memory_usage()
                    memory_delta = end_memory - start_memory if end_memory and start_memory else 0
                    
                    # Calculate per-item performance
                    per_item_time = elapsed / batch_size if batch_size > 0 else elapsed
                    throughput = batch_size / elapsed if elapsed > 0 else 0
                    
                    self._record_metric(
                        operation=operation_name,
                        duration=elapsed,
                        status="success",
                        batch_size=batch_size,
                        per_item_time=per_item_time,
                        throughput=throughput,
                        memory_delta=memory_delta
                    )
                    
                    # Log performance for immediate feedback
                    logger.info(
                        f"PERFORMANCE: {operation_name} - {batch_size} items in {elapsed:.3f}s "
                        f"({per_item_time:.3f}s/item, {throughput:.1f} items/s)"
                    )
                    
                    return result
                    
                except Exception as e:
                    elapsed = time.time() - start_time
                    self._record_metric(
                        operation=operation_name,
                        duration=elapsed,
                        status="error",
                        error=str(e),
                        batch_size=batch_size
                    )
                    raise
            return wrapper
        return decorator
    
    def record_embeddings_performance(self, 
                                     provider: str, 
                                     model: str, 
                                     batch_size: int, 
                                     duration: float, 
                                     success: bool = True,
                                     error: str = None):
        """Record embeddings-specific performance metrics"""
        if not self.enabled:
            return
        
        per_item_time = duration / batch_size if batch_size > 0 else duration
        throughput = batch_size / duration if duration > 0 else 0
        
        metric = {
            'operation': 'embeddings_generation',
            'provider': provider,
            'model': model,
            'batch_size': batch_size,
            'duration': duration,
            'per_item_time': per_item_time,
            'throughput': throughput,
            'status': 'success' if success else 'error',
            'timestamp': time.time()
        }
        
        if error:
            metric['error'] = error
        
        self.metrics['embeddings'].append(metric)
        self._maybe_log_to_file(metric)
        
        # Log performance summary
        status_emoji = "✅" if success else "❌"
        logger.info(
            f"EMBEDDINGS {status_emoji}: {provider}/{model} - {batch_size} embeddings in {duration:.3f}s "
            f"({per_item_time:.3f}s/embedding, {throughput:.1f} embeddings/s)"
        )
    
    def record_context_performance(self,
                                  provider: str,
                                  batch_size: int,
                                  duration: float,
                                  success: bool = True,
                                  error: str = None):
        """Record context generation performance metrics"""
        if not self.enabled:
            return
        
        per_item_time = duration / batch_size if batch_size > 0 else duration
        throughput = batch_size / duration if duration > 0 else 0
        
        metric = {
            'operation': 'context_generation',
            'provider': provider,
            'batch_size': batch_size,
            'duration': duration,
            'per_item_time': per_item_time,
            'throughput': throughput,
            'status': 'success' if success else 'error',
            'timestamp': time.time()
        }
        
        if error:
            metric['error'] = error
        
        self.metrics['context'].append(metric)
        self._maybe_log_to_file(metric)
        
        # Log performance summary
        status_emoji = "✅" if success else "❌"
        logger.info(
            f"CONTEXT {status_emoji}: {provider} - {batch_size} contexts in {duration:.3f}s "
            f"({per_item_time:.3f}s/context, {throughput:.1f} contexts/s)"
        )
    
    def get_performance_summary(self, operation: str = None) -> Dict[str, Any]:
        """Get performance summary statistics"""
        if not self.enabled:
            return {"enabled": False}
        
        if operation:
            metrics = self.metrics.get(operation, [])
        else:
            metrics = []
            for op_metrics in self.metrics.values():
                metrics.extend(op_metrics)
        
        if not metrics:
            return {"operation": operation, "metrics_count": 0}
        
        # Calculate statistics
        durations = [m['duration'] for m in metrics if 'duration' in m]
        throughputs = [m['throughput'] for m in metrics if 'throughput' in m]
        success_count = len([m for m in metrics if m.get('status') == 'success'])
        error_count = len([m for m in metrics if m.get('status') == 'error'])
        
        summary = {
            'operation': operation,
            'metrics_count': len(metrics),
            'success_count': success_count,
            'error_count': error_count,
            'success_rate': success_count / len(metrics) if metrics else 0,
        }
        
        if durations:
            summary.update({
                'avg_duration': sum(durations) / len(durations),
                'min_duration': min(durations),
                'max_duration': max(durations)
            })
        
        if throughputs:
            summary.update({
                'avg_throughput': sum(throughputs) / len(throughputs),
                'min_throughput': min(throughputs),
                'max_throughput': max(throughputs)
            })
        
        return summary
    
    def get_recent_performance(self, operation: str, minutes: int = 10) -> List[Dict[str, Any]]:
        """Get recent performance metrics for an operation"""
        if not self.enabled:
            return []
        
        cutoff_time = time.time() - (minutes * 60)
        metrics = self.metrics.get(operation, [])
        
        return [
            m for m in metrics 
            if m.get('timestamp', 0) > cutoff_time
        ]
    
    def clear_metrics(self, operation: str = None):
        """Clear stored metrics"""
        if operation:
            self.metrics[operation] = []
        else:
            self.metrics.clear()
        
        logger.info(f"🧹 Cleared performance metrics for {operation or 'all operations'}")
    
    def _record_metric(self, operation: str, duration: float, status: str, **kwargs):
        """Internal method to record a metric"""
        metric = {
            'operation': operation,
            'duration': duration,
            'status': status,
            'timestamp': time.time(),
            **kwargs
        }
        
        self.metrics[operation].append(metric)
        self._maybe_log_to_file(metric)
        
        # Log basic performance info
        logger.info(f"PERFORMANCE: {operation} completed in {duration:.3f}s ({status})")
    
    def _get_memory_usage(self) -> Optional[float]:
        """Get current memory usage in MB"""
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss / 1024 / 1024  # MB
        except ImportError:
            return None
        except Exception:
            return None
    
    def _maybe_log_to_file(self, metric: Dict[str, Any]):
        """Log metric to file if enabled"""
        if not self.log_to_file:
            return
        
        try:
            # Ensure log directory exists
            os.makedirs(os.path.dirname(self.log_file_path), exist_ok=True)
            
            # Append metric to log file
            with open(self.log_file_path, 'a') as f:
                f.write(json.dumps(metric) + '\n')
        except Exception as e:
            logger.warning(f"Failed to log performance metric to file: {e}")


# Global instance
performance_monitor = PerformanceMonitor()


# Convenience decorators
def time_embeddings(func):
    """Decorator for embeddings operations"""
    return performance_monitor.time_operation("embeddings")(func)


def time_context_generation(func):
    """Decorator for context generation operations"""
    return performance_monitor.time_operation("context_generation")(func)


def time_kb_operations(func):
    """Decorator for knowledge base operations"""
    return performance_monitor.time_operation("kb_operations")(func)


def time_file_processing(func):
    """Decorator for file processing operations"""
    return performance_monitor.time_operation("file_processing")(func)