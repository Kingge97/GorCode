"""
Response Cache
==============

Caching for model responses and tool results.
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import json
import hashlib
import threading


@dataclass
class CacheEntry:
    """A single cache entry."""
    
    key: str
    value: Any
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    hit_count: int = 0
    size_bytes: int = 0
    
    def is_expired(self) -> bool:
        """Check if entry is expired."""
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "key": self.key,
            "value": self.value,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "hit_count": self.hit_count,
            "size_bytes": self.size_bytes,
        }


class ResponseCache:
    """
    Cache for model responses and tool results.
    
    Features:
    - LRU eviction
    - TTL-based expiration
    - Size limits
    - Thread-safe operations
    """
    
    DEFAULT_MAX_ENTRIES = 100
    DEFAULT_MAX_SIZE_MB = 50
    DEFAULT_TTL_SECONDS = 3600  # 1 hour
    
    def __init__(
        self,
        max_entries: int = None,
        max_size_mb: float = None,
        default_ttl: int = None,
    ):
        """
        Initialize response cache.
        
        Args:
            max_entries: Maximum number of entries
            max_size_mb: Maximum cache size in MB
            default_ttl: Default TTL in seconds
        """
        self.max_entries = max_entries or self.DEFAULT_MAX_ENTRIES
        self.max_size_mb = max_size_mb or self.DEFAULT_MAX_SIZE_MB
        self.default_ttl = default_ttl or self.DEFAULT_TTL_SECONDS
        
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = threading.Lock()
        self._total_size = 0
    
    def _generate_key(self, *args, **kwargs) -> str:
        """Generate a cache key from arguments."""
        # Create a string representation
        key_data = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True, default=str)
        # Hash it
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def _estimate_size(self, value: Any) -> int:
        """Estimate size of a value in bytes."""
        try:
            return len(json.dumps(value, default=str).encode())
        except Exception:
            return 0
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get a value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None
        """
        with self._lock:
            entry = self._cache.get(key)
            
            if entry is None:
                return None
            
            if entry.is_expired():
                self._remove_entry(key)
                return None
            
            entry.hit_count += 1
            return entry.value
    
    def set(
        self,
        key: str,
        value: Any,
        ttl: int = None,
    ) -> None:
        """
        Set a value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds
        """
        with self._lock:
            # Calculate size
            size = self._estimate_size(value)
            
            # Check if we need to evict
            self._evict_if_needed(size)
            
            # Calculate expiry
            ttl = ttl or self.default_ttl
            expires_at = datetime.now() + timedelta(seconds=ttl) if ttl > 0 else None
            
            # Remove old entry if exists
            if key in self._cache:
                self._remove_entry(key)
            
            # Add new entry
            entry = CacheEntry(
                key=key,
                value=value,
                expires_at=expires_at,
                size_bytes=size,
            )
            
            self._cache[key] = entry
            self._total_size += size
    
    def delete(self, key: str) -> bool:
        """
        Delete a value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            True if deleted, False if not found
        """
        with self._lock:
            if key in self._cache:
                self._remove_entry(key)
                return True
            return False
    
    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()
            self._total_size = 0
    
    def _remove_entry(self, key: str) -> None:
        """Remove an entry (assumes lock is held)."""
        entry = self._cache.pop(key, None)
        if entry:
            self._total_size -= entry.size_bytes
    
    def _evict_if_needed(self, new_size: int) -> None:
        """Evict entries if needed (assumes lock is held)."""
        max_size_bytes = self.max_size_mb * 1024 * 1024
        
        # Evict by count
        while len(self._cache) >= self.max_entries:
            self._evict_lru()
        
        # Evict by size
        while self._total_size + new_size > max_size_bytes:
            if not self._evict_lru():
                break
    
    def _evict_lru(self) -> bool:
        """Evict least recently used entry."""
        if not self._cache:
            return False
        
        # Find entry with lowest hit count and oldest creation
        lru_key = min(
            self._cache.keys(),
            key=lambda k: (self._cache[k].hit_count, self._cache[k].created_at)
        )
        
        self._remove_entry(lru_key)
        return True
    
    def cache_response(
        self,
        messages: List[Dict[str, Any]],
        response: Any,
        model: str = "default",
        ttl: int = None,
    ) -> str:
        """
        Cache a model response.
        
        Args:
            messages: Messages that generated the response
            response: Response to cache
            model: Model name
            ttl: Time to live
            
        Returns:
            Cache key
        """
        key = self._generate_key(model, messages)
        self.set(key, response, ttl)
        return key
    
    def get_cached_response(
        self,
        messages: List[Dict[str, Any]],
        model: str = "default",
    ) -> Optional[Any]:
        """
        Get a cached model response.
        
        Args:
            messages: Messages to look up
            model: Model name
            
        Returns:
            Cached response or None
        """
        key = self._generate_key(model, messages)
        return self.get(key)
    
    def cache_tool_result(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        result: Any,
        ttl: int = None,
    ) -> str:
        """
        Cache a tool result.
        
        Args:
            tool_name: Tool name
            arguments: Tool arguments
            result: Tool result
            ttl: Time to live
            
        Returns:
            Cache key
        """
        key = self._generate_key(tool_name, arguments)
        self.set(key, result, ttl)
        return key
    
    def get_cached_tool_result(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Optional[Any]:
        """
        Get a cached tool result.
        
        Args:
            tool_name: Tool name
            arguments: Tool arguments
            
        Returns:
            Cached result or None
        """
        key = self._generate_key(tool_name, arguments)
        return self.get(key)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Statistics dictionary
        """
        with self._lock:
            total_hits = sum(e.hit_count for e in self._cache.values())
            
            return {
                "entries": len(self._cache),
                "max_entries": self.max_entries,
                "size_bytes": self._total_size,
                "size_mb": round(self._total_size / (1024 * 1024), 2),
                "max_size_mb": self.max_size_mb,
                "total_hits": total_hits,
                "usage_percent": round(len(self._cache) / self.max_entries * 100, 1),
            }
    
    def cleanup_expired(self) -> int:
        """
        Remove expired entries.
        
        Returns:
            Number of entries removed
        """
        with self._lock:
            expired_keys = [
                k for k, v in self._cache.items()
                if v.is_expired()
            ]
            
            for key in expired_keys:
                self._remove_entry(key)
            
            return len(expired_keys)
