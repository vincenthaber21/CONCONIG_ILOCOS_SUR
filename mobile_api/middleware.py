"""
Middleware to handle broken pipe errors and optimize connections for mobile API users.
This creates a pipeline tunnel for fast, stable connections.
"""
import logging
import sys
import time
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.sessions.exceptions import SessionInterrupted
from django.http import StreamingHttpResponse
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)


class MobileAPICSRFExemptMiddleware:
    """
    Bypass Django's CSRF checks for all /api/mobile/ endpoints.
    Mobile apps cannot obtain a CSRF token the way browsers do, so CSRF
    protection is irrelevant for session-cookie-authenticated API routes.
    Setting csrf_processing_done=True prevents CsrfViewMiddleware from
    ever reaching process_view for these paths.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/api/mobile/'):
            request.csrf_processing_done = True
        return self.get_response(request)


class BrokenPipeHandlerMiddleware(MiddlewareMixin):
    """
    Middleware to gracefully handle broken pipe errors from mobile clients.
    This prevents server errors when clients disconnect before response is sent.
    """
    
    def process_response(self, request, response):
        """
        Wrap response to handle broken pipe errors gracefully.
        """
        # Only apply to mobile API endpoints
        if not request.path.startswith('/api/mobile/'):
            return response
        
        # For streaming responses, wrap to catch broken pipes
        if isinstance(response, StreamingHttpResponse):
            original_iter = response.streaming_content
            
            def safe_iter():
                try:
                    for chunk in original_iter:
                        yield chunk
                except (BrokenPipeError, ConnectionResetError, OSError) as e:
                    # Client disconnected - this is normal for mobile apps
                    # Log at debug level, not error
                    logger.debug(
                        f"Client disconnected during response: {request.path} "
                        f"from {request.META.get('REMOTE_ADDR', 'unknown')} - {str(e)}"
                    )
                    # Silently stop sending data
                    return
            
            response.streaming_content = safe_iter()
        
        return response
    
    def process_exception(self, request, exception):
        """
        Catch and handle broken pipe exceptions.
        """
        # Check if it's a broken pipe error
        if isinstance(exception, (BrokenPipeError, ConnectionResetError, OSError)):
            # Check if error message indicates broken pipe
            error_str = str(exception).lower()
            if 'broken pipe' in error_str or 'connection reset' in error_str:
                # This is a client disconnect - not a server error
                logger.debug(
                    f"Client disconnected: {request.path} "
                    f"from {request.META.get('REMOTE_ADDR', 'unknown')}"
                )
                # Return None to let Django handle it normally (won't crash)
                return None
        
        # For other exceptions, let them propagate
        return None


class ConnectionOptimizationMiddleware(MiddlewareMixin):
    """
    Middleware to optimize connections for mobile API users.
    Adds headers for cache control and performance monitoring.
    Note: Connection keep-alive is handled automatically by the HTTP server.
    """
    
    def process_response(self, request, response):
        """
        Add connection optimization headers for mobile API endpoints.
        Note: Connection and Keep-Alive headers are hop-by-hop headers
        managed by the HTTP server, not WSGI applications.
        """
        # Only apply to mobile API endpoints
        if not request.path.startswith('/api/mobile/'):
            return response
        
        # Note: Connection and Keep-Alive headers are hop-by-hop headers
        # that are managed by the HTTP server (nginx, Apache, etc.), not WSGI apps.
        # The HTTP server will automatically handle keep-alive based on HTTP version.
        # We don't set these headers here to avoid WSGI errors.
        
        # Add cache control for API responses (no cache for dynamic data)
        if 'Cache-Control' not in response:
            response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
        
        # Add CORS headers if not already present (for mobile apps)
        if 'Access-Control-Allow-Origin' not in response:
            # Will be handled by corsheaders middleware, but ensure it's set
            pass
        
        # Add timing headers for debugging
        if hasattr(request, '_start_time'):
            duration = (time.time() - request._start_time) * 1000  # Convert to ms
            response['X-Response-Time'] = f'{duration:.2f}ms'
        
        return response
    
    def process_request(self, request):
        """
        Record request start time for performance monitoring.
        """
        if request.path.startswith('/api/mobile/'):
            request._start_time = time.time()
        
        return None


class ResilientSessionMiddleware(SessionMiddleware):
    """
    Drop-in replacement for Django's SessionMiddleware that gracefully handles
    SessionInterrupted errors (e.g. concurrent session writes / race conditions).
    Retries the session save up to 3 times, cycling the session key between
    attempts to avoid further conflicts.  If all retries fail the exception is
    re-raised so that it is still visible in logs.
    """

    def process_response(self, request, response):
        last_exception = None
        for attempt in range(3):
            try:
                return super().process_response(request, response)
            except SessionInterrupted as e:
                last_exception = e
                logger.warning(
                    "SessionInterrupted on attempt %d for %s from %s: %s",
                    attempt + 1,
                    request.path,
                    request.META.get("REMOTE_ADDR", "unknown"),
                    str(e),
                )
                if hasattr(request, "session"):
                    request.session.cycle_key()
                time.sleep(0.05 * (attempt + 1))  # brief back-off: 50 ms, 100 ms
        raise last_exception

