# kodlar/core/usage.py

import datetime
from google.cloud import firestore
from typing import Union
from fastapi import Depends, HTTPException, status

# Proje kökünden mutlak importlar kullanıyoruz
from schemas import DailyUsage
from core.security import get_current_user_id

# Plan limitlerini merkezi bir yerde tanımlıyoruz
PLAN_LIMITS = {
    "free": 2,
    "anonymous": 1,
    "standard": 10,
    "premium": "unlimited"
}

def get_or_create_daily_usage(user_id: str) -> DailyUsage:
    """
    Kullanıcının günlük kullanım hakkını Firestore'dan alır veya oluşturur.
    """
    # --- DÜZELTME: Döngüsel import'u kırmak için 'db' burada import edildi ---
    from main import db

    user_ref = db.collection('users').document(user_id)
    user_doc = user_ref.get()
    
    if not user_doc.exists:
        plan = "anonymous"
        user_data = {}
    else:
        user_data = user_doc.to_dict()
        plan = user_data.get("plan", "anonymous")

    today_str = datetime.date.today().isoformat()
    usage_data = user_data.get("usage")
    
    if usage_data and usage_data.get("date") == today_str:
        current_usage = usage_data.get("count", 0)
        rewarded_count = usage_data.get("rewarded_count", 0)
    else:
        current_usage = 0
        rewarded_count = 0
        new_usage_data = {
            "date": today_str,
            "count": current_usage,
            "rewarded_count": rewarded_count
        }
        user_ref.set({"usage": new_usage_data}, merge=True)

    daily_limit = PLAN_LIMITS.get(plan, 1)
    
    if daily_limit == "unlimited":
        remaining = "unlimited"
        percentage_used = 0.0
    else:
        total_available = daily_limit + rewarded_count
        remaining = max(0, total_available - current_usage)
        percentage_used = (current_usage / total_available) * 100 if total_available > 0 else 0

    return DailyUsage(
        daily_limit=daily_limit,
        rewarded_count=rewarded_count,
        current_usage=current_usage,
        remaining=remaining,
        percentage_used=round(percentage_used, 2),
        date=today_str
    )

def increment_usage(user_id: str) -> None:
    """
    Kullanıcının o günkü kullanım sayısını 1 artırır.
    """
    # --- DÜZELTME: Döngüsel import'u kırmak için 'db' burada import edildi ---
    from main import db

    user_ref = db.collection('users').document(user_id)
    
    @firestore.transactional
    def update_in_transaction(transaction, user_ref):
        snapshot = user_ref.get(transaction=transaction)
        if not snapshot.exists:
            print(f"Error: User {user_id} not found for incrementing usage.")
            return 0
        user_data = snapshot.to_dict()
        today_str = datetime.date.today().isoformat()
        usage_data = user_data.get("usage")
        if usage_data and usage_data.get("date") == today_str:
            new_count = usage_data.get("count", 0) + 1
            transaction.update(user_ref, {"usage.count": new_count})
        else:
            new_count = 1
            transaction.update(user_ref, {
                "usage": {"date": today_str, "count": new_count, "rewarded_count": 0}
            })
        return new_count

    transaction = db.transaction()
    new_usage_count = update_in_transaction(transaction, user_ref)
    print(f"Usage for user {user_id} incremented to {new_usage_count}")

async def check_usage_limit(user_id_tuple: tuple = Depends(get_current_user_id)):
    """
    Kullanıcının günlük limitini kontrol eden FastAPI dependency'si.
    """
    user_id, is_anonymous = user_id_tuple
    usage_status = get_or_create_daily_usage(user_id)
    
    if usage_status.remaining == 0:
        if isinstance(usage_status.daily_limit, int):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Daily limit of {usage_status.daily_limit} requests reached. Please upgrade your plan or try again tomorrow."
            )
    
    return user_id

def can_upgrade_plan(current_plan: str) -> dict:
    """Kullanıcının yükseltebileceği planları döndürür"""
    plans = ["free", "anonymous", "standard", "premium"]
    
    if current_plan == "premium" or current_plan not in plans:
        return {
            "current_plan": current_plan,
            "current_limit": PLAN_LIMITS.get(current_plan, "N/A"),
            "available_upgrades": []
        }
        
    current_index = plans.index(current_plan)
    
    available_upgrades = []
    for i in range(current_index + 1, len(plans)):
        plan = plans[i]
        if plan == "anonymous": continue
        
        available_upgrades.append({
            "plan": plan,
            "daily_limit": PLAN_LIMITS[plan],
            "upgrade_available": True
        })
    
    return {
        "current_plan": current_plan,
        "current_limit": PLAN_LIMITS.get(current_plan, 0),
        "available_upgrades": available_upgrades
    }
