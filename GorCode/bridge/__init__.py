"""
Bridge Module
=============

Protocol and gateway layer for GorCode frontend-backend decoupling.
"""

from .protocol import (
    PROTOCOL_VERSION,
    PROTOCOL_DEFINITIONS,
    make_request,
    make_response,
    make_event,
)
from .inprocess import InProcessTransport, FrontendClient, InProcessRuntime, create_inprocess_client

__all__ = [
    "PROTOCOL_VERSION",
    "PROTOCOL_DEFINITIONS",
    "make_request",
    "make_response",
    "make_event",
    "InProcessTransport",
    "FrontendClient",
    "InProcessRuntime",
    "create_inprocess_client",
]
