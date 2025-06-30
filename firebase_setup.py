
import firebase_admin
from firebase_admin import credentials, firestore, auth as firebase_auth
import os
import logging
from core.config import settings # <-- SETTINGS IMPORT'U EKLENDİ

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    key_path = settings.GOOGLE_APPLICATION_CREDENTIALS

    if not os.path.exists(key_path):
        logger.error(f"KRİTİK HATA: Firebase servis anahtarı bulunamadı: {key_path}")
        raise FileNotFoundError(f"Firebase servis anahtarı bulunamadı: {key_path}")

    if not firebase_admin._apps:
        cred = credentials.Certificate(key_path)
        firebase_admin.initialize_app(cred)
        logger.info("Firebase uygulaması başarıyla başlatıldı.")
    else:
        logger.info("Firebase uygulaması zaten başlatılmış.")

    db = firestore.client()
    auth = firebase_auth

except Exception as e:
    logger.critical(f"Firebase başlatılırken uygulama çökertici bir hata oluştu: {e}")
    raise e