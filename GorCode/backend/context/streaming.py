"""
Streaming Optimizer
===================

Optimizations for streaming model responses.
"""

from typing import Any, Dict, List, Optional, Generator, Callable
from dataclasses import dataclass, field
from datetime import datetime
import threading
import queue
import time


@dataclass
class StreamChunk:
    """A chunk of streaming response."""
    
    content: str
    is_thinking: bool = False
    is_tool_call: bool = False
    tool_name: Optional[str] = None
    is_final: bool = False
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "content": self.content,
            "is_thinking": self.is_thinking,
            "is_tool_call": self.is_tool_call,
            "tool_name": self.tool_name,
            "is_final": self.is_final,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class StreamStats:
    """Statistics for a streaming response."""
    
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    chunk_count: int = 0
    total_chars: int = 0
    thinking_chunks: int = 0
    tool_call_chunks: int = 0
    
    @property
    def duration_ms(self) -> float:
        """Get duration in milliseconds."""
        end = self.end_time or datetime.now()
        return (end - self.start_time).total_seconds() * 1000
    
    @property
    def chars_per_second(self) -> float:
        """Get characters per second."""
        duration = self.duration_ms / 1000
        if duration == 0:
            return 0
        return self.total_chars / duration


class StreamBuffer:
    """
    Buffer for streaming responses.
    
    Provides:
    - Chunk accumulation
    - Content extraction
    - Thinking/tool detection
    """
    
    def __init__(self, max_size: int = 100000):
        """
        Initialize stream buffer.
        
        Args:
            max_size: Maximum buffer size in characters
        """
        self.max_size = max_size
        self._buffer: List[StreamChunk] = []
        self._content_buffer: str = ""
        self._thinking_buffer: str = ""
        self._lock = threading.Lock()
        self._stats = StreamStats()
    
    def add_chunk(self, chunk: StreamChunk) -> None:
        """
        Add a chunk to the buffer.
        
        Args:
            chunk: Chunk to add
        """
        with self._lock:
            self._buffer.append(chunk)
            self._stats.chunk_count += 1
            
            if chunk.content:
                self._stats.total_chars += len(chunk.content)
                
                if chunk.is_thinking:
                    self._thinking_buffer += chunk.content
                    self._stats.thinking_chunks += 1
                else:
                    self._content_buffer += chunk.content
            
            if chunk.is_tool_call:
                self._stats.tool_call_chunks += 1
            
            if chunk.is_final:
                self._stats.end_time = datetime.now()
            
            # Trim if needed
            if len(self._content_buffer) > self.max_size:
                self._content_buffer = self._content_buffer[-self.max_size:]
    
    def get_content(self) -> str:
        """Get accumulated content."""
        with self._lock:
            return self._content_buffer
    
    def get_thinking(self) -> str:
        """Get accumulated thinking content."""
        with self._lock:
            return self._thinking_buffer
    
    def get_all_chunks(self) -> List[StreamChunk]:
        """Get all chunks."""
        with self._lock:
            return self._buffer.copy()
    
    def get_stats(self) -> StreamStats:
        """Get stream statistics."""
        with self._lock:
            return self._stats
    
    def clear(self) -> None:
        """Clear the buffer."""
        with self._lock:
            self._buffer.clear()
            self._content_buffer = ""
            self._thinking_buffer = ""
            self._stats = StreamStats()


class StreamingOptimizer:
    """
    Optimizer for streaming responses.
    
    Features:
    - Content buffering
    - Debouncing for UI updates
    - Thinking detection
    - Performance tracking
    """
    
    DEFAULT_DEBOUNCE_MS = 50  # Minimum time between UI updates
    THINKING_TAGS = ["<thinking>", "<think>", "[thinking]"]
    THINKING_END_TAGS = ["</thinking>", "</think>", "[/thinking]"]
    
    def __init__(
        self,
        debounce_ms: int = None,
        on_content: Callable[[str], None] = None,
        on_thinking: Callable[[str], None] = None,
        on_tool_call: Callable[[str, str], None] = None,
    ):
        """
        Initialize streaming optimizer.
        
        Args:
            debounce_ms: Debounce interval in milliseconds
            on_content: Callback for content updates
            on_thinking: Callback for thinking updates
            on_tool_call: Callback for tool calls (name, arguments)
        """
        self.debounce_ms = debounce_ms or self.DEFAULT_DEBOUNCE_MS
        self.on_content = on_content
        self.on_thinking = on_thinking
        self.on_tool_call = on_tool_call
        
        self._buffer = StreamBuffer()
        self._in_thinking = False
        self._last_update_time = datetime.now()
        self._pending_content = ""
    
    def process_chunk(self, content: str) -> Optional[StreamChunk]:
        """
        Process a chunk of streaming content.
        
        Args:
            content: Content chunk
            
        Returns:
            Processed StreamChunk or None
        """
        chunk = self._parse_chunk(content)
        if chunk:
            self._buffer.add_chunk(chunk)
            self._handle_callbacks(chunk)
        return chunk
    
    def _parse_chunk(self, content: str) -> Optional[StreamChunk]:
        """Parse raw content into a StreamChunk."""
        if not content:
            return None
        
        # Check for thinking tags
        is_thinking = False
        
        for tag in self.THINKING_TAGS:
            if tag in content:
                self._in_thinking = True
                content = content.replace(tag, "")
        
        for tag in self.THINKING_END_TAGS:
            if tag in content:
                self._in_thinking = False
                content = content.replace(tag, "")
        
        is_thinking = self._in_thinking
        
        # Check for tool call patterns
        # This is simplified - real implementation would parse JSON
        is_tool_call = '"name"' in content and '"arguments"' in content
        tool_name = None
        
        if is_tool_call:
            # Extract tool name if possible
            import re
            match = re.search(r'"name"\s*:\s*"([^"]+)"', content)
            if match:
                tool_name = match.group(1)
        
        return StreamChunk(
            content=content,
            is_thinking=is_thinking,
            is_tool_call=is_tool_call,
            tool_name=tool_name,
        )
    
    def _handle_callbacks(self, chunk: StreamChunk) -> None:
        """Handle registered callbacks with debouncing."""
        now = datetime.now()
        time_since_last = (now - self._last_update_time).total_seconds() * 1000
        
        # Accumulate content
        if chunk.content:
            self._pending_content += chunk.content
        
        # Check debounce
        should_update = (
            time_since_last >= self.debounce_ms or
            chunk.is_final or
            chunk.is_tool_call
        )
        
        if should_update and self._pending_content:
            if chunk.is_thinking and self.on_thinking:
                self.on_thinking(self._pending_content)
            elif self.on_content:
                self.on_content(self._pending_content)
            
            self._pending_content = ""
            self._last_update_time = now
        
        # Tool call callback
        if chunk.is_tool_call and chunk.tool_name and self.on_tool_call:
            self.on_tool_call(chunk.tool_name, chunk.content)
    
    def finalize(self) -> str:
        """
        Finalize the stream and get complete content.
        
        Returns:
            Complete content string
        """
        final_chunk = StreamChunk(content="", is_final=True)
        self._buffer.add_chunk(final_chunk)
        
        # Flush any pending content
        if self._pending_content:
            if self._in_thinking and self.on_thinking:
                self.on_thinking(self._pending_content)
            elif self.on_content:
                self.on_content(self._pending_content)
            self._pending_content = ""
        
        return self._buffer.get_content()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get streaming statistics."""
        stats = self._buffer.get_stats()
        return {
            "duration_ms": stats.duration_ms,
            "chunk_count": stats.chunk_count,
            "total_chars": stats.total_chars,
            "chars_per_second": round(stats.chars_per_second, 1),
            "thinking_chunks": stats.thinking_chunks,
            "tool_call_chunks": stats.tool_call_chunks,
        }
    
    def reset(self) -> None:
        """Reset the optimizer for a new stream."""
        self._buffer.clear()
        self._in_thinking = False
        self._pending_content = ""
        self._last_update_time = datetime.now()


class AsyncStreamProcessor:
    """
    Process streaming responses asynchronously.
    
    Useful for handling streaming in background threads.
    """
    
    def __init__(self, optimizer: StreamingOptimizer = None):
        """
        Initialize async processor.
        
        Args:
            optimizer: Streaming optimizer to use
        """
        self.optimizer = optimizer or StreamingOptimizer()
        self._queue: queue.Queue = queue.Queue()
        self._running = False
        self._thread: Optional[threading.Thread] = None
    
    def start(self) -> None:
        """Start the processor."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._process_loop, daemon=True)
        self._thread.start()
    
    def stop(self) -> None:
        """Stop the processor."""
        self._running = False
        self._queue.put(None)  # Signal to stop
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
    
    def put_chunk(self, content: str) -> None:
        """
        Add a chunk to the processing queue.
        
        Args:
            content: Content chunk
        """
        self._queue.put(content)
    
    def _process_loop(self) -> None:
        """Main processing loop."""
        while self._running:
            try:
                content = self._queue.get(timeout=0.1)
                if content is None:
                    break
                self.optimizer.process_chunk(content)
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Error processing stream: {e}")
