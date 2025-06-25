from fastapi import Depends, HTTPException, status
from datetime import date
from .security import get_current_user_id

USER_DATA_DB = {
    "user_firebase_uid_1": {
        "plan": "standard",  # 'free', 'standard', 'premium'
        "usage": {"count": 0, "date": "2025-06-12"}
    },
    "user_firebase_uid_2": {
        "plan": "free",
        "usage": {"count": 1, "date": "2025-06-12"}
    },
    "user_firebase_uid_3": {
        "plan": "premium",
        "usage": {"count": 0, "date": "2025-06-12"}
    },
    "default_user": {
        "plan": "free",
        "usage": {"count": 0, "date": "2025-01-01"}
    }
}

PLAN_LIMITS = {
    "free": 2,
    "standard": 10,
    "premium": 50
}

async def check_usage_limit(user_id: str = Depends(get_current_user_id)):
    today = str(date.today())
    
    user_data = USER_DATA_DB.get(user_id, USER_DATA_DB["default_user"])
    
    if user_data["usage"]["date"] != today:
        user_data["usage"]["count"] = 0
        user_data["usage"]["date"] = today

    limit = PLAN_LIMITS.get(user_data["plan"], 0)

    if user_data["usage"]["count"] >= limit:
        plan_name = user_data["plan"].capitalize()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Daily limit of {limit} requests reached for {plan_name} plan. Please upgrade your plan or try again tomorrow."
        )
    
    return user_id

def increment_usage(user_id: str):
    user_data = USER_DATA_DB.get(user_id, USER_DATA_DB["default_user"])
    user_data["usage"]["count"] += 1
    print(f"Usage for user {user_id} incremented to {user_data['usage']['count']} (Plan: {user_data['plan']})")

def can_upgrade_plan(current_plan: str) -> dict:
    """Kullanıcının yükseltebileceği planları döndürür"""
    plans = ["free", "standard", "premium"]
    current_index = plans.index(current_plan) if current_plan in plans else 0
    
    available_upgrades = []
    for i in range(current_index + 1, len(plans)):
        plan = plans[i]
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