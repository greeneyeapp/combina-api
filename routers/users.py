# routers/users.py

from fastapi import APIRouter, Depends, HTTPException, Request, Body
from firebase_admin import firestore
import logging

# Hatalı olan 'services' importu yerine, projenin ana dizinindeki
# 'firebase_setup.py' dosyasından db ve auth objelerini alıyoruz.
from firebase_setup import db, auth

router = APIRouter()

# Logging yapılandırması
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_current_user(request: Request):
    """
    Authorization header'ından token'ı alıp kullanıcıyı doğrular.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Yetkilendirme Gerekli")
    
    id_token = auth_header.split("Bearer ")[1]
    try:
        # 'auth' objesi artık firebase_setup.py'dan geliyor
        decoded_token = auth.verify_id_token(id_token)
        return decoded_token
    except Exception as e:
        logger.error(f"Token doğrulama hatası: {e}")
        raise HTTPException(status_code=401, detail="Geçersiz veya süresi dolmuş token")

def determine_plan_from_entitlements(entitlements: dict) -> str:
    """
    RevenueCat'ten gelen entitlements objesinden kullanıcının planını belirler.
    'premium' yetkisi aktifse 'premium', değilse 'free' döner.
    """
    # 'premium' yetkisinin olup olmadığını ve aktif olup olmadığını kontrol et
    if "premium" in entitlements and entitlements["premium"].get("expires_date") is None:
        return "premium"
    return "free"

@router.post("/revenuecat-webhook")
async def handle_revenuecat_webhook(request: Request):
    """
    RevenueCat'ten gelen webhook event'lerini işler.
    """
    try:
        event = await request.json()
        event_data = event.get("event", {})
        logger.info(f"Gelen RevenueCat Event Tipi: {event_data.get('type')}")
    except Exception as e:
        logger.error(f"Webhook isteği okunurken hata: {e}")
        raise HTTPException(status_code=400, detail="Geçersiz JSON")

    app_user_id = event_data.get("app_user_id")
    if not app_user_id:
        logger.warning("Webhook event'inde 'app_user_id' bulunamadı.")
        return {"status": "success", "warning": "No app_user_id found in event"}

    user_ref = db.collection('users').document(app_user_id)
    
    try:
        user_doc = user_ref.get()
        if not user_doc.exists:
            logger.warning(f"Webhook için kullanıcı bulunamadı: {app_user_id}")
            return {"status": "success", "message": f"User {app_user_id} not found"}

        user_data = user_doc.to_dict()
        previous_plan = user_data.get("plan", "free")
        
        entitlements = event_data.get("entitlements", {})
        new_plan = determine_plan_from_entitlements(entitlements)

        if previous_plan == new_plan:
            logger.info(f"Plan değişmedi, işlem atlandı. Kullanıcı: {app_user_id}, Plan: {new_plan}")
            return {"status": "success", "message": "Plan is already up to date"}

        batch = db.batch()

        history_ref = db.collection('plan_history').document()
        batch.set(history_ref, {
            "userId": app_user_id,
            "previousPlan": previous_plan,
            "newPlan": new_plan,
            "changeTimestamp": firestore.SERVER_TIMESTAMP,
            "changeSource": f"webhook_{event_data.get('type', 'unknown')}",
            "eventDetails": event_data
        })

        batch.update(user_ref, {
            "plan": new_plan,
            "planUpdatedAt": firestore.SERVER_TIMESTAMP,
            "subscriptionStatus": "active" if new_plan == "premium" else "inactive"
        })

        batch.commit()
        
        logger.info(f"Plan başarıyla güncellendi ve loglandı (Webhook). Kullanıcı: {app_user_id}, {previous_plan} -> {new_plan}")

    except Exception as e:
        logger.error(f"Webhook işlenirken hata oluştu: {app_user_id}, Hata: {e}")
        raise HTTPException(status_code=500, detail="Internal server error while processing webhook")

    return {"status": "success"}


@router.patch("/plan")
def update_user_plan(
    new_plan: str = Body(..., embed=True), 
    current_user: dict = Depends(get_current_user)
):
    """
    Kullanıcının planını manuel olarak günceller (Admin veya test amaçlı).
    """
    user_id = current_user["uid"]
    if new_plan not in ["free", "premium"]:
        raise HTTPException(status_code=400, detail="Geçersiz plan tipi. Sadece 'free' veya 'premium' olabilir.")
        
    user_ref = db.collection('users').document(user_id)
    
    try:
        user_doc = user_ref.get()
        if not user_doc.exists:
            raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")

        user_data = user_doc.to_dict()
        previous_plan = user_data.get("plan", "free")

        if previous_plan == new_plan:
             return {"message": "Plan zaten güncel", "current_plan": new_plan}

        batch = db.batch()

        history_ref = db.collection('plan_history').document()
        batch.set(history_ref, {
            "userId": user_id,
            "previousPlan": previous_plan,
            "newPlan": new_plan,
            "changeTimestamp": firestore.SERVER_TIMESTAMP,
            "changeSource": "manual_update"
        })

        batch.update(user_ref, {
            "plan": new_plan,
            "planUpdatedAt": firestore.SERVER_TIMESTAMP
        })
        
        batch.commit()
        
        logger.info(f"Plan başarıyla güncellendi ve loglandı (Manuel). Kullanıcı: {user_id}, {previous_plan} -> {new_plan}")
        return {"message": "Plan başarıyla güncellendi", "new_plan": new_plan}
    except Exception as e:
        logger.error(f"Manuel plan güncelleme hatası: {user_id}, Hata: {e}")
        raise HTTPException(status_code=500, detail="Plan güncellenirken bir hata oluştu.")


@router.post("/verify-purchase")
def verify_purchase(
    entitlements: dict = Body(..., embed=True),
    current_user: dict = Depends(get_current_user)
):
    """
    Client tarafından gönderilen entitlement bilgisi ile kullanıcının planını doğrular ve günceller.
    """
    user_id = current_user["uid"]
    new_plan = determine_plan_from_entitlements(entitlements)

    user_ref = db.collection('users').document(user_id)
    try:
        user_doc = user_ref.get()
        if not user_doc.exists:
            raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
        
        user_data = user_doc.to_dict()
        previous_plan = user_data.get("plan", "free")

        if previous_plan == new_plan:
            return {"status": "success", "plan": new_plan, "message": "Plan zaten güncel."}

        batch = db.batch()

        history_ref = db.collection('plan_history').document()
        batch.set(history_ref, {
            "userId": user_id,
            "previousPlan": previous_plan,
            "newPlan": new_plan,
            "changeTimestamp": firestore.SERVER_TIMESTAMP,
            "changeSource": "client_verification"
        })

        batch.update(user_ref, {
            "plan": new_plan,
            "planUpdatedAt": firestore.SERVER_TIMESTAMP
        })
        
        batch.commit()
        
        logger.info(f"Plan başarıyla güncellendi ve loglandı (Client). Kullanıcı: {user_id}, {previous_plan} -> {new_plan}")
        return {"status": "success", "plan": new_plan}
    except Exception as e:
        logger.error(f"Satın alma doğrulama hatası: {user_id}, Hata: {e}")
        raise HTTPException(status_code=500, detail="Satın alma doğrulanırken bir hata oluştu.")