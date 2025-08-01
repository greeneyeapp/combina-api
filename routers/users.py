# api-kodlar/routers/users.py - NIHAI, TAM VE BİRLEŞTİRİLMİŞ VERSİYON

from fastapi import APIRouter, Depends, Body, Request, HTTPException
from firebase_admin import firestore
from pydantic import BaseModel
from datetime import date
from typing import Tuple

# Gerekli importlar ve router kurulumu
from core.security import get_current_user_id
# Webhook için gerekli diğer importlar
import hmac
import hashlib
import os

# --- Profil güncelleme için Pydantic modeli ---
class UserInfoUpdate(BaseModel):
    name: str
    gender: str

# --- Plan güncelleme için Pydantic modeli ---
class PlanUpdate(BaseModel):
    plan: str

# --- Ana kullanıcı router'ı ---
router = APIRouter(
    prefix="/api/users",
    tags=["users"]
)

# --- Webhook router'ı (ayrı ve kimlik doğrulamasız) ---
webhook_router = APIRouter(
    prefix="/api",
    tags=["webhooks"]
)

db = firestore.client()

# --- 1. Birleştirilmiş ve Sağlamlaştırılmış Profil Endpoint'i ---
@router.get("/profile")
async def get_user_profile(
    request: Request,
    user_data: Tuple[str, bool] = Depends(get_current_user_id)
):
    """
    Tüm kullanıcı tipleri (anonim ve kayıtlı) için profil bilgilerini getirir.
    Profil tamamlama durumunu her zaman veritabanından doğrular ve gerekirse günceller.
    """
    user_id, _ = user_data
    print(f"✅ Serving profile for user: {user_id[:10]}...")
    
    user_ref = db.collection('users').document(user_id)
    user_doc = user_ref.get()
    
    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User profile not found in database.")
    
    user_data_dict = user_doc.to_dict()
    
    # Her profil getirme işleminde, profilin tam olup olmadığını yeniden hesapla.
    fullname = user_data_dict.get("fullname")
    gender = user_data_dict.get("gender")
    is_profile_complete_calculated = bool(fullname and gender and gender != 'unisex')
    
    if user_data_dict.get("profile_complete") != is_profile_complete_calculated:
        print(f"🔄 Profile status mismatch for {user_id[:10]}. Updating DB.")
        user_ref.update({"profile_complete": is_profile_complete_calculated})

    # Kullanım (usage) verilerini hesapla
    today_str = str(date.today())
    usage_data = user_data_dict.get("usage", {})
    if usage_data.get("date") != today_str:
        usage_data = {"count": 0, "date": today_str, "rewarded_count": usage_data.get("rewarded_count", 0)}
        user_ref.update({"usage": usage_data})
        
    plan = user_data_dict.get("plan", "free")
    plan_limits = {"free": 2, "premium": 1000, "anonymous": 1}
    daily_limit = plan_limits.get(plan, 2)
    
    current_usage = usage_data.get("count", 0)
    rewarded_count = usage_data.get("rewarded_count", 0)
    
    if plan == "premium":
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
            "daily_limit": "unlimited" if plan == "premium" else daily_limit,
            "rewarded_count": rewarded_count,
            "current_usage": current_usage,
            "remaining": remaining,
            "percentage_used": percentage_used,
            "date": today_str
        },
        "created_at": user_data_dict.get("createdAt"),
        "isAnonymous": user_data_dict.get("is_anonymous", False),
        "profile_complete": is_profile_complete_calculated
    }

# --- 2. Eksik Olan Profil Güncelleme Endpoint'i ---
@router.post("/update-info")
async def update_user_info(
    update_data: UserInfoUpdate,
    user_data_tuple: Tuple[str, bool] = Depends(get_current_user_id)
):
    """
    Kullanıcının adını ve cinsiyetini günceller ve 'profile_complete' durumunu
    veritabanına kalıcı olarak kaydeder.
    """
    user_id, _ = user_data_tuple
    user_ref = db.collection('users').document(user_id)

    if not user_ref.get().exists:
        raise HTTPException(status_code=404, detail="User not found.")

    is_profile_complete = bool(update_data.name and update_data.gender and update_data.gender != 'unisex')
    
    db_update_data = {
        "fullname": update_data.name,
        "gender": update_data.gender,
        "profile_complete": is_profile_complete
    }
    user_ref.update(db_update_data)
    
    print(f"✅ Profile updated for {user_id[:10]}. New status: profile_complete={is_profile_complete}")
    
    return {
        "status": "success",
        "message": "User info updated successfully.",
        "profile_complete": is_profile_complete
    }

# --- 3. Plan Güncelleme Endpoint'i ---
@router.patch("/plan")
async def update_user_plan(
    plan_data: PlanUpdate, 
    user_data_tuple: Tuple[str, bool] = Depends(get_current_user_id)
):
    user_id, _ = user_data_tuple
    user_ref = db.collection('users').document(user_id)
    
    if not user_ref.get().exists:
        raise HTTPException(status_code=404, detail="User profile not found.")
    
    new_plan = plan_data.plan
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

# --- 4. Reklam Ödülü Endpoint'i ---
@router.post("/grant-extra-suggestion")
async def grant_rewarded_suggestion(
    user_data_tuple: Tuple[str, bool] = Depends(get_current_user_id)
):
    """Reklam izleme karşılığında ekstra kombin hakkı verir."""
    user_id, _ = user_data_tuple
    try:
        user_ref = db.collection('users').document(user_id)
        today = str(date.today())
        
        @firestore.transactional
        def update_reward_in_transaction(transaction, user_ref_trans):
            snapshot = user_ref_trans.get(transaction=transaction).to_dict()
            usage_data = snapshot.get('usage', {})
            
            if usage_data.get("date") != today:
                usage_data = {"count": 0, "date": today, "rewarded_count": 0}

            new_rewarded_count = usage_data.get("rewarded_count", 0) + 1
            usage_data["rewarded_count"] = new_rewarded_count
            
            transaction.update(user_ref_trans, {"usage": usage_data})
            return new_rewarded_count

        transaction = db.transaction()
        final_reward_count = update_reward_in_transaction(transaction, user_ref)

        return {
            "status": "success",
            "message": "Rewarded suggestion right granted.",
            "data": {
                "new_rewarded_count": final_reward_count,
                "date": today
            }
        }
    except Exception as e:
        print(f"Error granting rewarded suggestion: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to grant rewarded suggestion right.")

# --- 5. Hesap Silme Endpoint'i ---
@router.delete("/delete-account")
async def delete_user_account(
    user_data_tuple: Tuple[str, bool] = Depends(get_current_user_id)
):
    user_id, _ = user_data_tuple
    try:
        user_ref = db.collection('users').document(user_id)
        if user_ref.get().exists:
            user_ref.delete()
            print(f"🗑️ Firestore document for user {user_id} deleted.")
        return {"status": "success", "message": "Account permanently deleted."}
    except Exception as e:
        print(f"❌ Error deleting account for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Could not delete account.")


# --- 6. RevenueCat Webhook Endpoint'i ve Yardımcı Fonksiyonlar ---
def verify_webhook_signature(signature: str, body: bytes) -> bool:
    """Webhook imzasını doğrular (güvenlik için)."""
    if not signature:
        print("Warning: No signature provided for webhook.")
        return False
    
    webhook_secret = os.getenv("REVENUECAT_WEBHOOK_SECRET")
    if not webhook_secret:
        print("Warning: REVENUECAT_WEBHOOK_SECRET not set. Allowing webhook for development.")
        return True
    
    try:
        expected_signature = hmac.new(webhook_secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
        received_signature = signature.split('sha256=')[-1]
        return hmac.compare_digest(expected_signature, received_signature)
    except Exception as e:
        print(f"Signature verification error: {e}")
        return False

def determine_plan_from_entitlements_webhook(entitlements: dict) -> str:
    """Webhook'tan gelen entitlement listesinden plan tipini belirler."""
    if "premium_access" in entitlements:
        if entitlements["premium_access"].get("expires_date") is None:
            return "premium"
    return "free"

@webhook_router.post("/revenuecat-webhook")
async def handle_revenuecat_webhook(request: Request):
    """RevenueCat'ten gelen sunucu-sunucu bildirimlerini işler."""
    body = await request.body()
    signature = request.headers.get("X-Revenuecat-Signature")
    
    if not verify_webhook_signature(signature, body):
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")
        
    try:
        webhook_data = await request.json()
        event = webhook_data.get("event", {})
        event_type = event.get("type")
        app_user_id = event.get("app_user_id")
        
        if not app_user_id:
            return {"status": "warning", "message": "No app_user_id in webhook event."}
            
        print(f"Received webhook event: {event_type} for user {app_user_id[:10]}")
        
        user_ref = db.collection('users').document(app_user_id)
        if not user_ref.get().exists:
            print(f"Warning: User document not found for webhook: {app_user_id}")
            return {"status": "warning", "message": "User not found."}

        if event_type in ["INITIAL_PURCHASE", "RENEWAL", "UNCANCELLATION", "PRODUCT_CHANGE"]:
            new_plan = determine_plan_from_entitlements_webhook(event.get("entitlements", {}))
            user_ref.update({
                "plan": new_plan,
                "planUpdatedAt": firestore.SERVER_TIMESTAMP,
                "subscriptionStatus": "active"
            })
            print(f"Plan updated via webhook: {app_user_id[:10]} -> {new_plan}")
            
        elif event_type in ["CANCELLATION", "EXPIRATION", "BILLING_ISSUE"]:
            user_ref.update({
                "plan": "free",
                "planUpdatedAt": firestore.SERVER_TIMESTAMP,
                "subscriptionStatus": "cancelled"
            })
            print(f"Subscription cancelled via webhook for user: {app_user_id[:10]}")
            
        return {"status": "success"}
        
    except Exception as e:
        print(f"Webhook processing error: {str(e)}")
        return {"status": "error", "message": str(e)}
