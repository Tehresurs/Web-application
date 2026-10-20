"""Request-local permissions; normal 8001 requests retain their current rights."""
from contextvars import ContextVar
read_only_request=ContextVar('tehresurs_read_only_request',default=False)
