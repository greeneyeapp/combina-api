from fastapi import APIRouter, Depends, Body, Request, HTTPException
from firebase_admin import firestore
from pydantic import BaseModel
from datetime import datetime, date
import hmac
import hashlib
import os

from core.security import get_current_user_id
from schemas import ProfileInit

# Users router (authentication gerektirir)
router = APIRouter(
    prefix="/api/users",
    tags=["users"],
    dependencies=[Depends(get_current_user_id)]
)

# RevenueCat webhook için ayrı router (authentication gerektirmez)
webhook_router = APIRouter(
    prefix="/api",
    tags=["webhooks"]
)

db = firestore.client()

@router.post("/init-profile")
async def create_user_profile(profile: ProfileInit, user_id: str = Depends(get_current_user_id)):
    user_ref = db.collection('users').document(user_id)
    
    # Profil verilerini hazırla
    profile_data = {
        "plan": "free",
        "gender": profile.gender,
        "fullname": profile.fullname,
        "createdAt": firestore.SERVER_TIMESTAMP
    }
    
    if profile.birthDate:
        try:
            birth_date = datetime.fromisoformat(profile.birthDate.replace('Z', '+00:00'))
            profile_data["birthDate"] = birth_date
            
            today = datetime.now()
            age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
            profile_data["age"] = age
            
        except ValueError:
            print(f"Invalid birth date format: {profile.birthDate}")
    
    user_ref.set(profile_data, merge=True)
    
    return {
        "status": "success", 
        "message": f"Profile for user {user_id} initialized.",
        "data": {
            "gender": profile.gender,
            "fullname": profile.fullname,
            "age": profile_data.get("age"),
            "plan": "free"
        }
    }

@router.get("/profile")
async def get_user_profile(user_id: str = Depends(get_current_user_id)):
    """Kullanıcının profil bilgilerini döndürür"""
    user_ref = db.collection('users').document(user_id)
    user_doc = user_ref.get()
    
    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User profile not found.")
    
    user_data = user_doc.to_dict()
    today = str(date.today())
    
    # Günlük usage'ı kontrol et ve gerekirse sıfırla
    if user_data.get("usage", {}).get("date") != today:
        user_data["usage"] = {"count": 0, "date": today}
        user_ref.update({"usage": user_data["usage"]})
    
    plan_limits = {"free": 2, "standard": 10, "premium": 50}
    plan = user_data.get("plan", "free")
    daily_limit = plan_limits.get(plan, 2)
    current_usage = user_data.get("usage", {}).get("count", 0)
    remaining = max(0, daily_limit - current_usage)
    percentage_used = round((current_usage / daily_limit) * 100, 1) if daily_limit > 0 else 0
    
    return {
        "user_id": user_id,
        "fullname": user_data.get("fullname"),
        "gender": user_data.get("gender"),
        "age": user_data.get("age"),
        "plan": plan,
        "usage": {
            "daily_limit": daily_limit,
            "current_usage": current_usage,
            "remaining": remaining,
            "percentage_used": percentage_used,
            "date": today
        },
        "created_at": user_data.get("createdAt")
    }

@router.patch("/plan")
async def update_user_plan(
    plan_data: dict = Body(...), 
    user_id: str = Depends(get_current_user_id)
):
    """Kullanıcının planını günceller (subscription işlemleri için)"""
    user_ref = db.collection('users').document(user_id)
    user_doc = user_ref.get()
    
    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User profile not found.")
    
    new_plan = plan_data.get("plan")
    if new_plan not in ["free", "standard", "premium"]:
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
    user_id: str = Depends(get_current_user_id)
):
    """Client'ten gelen purchase verification'ı handle eder"""
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
async def increment_suggestion_usage(user_id: str = Depends(get_current_user_id)):
    """Suggestion kullanımını artırır"""
    try:
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            raise HTTPException(status_code=404, detail="User profile not found.")
        
        user_data = user_doc.to_dict()
        today = str(date.today())
        
        # Günlük usage'ı kontrol et ve gerekirse sıfırla
        current_usage = user_data.get("usage", {})
        if current_usage.get("date") != today:
            current_usage = {"count": 0, "date": today}
        
        # Usage'ı artır
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
    # Client'ten gelen entitlements formatı
    for entitlement_id, entitlement_info in entitlements.items():
        if entitlement_id == "premium_access" and entitlement_info.get("isActive", False):
            return "premium"
        elif entitlement_id == "standard_access" and entitlement_info.get("isActive", False):
            return "standard"
    return "free"

def determine_plan_from_entitlements_webhook(entitlements):
    """Webhook'tan gelen RevenueCat entitlement'larından plan tipini belirler"""
    # Webhook'tan gelen entitlements formatı - expires_date kontrolü
    for entitlement_id, entitlement_info in entitlements.items():
        # expires_date null ise aktif subscription, null değilse expired
        expires_date = entitlement_info.get("expires_date")
        if expires_date is None:  # Aktif subscription
            if entitlement_id == "premium_access":
                return "premium"
            elif entitlement_id == "standard_access":
                return "standard"
    return "free"

def verify_webhook_signature(signature: str, body: bytes) -> bool:
    """Webhook signature'ını doğrular (güvenlik)"""
    if not signature:
        print("Warning: No signature provided")
        return False
    
    # RevenueCat webhook secret'ını environment variable'dan al
    webhook_secret = os.getenv("REVENUECAT_WEBHOOK_SECRET")
    
    if not webhook_secret:
        print("Warning: REVENUECAT_WEBHOOK_SECRET not set - allowing webhook for development")
        return True  # Development için geçici
    
    try:
        # RevenueCat signature verification
        expected_signature = hmac.new(
            webhook_secret.encode('utf-8'),
            body,
            hashlib.sha256
        ).hexdigest()
        
        # Signature formatı kontrolü
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
    
@router.post("/grant-extra-suggestion")
async def grant_rewarded_suggestion(user_id: str = Depends(get_current_user_id)):
    """Kullanıcıya reklam izlemesi karşılığında bir ekstra öneri hakkı verir."""
    try:
        user_ref = db.collection('users').document(user_id)
        today = str(date.today())
        
        # Kullanıcının bugünkü kullanım verisini al
        usage_data = user_ref.get(field_paths={'usage'}).to_dict().get('usage', {})
        
        # Eğer gün farklıysa, sıfırdan bir usage objesi oluştur
        if usage_data.get("date") != today:
            usage_data = {"count": 0, "date": today, "rewarded_count": 0}

        # Ödüllü hak sayısını 1 artır
        new_rewarded_count = usage_data.get("rewarded_count", 0) + 1
        usage_data["rewarded_count"] = new_rewarded_count
        
        # Veritabanını güncelle
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