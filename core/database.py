# kodlar/core/database.py

import firebase_admin
from firebase_admin import credentials, firestore
import os

# Firebase Admin SDK'sını başlat.
# Bu kod, uygulamanın yaşam döngüsünde sadece bir kez çalışır.
try:
    # Sunucu ortamında, GOOGLE_APPLICATION_CREDENTIALS ortam değişkeni
    # servis hesabı anahtar dosyasının yolunu göstermelidir.
    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not cred_path:
        raise ValueError("GOOGLE_APPLICATION_CREDENTIALS ortam değişkeni ayarlanmamış.")
        
    cred = credentials.Certificate(cred_path)
    
    # Eğer zaten başlatılmamışsa başlat
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
        print("✅ Firebase Admin SDK başarıyla başlatıldı.")
    else:
        print("✅ Firebase Admin SDK zaten başlatılmış.")

except Exception as e:
    print(f"🔥 Firebase Admin SDK başlatılırken hata oluştu: {e}")
    # Hata durumunda, uygulama başlamadan çökmesi daha iyidir.
    raise e

# Diğer tüm modüllerin kullanacağı global Firestore client nesnesini oluştur.
db = firestore.client()
