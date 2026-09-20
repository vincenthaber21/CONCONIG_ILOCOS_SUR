#!/bin/bash
# ============================================
# Django Server for Mobile App Access
# ============================================
# This script starts Django server bound to 0.0.0.0:8000
# which allows mobile devices on the same network to connect.
#
# IMPORTANT: Make sure your mobile device and computer
# are on the same Wi-Fi network!
# ============================================

echo ""
echo "============================================"
echo "Starting Django Server for Mobile App..."
echo "============================================"
echo ""
echo "Server will be accessible at:"
echo "  - http://localhost:8000 (on this computer)"
echo "  - http://YOUR_IP:8000 (on mobile devices)"
echo ""
echo "To find your IP address:"
echo "  Mac/Linux: ifconfig or ip addr"
echo "  Windows: ipconfig"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""
echo "[INFO] Auto-reload: runserver restarts when you save Python/templates/static files."
echo "[INFO] \"Broken pipe\" in logs means a client closed early — normal, not a failure."
echo ""
echo "============================================"
echo ""

python manage.py runserver 0.0.0.0:8000

