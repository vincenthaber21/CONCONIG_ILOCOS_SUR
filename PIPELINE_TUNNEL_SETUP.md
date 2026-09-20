# Pipeline Tunnel Setup for Mobile APK Users

## Overview

This document describes the pipeline tunnel implementation that optimizes connections for mobile APK users, preventing "Broken pipe" errors and ensuring fast, stable connections to the server.

## Problem Solved

**Issue:** Mobile app users (APK) were experiencing "Broken pipe" errors:
```
[17/Dec/2025 15:26:12,086] - Broken pipe from ('172.16.35.74', 48482)
```

**Root Cause:** 
- Mobile clients disconnect before the server finishes sending responses
- No graceful handling of client disconnections
- Missing connection keep-alive optimizations
- No connection pooling for mobile API endpoints

## Solution: Pipeline Tunnel

The pipeline tunnel consists of three layers:

### 1. WSGI-Level Error Handling (`coop_kiosk/wsgi.py`)
- Catches broken pipe errors at the lowest level
- Prevents error propagation to logs
- Returns empty responses for disconnected clients
- Logs disconnections at debug level (not error level)

### 2. Middleware Layer (`mobile_api/middleware.py`)

#### BrokenPipeHandlerMiddleware
- Handles broken pipe errors gracefully
- Only applies to `/api/mobile/` endpoints
- Wraps streaming responses to catch disconnections
- Suppresses error logs for normal client disconnects

#### ConnectionOptimizationMiddleware
- Adds performance timing headers (`X-Response-Time`)
- Optimizes cache control headers
- Note: Connection keep-alive is automatically handled by the HTTP server
  (WSGI apps cannot set hop-by-hop headers like `Connection`)

### 3. Django Settings (`coop_kiosk/settings.py`)
- Connection optimization settings
- Logging configuration to suppress broken pipe errors
- Upload size limits optimized for mobile
- Keep-alive settings documented

## Features

### ✅ Broken Pipe Error Suppression
- Broken pipe errors are caught and handled gracefully
- No more error logs for normal client disconnections
- Server continues running smoothly

### ✅ Connection Keep-Alive
- HTTP keep-alive is automatically handled by the HTTP server
- The server manages keep-alive based on HTTP version and client capabilities
- Mobile app sends keep-alive in request headers (client-side)
- Reduces connection overhead significantly

### ✅ Performance Optimization
- Database queries optimized with `select_related()` and `prefetch_related()`
- Response time tracking via `X-Response-Time` header
- Faster response times for mobile users

### ✅ Fast Response Times
- Optimized database queries reduce query count
- Connection pooling reduces connection setup time
- Keep-alive eliminates TCP handshake overhead

## Configuration

### Middleware Order
The middleware is configured in `settings.py` in this order:
1. `ConnectionOptimizationMiddleware` - Early in the chain to add headers
2. `BrokenPipeHandlerMiddleware` - Late in the chain to catch errors

### Logging
Broken pipe errors are logged at DEBUG level (not ERROR) to reduce log noise:
```python
LOGGING = {
    'loggers': {
        'mobile_api.middleware': {
            'level': 'DEBUG' if DEBUG else 'INFO',
        },
    },
}
```

## How It Works

### Request Flow
1. **Client Request** → Mobile app sends request with keep-alive headers to `/api/mobile/*`
2. **Connection Optimization** → Middleware adds cache control and timing headers
3. **Request Processing** → Django processes the request
4. **Response** → Response sent (HTTP server handles keep-alive automatically)
5. **Client Disconnect** → If client disconnects early, error is caught gracefully

### Error Handling Flow
1. **Broken Pipe Occurs** → Client disconnects before response complete
2. **WSGI Catches Error** → `wsgi.py` wrapper catches the exception
3. **Middleware Handles** → `BrokenPipeHandlerMiddleware` processes it
4. **Graceful Exit** → Error logged at debug level, no crash

## Benefits

### For Mobile Users
- ✅ Faster connection times (keep-alive)
- ✅ More stable connections
- ✅ Reduced connection errors
- ✅ Better performance on slow networks

### For Server
- ✅ No error logs for normal disconnects
- ✅ Reduced connection overhead
- ✅ Better resource utilization
- ✅ Cleaner logs

## Testing

### Test Connection
Use the health check endpoint to test:
```bash
curl http://your-server:8000/api/mobile/health/
```

### Monitor Performance
Check response time header:
```bash
curl -I http://your-server:8000/api/mobile/health/
# Look for: X-Response-Time: XX.XXms
```

### Test Broken Pipe Handling
1. Start a request from mobile app
2. Disconnect network immediately
3. Check server logs - should see debug message, not error

## Troubleshooting

### Still Seeing Broken Pipe Errors?
1. **Check Middleware Order** - Ensure middleware is in correct order in `settings.py`
2. **Check Log Level** - Verify logging is set to DEBUG/INFO
3. **Restart Server** - Restart Django server after changes

### Connection Still Slow?
1. **Check Network** - Verify mobile device and server on same network
2. **Check Firewall** - Ensure firewall allows connections
3. **Check HTTP Server** - In production, configure your HTTP server (nginx/Apache) for keep-alive

### Performance Issues?
1. **Check Database Queries** - Use Django Debug Toolbar to check query count
2. **Check Response Times** - Monitor `X-Response-Time` header
3. **Check Server Load** - Monitor server resources

## Mobile App Configuration

The mobile app (`mobile_app/services/api.js`) is already configured with:
- Keep-alive headers in requests
- Connection monitoring
- Automatic retry logic
- Connection quality tracking

No changes needed in the mobile app - the pipeline tunnel works automatically!

## Production Considerations

### For Production Deployment
1. **HTTPS Required** - Use HTTPS in production
2. **Secure Cookies** - Set `SESSION_COOKIE_SECURE = True`
3. **Logging** - Set log level to INFO (not DEBUG)
4. **Monitoring** - Monitor connection metrics

### Recommended Settings
```python
# settings.py (production)
DEBUG = False
SESSION_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
LOGGING['loggers']['mobile_api.middleware']['level'] = 'INFO'
```

## Summary

The pipeline tunnel provides:
- ✅ Graceful broken pipe error handling
- ✅ HTTP keep-alive for persistent connections
- ✅ Optimized database queries
- ✅ Performance monitoring
- ✅ Clean, readable logs

Mobile APK users now have fast, stable connections to the server with no broken pipe errors cluttering the logs!

