"""
Permission Management Module
=============================

Session-level permission management for dangerous operations.
"""

from enum import Enum
from typing import Dict, Optional, Set
from dataclasses import dataclass, field
import asyncio


class PermissionType(Enum):
    """Types of operations that require permission."""
    WRITE = "write"           # File write/creation
    EDIT = "edit"             # File editing
    BASH = "bash"             # Bash command execution
    BASH_DELETE = "bash_delete"  # Bash commands with delete operations


class PermissionResponse(Enum):
    """User responses to permission requests."""
    ONCE = "once"             # Allow once
    ALWAYS = "always"         # Allow for entire session
    REJECT = "reject"         # Reject the operation


@dataclass
class PermissionRequest:
    """A permission request waiting for user response."""
    
    request_id: str
    permission_type: PermissionType
    metadata: Dict = field(default_factory=dict)
    
    # For async waiting
    future: Optional[asyncio.Future] = None


class PermissionManager:
    """
    Manages session-level permissions for dangerous operations.
    
    Features:
    - Request user permission for dangerous operations
    - Remember user choices for the session
    - Provide UI callbacks for permission dialogs
    """
    
    def __init__(self):
        """Initialize permission manager."""
        # Session-level permissions: {PermissionType: bool}
        self._session_permissions: Dict[PermissionType, bool] = {}
        
        # Pending requests: {request_id: PermissionRequest}
        self._pending_requests: Dict[str, PermissionRequest] = {}
        
        # Request counter for generating IDs
        self._request_counter = 0
        
        # Permission request callback (set by UI)
        self._permission_callback = None
    
    def set_permission_callback(self, callback):
        """
        Set callback for permission requests.
        
        Args:
            callback: Async function(request_id, permission_type, metadata) -> PermissionResponse
        """
        self._permission_callback = callback
    
    def grant_session_permission(self, permission_type: PermissionType) -> None:
        """
        Grant permission for the entire session.
        
        Args:
            permission_type: Type of permission to grant
        """
        self._session_permissions[permission_type] = True
    
    def revoke_session_permission(self, permission_type: PermissionType) -> None:
        """
        Revoke session permission.
        
        Args:
            permission_type: Type of permission to revoke
        """
        if permission_type in self._session_permissions:
            del self._session_permissions[permission_type]
    
    def has_session_permission(self, permission_type: PermissionType) -> bool:
        """
        Check if permission is granted for the session.
        
        Args:
            permission_type: Type of permission to check
            
        Returns:
            True if permission is granted
        """
        return self._session_permissions.get(permission_type, False)
    
    def get_session_permissions(self) -> Dict[PermissionType, bool]:
        """
        Get all session permissions.
        
        Returns:
            Dictionary of permission types and their status
        """
        return self._session_permissions.copy()
    
    def clear_session_permissions(self) -> None:
        """Clear all session permissions."""
        self._session_permissions.clear()
    
    async def request_permission(
        self, 
        permission_type: PermissionType,
        metadata: Dict = None
    ) -> PermissionResponse:
        """
        Request permission from user.
        
        Args:
            permission_type: Type of permission needed
            metadata: Additional context for the request (file_path, command, diff, etc.)
            
        Returns:
            PermissionResponse from user
            
        Raises:
            RuntimeError: If no permission callback is set
        """
        # Check if already granted for session
        if self.has_session_permission(permission_type):
            return PermissionResponse.ONCE  # Already granted
        
        # No callback set - default to reject for safety
        if self._permission_callback is None:
            return PermissionResponse.REJECT
        
        # Generate request ID
        self._request_counter += 1
        request_id = f"perm_{self._request_counter}"
        
        # Create request
        future = asyncio.Future()
        request = PermissionRequest(
            request_id=request_id,
            permission_type=permission_type,
            metadata=metadata or {},
            future=future
        )
        self._pending_requests[request_id] = request
        
        # Call UI callback
        try:
            response = await self._permission_callback(
                request_id, 
                permission_type, 
                metadata or {}
            )
            
            # Handle response
            if response == PermissionResponse.ALWAYS:
                self.grant_session_permission(permission_type)
            
            return response
            
        finally:
            # Clean up
            if request_id in self._pending_requests:
                del self._pending_requests[request_id]
    
    def respond_to_request(self, request_id: str, response: PermissionResponse) -> bool:
        """
        Respond to a pending permission request.
        
        Args:
            request_id: ID of the request
            response: User's response
            
        Returns:
            True if request was found and handled
        """
        if request_id not in self._pending_requests:
            return False
        
        request = self._pending_requests[request_id]
        
        # Handle ALWAYS response
        if response == PermissionResponse.ALWAYS:
            self.grant_session_permission(request.permission_type)
        
        # Set future result
        if request.future and not request.future.done():
            request.future.set_result(response)
        
        # Clean up
        del self._pending_requests[request_id]
        return True
    
    def get_pending_requests(self) -> Dict[str, PermissionRequest]:
        """
        Get all pending permission requests.
        
        Returns:
            Dictionary of request IDs to PermissionRequest objects
        """
        return self._pending_requests.copy()


# Global permission manager instance
_permission_manager = PermissionManager()


def get_permission_manager() -> PermissionManager:
    """Get the global permission manager instance."""
    return _permission_manager
