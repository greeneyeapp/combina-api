# kodlar/core/usage.py

import datetime
from google.cloud import firestore
from typing import Union

# Proje içi importlar
from .database import db  # Hatalı import düzeltildi, artık yeni database dosyasından alıyoruz
from ..schemas import DailyUsage

# Plan limitlerini merkezi bir yerde tanımlıyoruz
PLAN_LIMITS = {
    "free": 2,
    "anonymous": 1,
    "standard": 10,
    "premium": "unlimited"  # Client tarafında da bu şekilde yönetiliyor
}

def get_or_create_daily_usage(user_id: str) -> DailyUsage:
    """
    Kullanıcının günlük kullanım hakkını Firestore'dan alır veya oluşturur.
    
    Args:
        user_id (str): Firestore'daki kullanıcı ID'si.

    Returns:
        DailyUsage: Kullanıcının güncel kullanım durumunu içeren Pydantic modeli.
    """
    # 1. Kullanıcının planını öğrenmek için ana dokümanını al
    user_ref = db.collection('users').document(user_id)
    user_doc = user_ref.get()
    
    if not user_doc.exists:
        # Bu durum normalde yaşanmamalı, ama bir güvenlik önlemi olarak
        # kullanıcı bulunamazsa varsayılan anonim planını kullan.
        plan = "anonymous"
        user_data = {}
    else:
        user_data = user_doc.to_dict()
        plan = user_data.get("plan", "anonymous")

    # 2. Bugünün tarihini al (YYYY-MM-DD formatında)
    today_str = datetime.date.today().isoformat()

    # 3. Firestore'daki 'usage' alanını kontrol et
    usage_data = user_data.get("usage")
    
    # 4. Eğer 'usage' alanı varsa ve tarihi bugünse, mevcut veriyi kullan.
    #    Yoksa veya tarihi eskiyse, bugünün verisini sıfırdan oluştur.
    if usage_data and usage_data.get("date") == today_str:
        current_usage = usage_data.get("count", 0)
        rewarded_count = usage_data.get("rewarded_count", 0)
    else:
        current_usage = 0
        rewarded_count = 0
        # Firestore'da bugünün yeni kullanım kaydını oluştur/güncelle
        new_usage_data = {
            "date": today_str,
            "count": current_usage,
            "rewarded_count": rewarded_count
        }
        # Kullanıcı dokümanı yoksa update() hata verir, bu yüzden set(..., merge=True) daha güvenli
        user_ref.set({"usage": new_usage_data}, merge=True)

    # 5. Kalan hakları ve yüzdeyi hesapla
    daily_limit = PLAN_LIMITS.get(plan, 1)  # Bilinmeyen bir plan varsa 1 hak ver
    
    if daily_limit == "unlimited":
        remaining = "unlimited"
        percentage_used = 0.0
    else:
        total_available = daily_limit + rewarded_count
        remaining = max(0, total_available - current_usage)
        percentage_used = (current_usage / total_available) * 100 if total_available > 0 else 0

    # 6. auth.py'nin beklediği Pydantic modelini doldurup döndür
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
    Bu fonksiyon, başarılı bir kombin önerisinden sonra çağrılmalıdır.
    """
    user_ref = db.collection('users').document(user_id)
    
    # Firestore'da atomik (güvenli) bir artırma işlemi için transaction kullan
    @firestore.transactional
    def update_in_transaction(transaction, user_ref):
        snapshot = user_ref.get(transaction=transaction)
        
        # Kullanıcı dokümanı yoksa işlem yapma
        if not snapshot.exists:
            print(f"Error: User {user_id} not found for incrementing usage.")
            return 0

        user_data = snapshot.to_dict()
        
        today_str = datetime.date.today().isoformat()
        usage_data = user_data.get("usage")

        if usage_data and usage_data.get("date") == today_str:
            # Bugün için zaten bir kayıt var, sadece sayacı artır
            new_count = usage_data.get("count", 0) + 1
            transaction.update(user_ref, {"usage.count": new_count})
        else:
            # Bugünün ilk kullanımı, yeni bir kayıt oluştur
            new_count = 1
            transaction.update(user_ref, {
                "usage": {
                    "date": today_str,
                    "count": new_count,
                    "rewarded_count": 0
                }
            })
        return new_count

    transaction = db.transaction()
    new_usage_count = update_in_transaction(transaction, user_ref)
    print(f"Usage for user {user_id} incremented to {new_usage_count}")
