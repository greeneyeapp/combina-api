from fastapi import APIRouter, Depends, Body, Request, HTTPException
from firebase_admin import firestore
from pydantic import BaseModel
from datetime import datetime, date
from typing import Tuple
import hmac
import hashlib
import os

from core.security import get_current_user_id, require_authenticated_user
from schemas import ProfileInit

# Users router (authentication gerektirir)
router = APIRouter(
    prefix="/api/users",
    tags=["users"]
    # dependencies=[Depends(require_authenticated_user)] kaldırıldı - endpoint bazında kontrol edilecek
)

# RevenueCat webhook için ayrı router (authentication gerektirmez)
webhook_router = APIRouter(
    prefix="/api",
    tags=["webhooks"]
)

db = firestore.client()

# YENİ: Anonymous ve authenticated kullanıcılar için birleşik profil endpoint'i
@router.get("/profile")  # Ana router kullanıyoruz: /api/users/profile
async def get_user_profile_universal(
    request: Request,
    user_data: Tuple[str, bool] = Depends(get_current_user_id)
):
    """Hem anonymous hem authenticated kullanıcılar için profil bilgileri"""
    user_id, is_anonymous = user_data
    
    if is_anonymous:
        # Anonymous kullanıcı için in-memory cache'den bilgiler döndür
        from routers.outfits import get_anonymous_user_usage, PLAN_LIMITS
        
        usage_data = get_anonymous_user_usage(user_id)
        daily_limit = PLAN_LIMITS.get("anonymous", 1)
        current_usage = usage_data.get("count", 0)
        remaining = max(0, daily_limit - current_usage)
        percentage_used = (current_usage / daily_limit) * 100 if daily_limit > 0 else 0
        
        print(f"✅ Serving anonymous profile for: {user_id[:16]}...")
        
        return {
            "user_id": user_id,
            "type": "anonymous",
            "plan": "anonymous",
            "fullname": None,
            "email": None,
            "gender": "unisex",  # Default for anonymous
            "usage": {
                "daily_limit": daily_limit,
                "rewarded_count": 0,
                "current_usage": current_usage,
                "remaining": remaining,
                "percentage_used": round(percentage_used, 2),
                "date": str(date.today())
            },
            "created_at": None,
            "isAnonymous": True,
            "profile_complete": False
        }
    
    else:
        # Authenticated kullanıcı (Firestore'dan veri çek)
        print(f"✅ Serving authenticated profile for: {user_id[:16]}...")
        
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            raise HTTPException(status_code=404, detail="User profile not found.")
        
        user_data_dict = user_doc.to_dict()
        today_str = str(date.today())
        
        usage_data = user_data_dict.get("usage", {})
        
        if usage_data.get("date") != today_str:
            print(f"🔄 Day has changed. Resetting usage for user {user_id[:8]}.")
            usage_data = {"count": 0, "date": today_str, "rewarded_count": 0}
            user_ref.update({"usage": usage_data})
        
        plan = user_data_dict.get("plan", "free")
        
        plan_limits = {"free": 2, "premium": None}
        daily_limit = plan_limits.get(plan, 2)
        
        current_usage = usage_data.get("count", 0)
        rewarded_count = usage_data.get("rewarded_count", 0)
        
        if plan == "premium":
            effective_limit = None
            remaining = "unlimited"
            percentage_used = 0
        else:
            effective_limit = daily_limit + rewarded_count
            remaining = max(0, effective_limit - current_usage)
            percentage_used = round((current_usage / effective_limit) * 100, 1) if effective_limit > 0 else 0
        
        return {
            "user_id": user_id,
            "fullname": user_data_dict.get("fullname"),
            "email": user_data_dict.get("email"),
            "gender": user_data_dict.get("gender"),
            "plan": plan,
            "usage": {
                "daily_limit": "unlimited" if daily_limit is None else daily_limit,
                "rewarded_count": rewarded_count,
                "current_usage": current_usage,
                "remaining": remaining,
                "percentage_used": percentage_used,
                "date": today_str
            },
            "created_at": user_data_dict.get("createdAt"),
            "is_anonymous": False,       # ← Bu field'ı ekleyin
            "isAnonymous": False,        # ← Bu field'ı da ekleyin (client compatibility için)
            "profile_complete": bool(user_data_dict.get("fullname") and user_data_dict.get("gender"))
        }

@router.post("/init-profile")
async def create_user_profile(
    profile: ProfileInit, 
    user_id: str = Depends(require_authenticated_user)  # Authentication gerekli
):
    """Sadece authenticated kullanıcılar için profil oluşturma"""
    user_ref = db.collection('users').document(user_id)
    
    # Profil verilerini hazırla
    profile_data = {
        "plan": "free",
        "gender": profile.gender,
        "fullname": profile.fullname,
        "createdAt": firestore.SERVER_TIMESTAMP
    }
    
    user_ref.set(profile_data, merge=True)
    
    return {
        "status": "success", 
        "message": f"Profile for user {user_id} initialized.",
        "data": {
            "gender": profile.gender,
            "fullname": profile.fullname,
            "plan": "free"
        }
    }

# ESKİ profile endpoint'ini authenticated-only olarak koru (KALDIRILDI - çakışmayı önlemek için)
# @router.get("/profile")
# async def get_authenticated_user_profile(user_id: str = Depends(require_authenticated_user)):
#     """Bu endpoint kaldırıldı - get_user_profile_universal kullanılıyor"""
#     pass

@router.patch("/plan")
async def update_user_plan(
    plan_data: dict = Body(...), 
    user_id: str = Depends(require_authenticated_user)  # Authentication gerekli
):
    """Sadece authenticated kullanıcılar için plan güncelleme"""
    user_ref = db.collection('users').document(user_id)
    user_doc = user_ref.get()
    
    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User profile not found.")
    
    new_plan = plan_data.get("plan")
    if new_plan not in ["free", "premium"]:
        raise HTTPException(status_code=400, detail="Invalid plan type.")
    
    user_ref.update({
        "plan": new_plan,
        "planUpdatedAt": firestore.SERVER_TIMESTAMP
    })
    
    return {
        "status": "success",
        "message": f"Plan updated to {new_plan}",
        "data": {"plan": new_plan}
    }

@router.post("/verify-purchase")
async def verify_purchase(
    verification_data: dict = Body(...),
    user_id: str = Depends(require_authenticated_user)  # Authentication gerekli
):
    """Sadece authenticated kullanıcılar için satın alma doğrulama"""
    try:
        customer_info = verification_data.get("customer_info", {})
        
        # RevenueCat customer info'dan plan tipini belirle
        entitlements = customer_info.get("entitlements", {})
        new_plan = determine_plan_from_entitlements(entitlements)
        
        # User'ın planını güncelle
        user_ref = db.collection('users').document(user_id)
        user_ref.update({
            "plan": new_plan,
            "planUpdatedAt": firestore.SERVER_TIMESTAMP,
            "revenueCatCustomerId": customer_info.get("original_app_user_id")
        })
        
        return {
            "status": "success",
            "message": f"Plan updated to {new_plan}",
            "data": {"plan": new_plan}
        }
        
    except Exception as e:
        print(f"Purchase verification error: {str(e)}")
        raise HTTPException(status_code=500, detail="Purchase verification failed")

@router.post("/increment-usage")
async def increment_suggestion_usage(
    user_id: str = Depends(require_authenticated_user)  # Authentication gerekli
):
    """Sadece authenticated kullanıcılar için kullanım artırma"""
    try:
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            raise HTTPException(status_code=404, detail="User profile not found.")
        
        user_data = user_doc.to_dict()
        today = str(date.today())
        
        current_usage = user_data.get("usage", {})
        if current_usage.get("date") != today:
            current_usage = {"count": 0, "date": today}
        
        new_count = current_usage.get("count", 0) + 1
        updated_usage = {"count": new_count, "date": today}
        
        user_ref.update({"usage": updated_usage})
        
        return {
            "status": "success",
            "message": "Usage incremented",
            "data": {
                "current_usage": new_count,
                "date": today
            }
        }
        
    except Exception as e:
        print(f"Usage increment error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to increment usage")

@router.post("/grant-extra-suggestion")
async def grant_rewarded_suggestion(
    user_id: str = Depends(require_authenticated_user)  # Authentication gerekli
):
    """Sadece authenticated kullanıcılar için reklam karşılığı ekstra hak verme"""
    try:
        user_ref = db.collection('users').document(user_id)
        today = str(date.today())
        
        usage_data = user_ref.get(field_paths={'usage'}).to_dict().get('usage', {})
        
        if usage_data.get("date") != today:
            usage_data = {"count": 0, "date": today, "rewarded_count": 0}

        new_rewarded_count = usage_data.get("rewarded_count", 0) + 1
        usage_data["rewarded_count"] = new_rewarded_count
        
        user_ref.update({"usage": usage_data})
        
        return {
            "status": "success",
            "message": "Rewarded suggestion right granted.",
            "data": {
                "new_rewarded_count": new_rewarded_count,
                "date": today
            }
        }
    except Exception as e:
        print(f"Error granting rewarded suggestion: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to grant rewarded suggestion right.")
    
@router.delete("/delete-account")
async def delete_user_account(
    user_id: str = Depends(require_authenticated_user)  # Authentication gerekli
):
    """Sadece authenticated kullanıcılar için hesap silme"""
    try:
        user_ref = db.collection('users').document(user_id)
        
        user_doc = user_ref.get()
        if not user_doc.exists:
            return {"status": "success", "message": "User document not found, assumed already deleted."}

        user_ref.delete()
        print(f"🗑️ Firestore document for user {user_id} deleted.")

        return {"status": "success", "message": "Account permanently deleted from database."}

    except Exception as e:
        print(f"❌ Error deleting account for user {user_id}: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail="An error occurred while deleting the account. Please try again later."
        )

# RevenueCat Webhook Handler (authentication gerektirmez)
@webhook_router.post("/revenuecat-webhook")
async def handle_revenuecat_webhook(request: Request):
    """RevenueCat webhook'larını handle eder"""
    try:
        # Request body'yi oku (signature verification için)
        body = await request.body()
        
        # Webhook signature verification (güvenlik için)
        signature = request.headers.get("X-Revenuecat-Signature")
        
        if not verify_webhook_signature(signature, body):
            print(f"Invalid webhook signature: {signature}")
            raise HTTPException(status_code=401, detail="Invalid signature")
        
        # JSON data'yı parse et
        webhook_data = await request.json()
        event = webhook_data.get("event", {})
        event_type = event.get("type")
        
        print(f"Received webhook event: {event_type}")
        
        if event_type in ["INITIAL_PURCHASE", "RENEWAL", "PRODUCT_CHANGE"]:
            # Subscription başladı veya yenilendi
            app_user_id = event.get("app_user_id")
            
            if not app_user_id:
                print("Warning: No app_user_id in webhook event")
                return {"status": "success", "warning": "No app_user_id"}
            
            # Entitlements'ı doğru yerden al
            entitlements = event.get("entitlements", {})
            
            # Plan tipini belirle
            new_plan = determine_plan_from_entitlements_webhook(entitlements)
            
            # User'ın planını güncelle
            user_ref = db.collection('users').document(app_user_id)
            
            # User document'ının var olup olmadığını kontrol et
            user_doc = user_ref.get()
            if user_doc.exists:
                user_ref.update({
                    "plan": new_plan,
                    "planUpdatedAt": firestore.SERVER_TIMESTAMP,
                    "subscriptionStatus": "active"
                })
                print(f"Plan updated via webhook: {app_user_id} -> {new_plan}")
            else:
                print(f"Warning: User document not found for {app_user_id}")
            
        elif event_type in ["CANCELLATION", "EXPIRATION"]:
            # Subscription iptal oldu veya süresi doldu
            app_user_id = event.get("app_user_id")
            
            if not app_user_id:
                print("Warning: No app_user_id in webhook event")
                return {"status": "success", "warning": "No app_user_id"}
            
            user_ref = db.collection('users').document(app_user_id)
            
            # User document'ının var olup olmadığını kontrol et
            user_doc = user_ref.get()
            if user_doc.exists:
                user_ref.update({
                    "plan": "free",
                    "planUpdatedAt": firestore.SERVER_TIMESTAMP,
                    "subscriptionStatus": "cancelled"
                })
                print(f"Subscription cancelled via webhook: {app_user_id}")
            else:
                print(f"Warning: User document not found for {app_user_id}")
        
        return {"status": "success", "event_type": event_type}
        
    except Exception as e:
        print(f"Webhook error: {str(e)}")
        # Webhook hatalarında 500 döndürmek yerine 200 döndür ki RevenueCat retry etmesin
        return {"status": "error", "message": str(e)}

def determine_plan_from_entitlements(entitlements):
    """Client'ten gelen RevenueCat entitlement'larından plan tipini belirler"""
    for entitlement_id, entitlement_info in entitlements.items():
        if entitlement_id == "premium_access" and entitlement_info.get("isActive", False):
            return "premium"
    return "free"

def determine_plan_from_entitlements_webhook(entitlements):
    """Webhook'tan gelen RevenueCat entitlement'larından plan tipini belirler"""
    for entitlement_id, entitlement_info in entitlements.items():
        expires_date = entitlement_info.get("expires_date")
        if expires_date is None:  # Aktif subscription
            if entitlement_id == "premium_access":
                return "premium"
    return "free"

def verify_webhook_signature(signature: str, body: bytes) -> bool:
    """Webhook signature'ını doğrular (güvenlik)"""
    if not signature:
        print("Warning: No signature provided")
        return False
    
    webhook_secret = os.getenv("REVENUECAT_WEBHOOK_SECRET")
    
    if not webhook_secret:
        print("Warning: REVENUECAT_WEBHOOK_SECRET not set - allowing webhook for development")
        return True  # Development için geçici
    
    try:
        expected_signature = hmac.new(
            webhook_secret.encode('utf-8'),
            body,
            hashlib.sha256
        ).hexdigest()
        
        received_signature = signature
        if signature.startswith('sha256='):
            received_signature = signature[7:]
        
        is_valid = hmac.compare_digest(expected_signature, received_signature)
        
        if not is_valid:
            print(f"Signature mismatch - Expected: {expected_signature}, Received: {received_signature}")
        
        return is_valid
        
    except Exception as e:
        print(f"Signature verification error: {e}")
        return False