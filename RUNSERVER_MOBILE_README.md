# Running Django Server for Mobile App Access

## ⚠️ IMPORTANT: How `runserver` Affects Mobile App

**Yes, `python manage.py runserver` DOES affect the mobile app!**

### The Problem

By default, Django's `runserver` command binds to `127.0.0.1` (localhost), which means:
- ✅ Works on the same computer
- ❌ **Does NOT work for mobile devices** on the network

### The Solution

You must bind the server to `0.0.0.0` to allow mobile devices to connect:

```bash
# ✅ CORRECT - Mobile devices can connect
python manage.py runserver 0.0.0.0:8000

# ❌ WRONG - Only works on same computer
python manage.py runserver
```

## Quick Start

### Windows
Double-click `runserver_mobile.bat` or run:
```cmd
runserver_mobile.bat
```

### Mac/Linux
```bash
chmod +x runserver_mobile.sh
./runserver_mobile.sh
```

## How to Verify

When you start the server, check the output:

**❌ Wrong (won't work for mobile):**
```
Starting development server at http://127.0.0.1:8000/
```

**✅ Correct (will work for mobile):**
```
Starting development server at http://0.0.0.0:8000/
```

## Network Requirements

1. **Same Wi-Fi Network**: Your computer and mobile device must be on the same Wi-Fi network
2. **Find Your IP**: 
   - Windows: `ipconfig` (look for IPv4 Address)
   - Mac/Linux: `ifconfig` or `ip addr`
3. **Update Mobile Config**: Set `mobile_app/config.js` to use your computer's IP:
   ```javascript
   const LOCAL_IP = 'http://YOUR_IP:8000';
   // Example: 'http://192.168.1.100:8000'
   ```

## Firewall Settings

If mobile devices still can't connect:

### Windows
1. Open Windows Defender Firewall
2. Allow Python through firewall
3. Or temporarily disable firewall for testing

### Mac
1. System Preferences > Security & Privacy > Firewall
2. Allow Python/Django connections

### Linux
```bash
# Allow port 8000 through firewall
sudo ufw allow 8000
```

## Testing Connection

1. Start server: `python manage.py runserver 0.0.0.0:8000`
2. Open mobile browser and go to: `http://YOUR_IP:8000/admin/`
3. If you see the Django admin login, connection works!
4. Now the mobile app should be able to connect

## Common Issues

### Issue: "Cannot connect to server"
- ✅ Check server is running with `0.0.0.0:8000`
- ✅ Verify both devices on same Wi-Fi
- ✅ Check firewall settings
- ✅ Verify IP address in `config.js`

### Issue: "Connection timeout"
- ✅ Server might be bound to `127.0.0.1` instead of `0.0.0.0`
- ✅ Check server console output
- ✅ Restart server with correct binding

## Summary

| Command | Accessible From | Mobile App Works? |
|---------|----------------|-------------------|
| `python manage.py runserver` | Same computer only | ❌ No |
| `python manage.py runserver 0.0.0.0:8000` | Same network | ✅ Yes |

**Always use `0.0.0.0:8000` for mobile app development!**

