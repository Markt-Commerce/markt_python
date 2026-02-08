# 🍪 Cookie & CORS Configuration Guide

## Overview
Fixed datetime serialization bug in `get_room_messages` and configured session cookies for cross-origin testing.

---

## 🚀 Production Settings

### For Production (Same-Origin React App)
```ini
# settings.ini or environment variables
SESSION_COOKIE_SAMESITE=Lax
SESSION_COOKIE_SECURE=True
ALLOWED_ORIGINS=https://markt.com,https://www.markt.com
```

**Explanation:**
- `SameSite=Lax`: Default secure setting. Cookies sent with top-level navigation and same-site requests.
- `Secure=True`: Cookies only sent over HTTPS (required for production).
- `ALLOWED_ORIGINS`: Your production React app domain(s).

### For Cross-Origin Testing (localhost → test.api.marktcommerce.com)
```ini
# settings.ini or environment variables
SESSION_COOKIE_SAMESITE=None
SESSION_COOKIE_SECURE=True
ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

**Explanation:**
- `SameSite=None`: Required for cross-origin cookies (localhost to test server).
- `Secure=True`: Must be True when SameSite=None (HTTPS required).
- `ALLOWED_ORIGINS`: Test client origins.

---

## 🔧 What I Fixed

### 1. DateTime Serialization Bug
**File:** `app/chats/services.py` (lines 250-252)

**Before:**
```python
"read_at": message.read_at.isoformat() if message.read_at else None,
"created_at": message.created_at.isoformat(),
```

**After:**
```python
# Return datetime objects; schema will serialize
"read_at": message.read_at if message.read_at else None,
"created_at": message.created_at,
```

**Why:** Marshmallow DateTime fields expect Python datetime objects, not strings. The schema handles `.isoformat()` automatically.

### 2. CORS & Credentials
**Files:** `main/setup.py`, `main/extensions.py`, `authenticated_test_client.html`

- Updated CORS to use `settings.ALLOWED_ORIGINS` (not `*`)
- Added `withCredentials: true` to Socket.IO client
- All fetch calls use `credentials: 'include'`

---

## 🐛 Known Issue: Incognito Tab Cookie Problem

**Symptom:**
- Seller (main tab): ✅ Login works, rooms load
- Buyer (incognito tab): ❌ "Unauthorized" on API calls

**Root Cause:**
Incognito mode blocks third-party cookies by default. When you:
1. Open http://localhost:3000 (test client)
2. Login to https://test.api.marktcommerce.com
3. Browser sees this as "third-party cookie" (different origin)
4. Incognito blocks it

**Solutions:**

### Option A: Use Two Regular Tabs (Recommended for Testing)
```
Tab 1: http://localhost:3000 (login as seller)
Tab 2: http://localhost:3000 in new window (login as buyer)
```
Both will share cookies properly.

### Option B: Allow Third-Party Cookies in Incognito
Chrome: Settings → Privacy → Allow third-party cookies temporarily

### Option C: Use Different Browsers
```
Chrome: Seller
Firefox: Buyer
```

### Option D: Deploy Test Client to Same Domain (Production Approach)
Serve test client from: `https://test.api.marktcommerce.com/test-client.html`
- No cross-origin issues
- Cookies work automatically
- Set `SESSION_COOKIE_SAMESITE=Lax`

---

## 📋 Testing Checklist

### Server Configuration
- [x] `SESSION_COOKIE_SAMESITE=None` (for cross-origin testing)
- [x] `SESSION_COOKIE_SECURE=True` (required with SameSite=None)
- [x] `ALLOWED_ORIGINS` includes `http://localhost:3000`
- [x] CORS configured in `main/setup.py` and `main/extensions.py`

### Client Configuration
- [x] `credentials: 'include'` in all fetch calls
- [x] `withCredentials: true` in Socket.IO options
- [x] Connecting to `https://test.api.marktcommerce.com` (HTTPS required)

### Testing Flow
1. **Restart server** after config changes
2. Open http://localhost:3000 in **two regular tabs** (not incognito)
3. Tab 1: Login as seller → Load rooms ✅
4. Tab 2: Login as buyer → Load rooms ✅
5. Select same room in both tabs
6. Send messages and verify real-time sync

---

## 🔒 Security Notes

### Production Checklist
- [ ] Change `SECRET_KEY` to strong random value
- [ ] Set `SESSION_COOKIE_SAMESITE=Lax` (default secure)
- [ ] Set `SESSION_COOKIE_SECURE=True` (HTTPS only)
- [ ] Restrict `ALLOWED_ORIGINS` to production domains only
- [ ] Never use `*` for CORS origins in production
- [ ] Enable HTTPS on all domains

### Session Security
```python
# Add to main/config.py for production
self.SESSION_COOKIE_HTTPONLY = True  # Prevent XSS
self.SESSION_COOKIE_DOMAIN = config("SESSION_COOKIE_DOMAIN", default=None)
self.PERMANENT_SESSION_LIFETIME = 3600  # 1 hour
```

---

## 🎯 Quick Reference

| Environment | SameSite | Secure | Origins | Use Case |
|------------|----------|--------|---------|----------|
| **Development** | Lax | False | localhost:3000 | Local testing |
| **Testing (cross-origin)** | None | True | localhost:3000 | Test client → test server |
| **Production** | Lax | True | markt.com | React app on same domain |
| **Production (multi-domain)** | None | True | app.markt.com,api.markt.com | React app on subdomain |

---

## 📞 Support

If you still see "Unauthorized":
1. Check browser console for cookie warnings
2. Verify `Set-Cookie` headers in Network tab
3. Confirm server restarted after config changes
4. Try two regular tabs instead of incognito
5. Check server logs for CORS errors

