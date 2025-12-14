#!/bin/bash
# Diagnostic script for 502 Bad Gateway errors
# Usage: sudo bash scripts/diagnose_502.sh

echo "=========================================="
echo "502 Bad Gateway Diagnostic Script"
echo "=========================================="
echo ""

# Check 1: Is the service running?
echo "1. Checking if smartharvester service is running..."
if systemctl is-active --quiet smartharvester; then
    echo "   ✅ Service is running"
    systemctl status smartharvester --no-pager -l | head -5
else
    echo "   ❌ Service is NOT running"
    echo "   Fix: sudo systemctl start smartharvester"
fi
echo ""

# Check 2: Is Gunicorn process running?
echo "2. Checking if Gunicorn process is running..."
GUNICORN_PID=$(pgrep -f gunicorn)
if [ -n "$GUNICORN_PID" ]; then
    echo "   ✅ Gunicorn is running (PID: $GUNICORN_PID)"
    ps aux | grep gunicorn | grep -v grep | head -2
else
    echo "   ❌ Gunicorn is NOT running"
    echo "   Fix: sudo systemctl start smartharvester"
fi
echo ""

# Check 3: Is Gunicorn listening on port 8000?
echo "3. Checking if port 8000 is listening..."
if netstat -tlnp 2>/dev/null | grep -q ":8000"; then
    echo "   ✅ Port 8000 is listening"
    netstat -tlnp 2>/dev/null | grep ":8000"
elif ss -tlnp 2>/dev/null | grep -q ":8000"; then
    echo "   ✅ Port 8000 is listening"
    ss -tlnp 2>/dev/null | grep ":8000"
else
    echo "   ❌ Port 8000 is NOT listening"
    echo "   This means Gunicorn is not running or bound to wrong port"
fi
echo ""

# Check 4: Can we reach the backend directly?
echo "4. Testing backend connection..."
if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/ | grep -q "200\|301\|302"; then
    echo "   ✅ Backend responds successfully"
    curl -s -I http://127.0.0.1:8000/ | head -3
else
    echo "   ❌ Backend does NOT respond"
    echo "   Response:"
    curl -s -I http://127.0.0.1:8000/ | head -5
    echo "   This means Gunicorn is not running or not accessible"
fi
echo ""

# Check 5: Is nginx running?
echo "5. Checking nginx status..."
if systemctl is-active --quiet nginx; then
    echo "   ✅ Nginx is running"
else
    echo "   ❌ Nginx is NOT running"
    echo "   Fix: sudo systemctl start nginx"
fi
echo ""

# Check 6: Nginx configuration
echo "6. Checking nginx configuration..."
if nginx -t 2>&1 | grep -q "successful"; then
    echo "   ✅ Nginx configuration is valid"
else
    echo "   ❌ Nginx configuration has errors:"
    nginx -t
fi
echo ""

# Check 7: Nginx proxy_pass configuration
echo "7. Checking nginx proxy_pass configuration..."
PROXY_PASS=$(grep -r "proxy_pass" /etc/nginx/sites-enabled/ 2>/dev/null | grep -v "#" | head -1)
if [ -n "$PROXY_PASS" ]; then
    echo "   Found proxy_pass configuration:"
    echo "   $PROXY_PASS"
    if echo "$PROXY_PASS" | grep -q "127.0.0.1:8000\|localhost:8000"; then
        echo "   ✅ Points to correct backend (port 8000)"
    else
        echo "   ⚠️  May not point to correct backend"
    fi
else
    echo "   ❌ No proxy_pass found in nginx configuration"
    echo "   Nginx needs to proxy to http://127.0.0.1:8000"
fi
echo ""

# Check 8: Recent nginx errors
echo "8. Recent nginx error log entries..."
if [ -f /var/log/nginx/error.log ]; then
    echo "   Last 5 error log entries:"
    tail -5 /var/log/nginx/error.log 2>/dev/null | sed 's/^/   /'
else
    echo "   ⚠️  Error log not found"
fi
echo ""

# Check 9: Recent service errors
echo "9. Recent smartharvester service errors..."
journalctl -u smartharvester -n 10 --no-pager 2>/dev/null | grep -i "error\|fail\|exception" | tail -5 | sed 's/^/   /' || echo "   No recent errors found"
echo ""

# Summary and recommendations
echo "=========================================="
echo "Summary & Recommendations"
echo "=========================================="
echo ""

if ! systemctl is-active --quiet smartharvester; then
    echo "🔴 CRITICAL: Service is not running"
    echo "   Run: sudo systemctl start smartharvester"
    echo ""
fi

if ! netstat -tlnp 2>/dev/null | grep -q ":8000" && ! ss -tlnp 2>/dev/null | grep -q ":8000"; then
    echo "🔴 CRITICAL: Port 8000 is not listening"
    echo "   This means Gunicorn is not running"
    echo "   Run: sudo systemctl start smartharvester"
    echo ""
fi

if ! curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/ | grep -q "200\|301\|302"; then
    echo "🔴 CRITICAL: Backend is not responding"
    echo "   Check service logs: sudo journalctl -u smartharvester -n 50"
    echo ""
fi

echo "Next steps:"
echo "1. If service not running: sudo systemctl start smartharvester"
echo "2. Check service logs: sudo journalctl -u smartharvester -f"
echo "3. Check nginx logs: sudo tail -f /var/log/nginx/error.log"
echo "4. Verify nginx config: sudo cat /etc/nginx/sites-enabled/default"
echo ""

