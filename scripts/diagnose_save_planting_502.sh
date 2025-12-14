#!/bin/bash
# Diagnostic script for 502 error on /save_planting/

echo "=== Diagnosing 502 Bad Gateway on /save_planting/ ==="
echo ""

echo "1. Checking if Django service is running..."
sudo systemctl status smartharvester --no-pager | head -10
echo ""

echo "2. Checking if Gunicorn is listening on port 8000..."
sudo netstat -tlnp | grep 8000 || sudo ss -tlnp | grep 8000
echo ""

echo "3. Testing backend directly..."
curl -I http://127.0.0.1:8000/ 2>&1 | head -5
echo ""

echo "4. Testing /save_planting/ endpoint directly..."
curl -I http://127.0.0.1:8000/save_planting/ 2>&1 | head -5
echo ""

echo "5. Checking recent service logs for errors..."
sudo journalctl -u smartharvester -n 50 --no-pager | grep -i "error\|exception\|traceback\|502" | tail -20
echo ""

echo "6. Checking Nginx error logs..."
sudo tail -20 /var/log/nginx/error.log | grep -i "502\|save_planting\|upstream"
echo ""

echo "7. Checking Nginx configuration..."
sudo nginx -t 2>&1
echo ""

echo "8. Checking if process is running..."
ps aux | grep -E "gunicorn|python.*manage.py" | grep -v grep
echo ""

echo "=== Diagnosis Complete ==="
echo ""
echo "Common fixes:"
echo "1. If service not running: sudo systemctl start smartharvester"
echo "2. If port mismatch: Check nginx proxy_pass matches Gunicorn port"
echo "3. If backend crashed: Check logs above for Python errors"
echo "4. If timeout: Increase nginx proxy_read_timeout"

