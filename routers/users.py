from fastapi import APIRouter, Depends, Body, Request, HTTPException
from firebase_admin import firestore
from pydantic import BaseModel
from datetime import date
from typing import Tuple, Optional
import hmac
import hashlib
import os
import datetime

from core.security import get_current_user_id
from schemas import DailyUsage # schemas.py'den DailyUsage'ı import edelim

router = APIRouter(
    prefix="/api/users",
    tags=["users"]
)
webhook_router = APIRouter(
    prefix="/api",
    tags=["webhooks"]
)
db = firestore.client()

class UserInfoUpdate(BaseModel):
    name: str
    gender: str

class PlanUpdate(BaseModel):
    plan: str

class PurchaseVerificationRequest(BaseModel):
    customer_info: dict

@router.get("/profile")
async def get_user_profile(
    request: Request,
    user_data_tuple: Tuple[str, bool] = Depends(get_current_user_id)
):
    user_id, is_anonymous = user_data_tuple
    
    user_ref = db.collection('users').document(user_id)
    user_doc = user_ref.get()
    
    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User profile not found in database.")
    
    user_data_dict = user_doc.to_dict()
    
    fullname = user_data_dict.get("fullname")
    gender = user_data_dict.get("gender")
    is_profile_complete_calculated = bool(fullname and gender and gender != 'unisex')
    
    if user_data_dict.get("profile_complete") != is_profile_complete_calculated:
        user_ref.update({"profile_complete": is_profile_complete_calculated})

    usage_status = get_or_create_daily_usage(user_id)
    
    return {
        "user_id": user_id,
        "fullname": user_data_dict.get("fullname"),
        "email": user_data_dict.get("email"),
        "gender": user_data_dict.get("gender"),
        "plan": user_data_dict.get("plan", "free"),
        "usage": usage_status.dict(),
        "created_at": user_data_dict.get("createdAt"),
        "isAnonymous": user_data_dict.get("is_anonymous", False),
        "profile_complete": is_profile_complete_calculated
    }

@router.post("/update-info")
async def update_user_info(
    update_data: UserInfoUpdate,
    user_data_tuple: Tuple[str, bool] = Depends(get_current_user_id)
):
    user_id, _ = user_data_tuple
    user_ref = db.collection('users').document(user_id)

    if not user_ref.get().exists:
        raise HTTPException(status_code=404, detail="User not found.")

    is_profile_complete = bool(update_data.name and update_data.gender and update_data.gender != 'unisex')
    
    db_update_data = {
        "fullname": update_data.name,
        "gender": update_data.gender,
        "profile_complete": is_profile_complete,
        "updatedAt": firestore.SERVER_TIMESTAMP
    }
    user_ref.update(db_update_data)
    
    return {
        "status": "success",
        "message": "User info updated successfully.",
        "profile_complete": is_profile_complete
    }

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

@router.post("/grant-extra-suggestion")
async def grant_rewarded_suggestion(
    user_data_tuple: Tuple[str, bool] = Depends(get_current_user_id)
):
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

@router.post("/verify-purchase")
async def verify_purchase(
    request_data: PurchaseVerificationRequest,
    user_data_tuple: Tuple[str, bool] = Depends(get_current_user_id)
):
    user_id, _ = user_data_tuple
    print(f"Received purchase verification for user: {user_id}")
    print(f"Customer Info from client: {request_data.customer_info}")
    return {"status": "received", "message": "Verification data received for logging."}

def verify_webhook_signature(signature: str, body: bytes) -> bool:
    if not signature: return False
    webhook_secret = os.getenv("REVENUECAT_WEBHOOK_SECRET")
    if not webhook_secret: return True
    try:
        expected_signature = hmac.new(webhook_secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected_signature, signature.split('sha256=')[-1])
    except Exception as e:
        print(f"Signature verification error: {e}")
        return False

def determine_plan_from_entitlements_webhook(entitlements: dict) -> str:
    if "premium_access" in entitlements and entitlements["premium_access"].get("expires_date") is None:
        return "premium"
    return "free"

@webhook_router.post("/revenuecat-webhook")
async def handle_revenuecat_webhook(request: Request):
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
            
        user_ref = db.collection('users').document(app_user_id)
        if not user_ref.get().exists:
            return {"status": "warning", "message": "User not found."}

        if event_type in ["INITIAL_PURCHASE", "RENEWAL", "UNCANCELLATION", "PRODUCT_CHANGE"]:
            new_plan = determine_plan_from_entitlements_webhook(event.get("entitlements", {}))
            user_ref.update({"plan": new_plan, "planUpdatedAt": firestore.SERVER_TIMESTAMP, "subscriptionStatus": "active"})
        elif event_type in ["CANCELLATION", "EXPIRATION", "BILLING_ISSUE"]:
            user_ref.update({"plan": "free", "planUpdatedAt": firestore.SERVER_TIMESTAMP, "subscriptionStatus": "cancelled"})
            
        return {"status": "success"}
    except Exception as e:
        print(f"Webhook processing error: {str(e)}")
        return {"status": "error", "message": str(e)}

# --- DEĞİŞİKLİK: 'get_or_create_daily_usage' fonksiyonunu core/usage.py'den buraya taşıdık.
def get_or_create_daily_usage(user_id: str) -> DailyUsage:
    user_ref = db.collection('users').document(user_id)
    user_doc = user_ref.get()
    
    if not user_doc.exists:
        plan = "free"
        user_data = {}
    else:
        user_data = user_doc.to_dict()
        plan = user_data.get("plan", "free")

    today_str = datetime.date.today().isoformat()
    usage_data = user_data.get("usage")
    
    if usage_data and usage_data.get("date") == today_str:
        current_usage = usage_data.get("count", 0)
        rewarded_count = usage_data.get("rewarded_count", 0)
    else:
        current_usage = 0
        rewarded_count = 0
        new_usage_data = {"date": today_str, "count": 0, "rewarded_count": 0}
        user_ref.set({"usage": new_usage_data}, merge=True)

    from core.usage import PLAN_LIMITS
    daily_limit = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
    
    if daily_limit == "unlimited":
        remaining = "unlimited"
        percentage_used = 0.0
    else:
        total_available = daily_limit + rewarded_count
        remaining = max(0, total_available - current_usage)
        percentage_used = (current_usage / total_available) * 100 if total_available > 0 else 0

    return DailyUsage(
        daily_limit=daily_limit, rewarded_count=rewarded_count,
        current_usage=current_usage, remaining=remaining,
        percentage_used=round(percentage_used, 2), date=today_str
    )