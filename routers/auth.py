from fastapi import APIRouter, Depends, HTTPException, status, Request, Body  # Body eklendi
from datetime import timedelta, datetime
from firebase_admin import firestore
import requests
import jwt
from typing import Optional, Tuple
from pydantic import BaseModel
import secrets
from core.security import create_access_token, get_current_user_id, require_authenticated_user
from core.config import settings

router = APIRouter()
db = firestore.client()

# OAuth modelleri
class GoogleAuthRequest(BaseModel):
    access_token: str

class AppleAuthRequest(BaseModel):
    identity_token: str
    authorization_code: Optional[str] = None
    user_info: Optional[dict] = None

class UserInfoUpdate(BaseModel):
    name: str
    gender: str

# Anonymous kullanıcı bilgi modeli
class AnonymousUserInfo(BaseModel):
    session_id: str
    language: Optional[str] = "en"
    gender: Optional[str] = "unisex"

# Google OAuth endpoint (değişmedi)
@router.post("/auth/google")
async def google_auth(request: GoogleAuthRequest):
    """Google OAuth ile direkt backend'e giriş"""
    try:
        # Google API'den kullanıcı bilgilerini al
        google_user_info = await get_google_user_info(request.access_token)
        
        if not google_user_info:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Google access token"
            )
        
        # Kullanıcı ID'sini Google ID'den oluştur
        user_id = f"google_{google_user_info['id']}"
        
        # Kullanıcıyı Firestore'da oluştur/güncelle
        user_info = await create_or_update_user(
            uid=user_id,
            email=google_user_info['email'],
            name=google_user_info.get('name', ''),
            provider='google',
            provider_id=google_user_info['id']
        )
        
        # Backend JWT token oluştur
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": user_id}, expires_delta=access_token_expires
        )
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user_info": user_info
        }
        
    except Exception as e:
        print(f"Google auth error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google authentication failed"
        )

@router.post("/auth/apple")
async def apple_auth(request: AppleAuthRequest):
    """Apple Sign-In ile direkt backend'e giriş"""
    try:
        # Apple identity token'ı doğrula
        apple_user_info = await verify_apple_token(request.identity_token)
        
        if not apple_user_info or not isinstance(apple_user_info, dict):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Apple identity token"
            )
        
        # --- GÜVENLİ İSİM BİRLEŞTİRME MANTIĞI ---
        full_name = ""
        
        # Client'tan gelen 'name' alanının SÖZLÜK olup olmadığını kontrol et
        if request.user_info and isinstance(request.user_info.get('name'), dict):
            name_data = request.user_info['name']
            full_name = f"{name_data.get('givenName', '')} {name_data.get('familyName', '')}".strip()
        # Client'tan gelen 'name' alanının METİN olup olmadığını kontrol et
        elif request.user_info and isinstance(request.user_info.get('name'), str):
             full_name = request.user_info['name']

        # Eğer yukarıdaki kontrollerden bir isim alınamadıysa, token'dan gelen bilgileri kullan
        if not full_name:
            if apple_user_info.get('email'):
                full_name = apple_user_info.get('email').split('@')[0]
            else:
                apple_sub = apple_user_info.get('sub', secrets.token_hex(4))
                full_name = f"User_{apple_sub[:8]}"
        
        # Kullanıcı ID'sini Apple ID'den oluştur
        user_id = f"apple_{apple_user_info['sub']}"
        
        # Kullanıcıyı Firestore'da oluştur/güncelle
        user_info = await create_or_update_user(
            uid=user_id,
            email=apple_user_info.get('email', ''),
            name=full_name,
            provider='apple',
            provider_id=apple_user_info['sub']
        )
        
        # Backend JWT token oluştur
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": user_id}, expires_delta=access_token_expires
        )
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user_info": user_info
        }
        
    except Exception as e:
        # Hata durumunda sadece genel bir hata mesajı döndür
        print(f"Apple auth error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Apple authentication failed."
        )

@router.post("/auth/anonymous")
async def start_anonymous_session(
    request: Request,
    user_info: AnonymousUserInfo
):
    """
    Anonymous kullanıcı için session başlatır.
    Client IP ve User-Agent'tan unique ID oluşturur.
    """
    try:
        from core.security import create_anonymous_user_id
        anonymous_id = create_anonymous_user_id(request)
        
        print(f"🔄 Starting anonymous session: {anonymous_id[:16]}...")
        
        # Anonymous kullanıcıyı Firestore'a kaydet
        user_ref = db.collection('users').document(anonymous_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            user_data = {
                "type": "anonymous",
                "plan": "anonymous",
                "gender": user_info.gender or "unisex",
                "language": user_info.language or "en",
                "createdAt": firestore.SERVER_TIMESTAMP,
                "profile_incomplete": True,
                "usage": {
                    "count": 0, 
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "rewarded_count": 0
                },
                "recent_outfits": []
            }
            user_ref.set(user_data)
            print(f"✅ New anonymous user created in DB: {anonymous_id}")
        else:
            print(f"✅ Existing anonymous user found: {anonymous_id}")
        
        session_token = create_access_token(
            data={"sub": anonymous_id, "type": "anonymous"},
            expires_delta=timedelta(days=1)
        )
        
        return {
            "session_id": anonymous_id,
            "access_token": session_token,
            "token_type": "bearer",
            "user_info": {
                "uid": anonymous_id,
                "type": "anonymous",
                "plan": "anonymous",
                "daily_limit": 1,
                "gender": user_info.gender or "unisex",
                "language": user_info.language or "en",
                "is_anonymous": True,  # ← Bu field'ı ekleyin
                "isAnonymous": True,   # ← Bu field'ı da ekleyin (client compatibility için)
                "profile_complete": False
            }
        }
        
    except Exception as e:
        print(f"Anonymous session error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start anonymous session"
        )

# YENİ: Anonymous kullanıcıdan authenticated kullanıcıya geçiş endpoint'i
@router.post("/auth/convert-anonymous")
async def convert_anonymous_to_authenticated(
    request: Request,
    conversion_data: dict = Body(...),  # Bu satır artık çalışacak
    user_data: Tuple[str, bool] = Depends(get_current_user_id)
):
    """
    Anonymous kullanıcıyı authenticated kullanıcıya dönüştürür.
    OAuth ile giriş yapıldıktan sonra anonymous session verilerini kaydeder.
    """
    user_id, is_anonymous = user_data
    
    if not is_anonymous:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This endpoint is only for anonymous users"
        )
    
    try:
        # OAuth token'ından yeni user bilgilerini al
        oauth_token = conversion_data.get("oauth_token")
        provider = conversion_data.get("provider")  # "google" or "apple"
        
        if not oauth_token or not provider:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OAuth token and provider are required"
            )
        
        # Anonymous kullanıcının mevcut verilerini al
        from routers.outfits import get_anonymous_user_usage
        anonymous_usage = get_anonymous_user_usage(user_id)
        
        # Yeni authenticated user oluştur (bu kısım OAuth provider'a göre farklı olacak)
        if provider == "google":
            google_user_info = await get_google_user_info(oauth_token)
            if not google_user_info:
                raise HTTPException(status_code=401, detail="Invalid Google token")
            
            new_user_id = f"google_{google_user_info['id']}"
            user_info = await create_or_update_user(
                uid=new_user_id,
                email=google_user_info['email'],
                name=google_user_info.get('name', ''),
                provider='google',
                provider_id=google_user_info['id']
            )
        
        elif provider == "apple":
            # Apple token verification logic buraya gelecek
            # Şimdilik basit bir implementation
            raise HTTPException(status_code=501, detail="Apple conversion not implemented yet")
        
        else:
            raise HTTPException(status_code=400, detail="Unsupported provider")
        
        # Anonymous kullanıcının kullanım verilerini yeni kullanıcıya aktar (opsiyonel)
        if anonymous_usage.get("count", 0) > 0:
            user_ref = db.collection('users').document(new_user_id)
            user_ref.update({
                "usage.transferred_from_anonymous": anonymous_usage.get("count", 0),
                "conversion_date": firestore.SERVER_TIMESTAMP
            })
        
        # Anonymous cache'i temizle
        from routers.outfits import ANONYMOUS_CACHE
        if user_id in ANONYMOUS_CACHE:
            del ANONYMOUS_CACHE[user_id]
        
        # Yeni JWT token oluştur
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": new_user_id}, expires_delta=access_token_expires
        )
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user_info": user_info,
            "converted_from_anonymous": True,
            "anonymous_usage_transferred": anonymous_usage.get("count", 0)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Anonymous conversion error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to convert anonymous user"
        )

@router.get("/auth/anonymous/status")
async def get_anonymous_status(
    request: Request,
    user_data: Tuple[str, bool] = Depends(get_current_user_id)
):
    """
    Anonymous kullanıcının mevcut durumunu döndürür.
    """
    user_id, is_anonymous = user_data
    
    if not is_anonymous:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This endpoint is only for anonymous users"
        )
    
    try:
        # Anonymous cache'den kullanım bilgilerini al
        from routers.outfits import get_anonymous_user_usage, PLAN_LIMITS
        
        usage_data = get_anonymous_user_usage(user_id)
        daily_limit = PLAN_LIMITS.get("anonymous", 1)
        current_usage = usage_data.get("count", 0)
        remaining = max(0, daily_limit - current_usage)
        
        return {
            "session_id": user_id,
            "plan": "anonymous",
            "usage": {
                "current_usage": current_usage,
                "daily_limit": daily_limit,
                "remaining": remaining,
                "date": usage_data.get("date")
            },
            "is_anonymous": True
        }
        
    except Exception as e:
        print(f"Anonymous status error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get anonymous status"
        )

@router.post("/api/users/update-info")
async def update_user_info(
    request_data: UserInfoUpdate,
    user_id: str = Depends(require_authenticated_user)
):
    """Sadece authenticated kullanıcılar için bilgi güncelleme"""
    try:
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Bilgileri güncelle ve profili tamamlandı olarak işaretle
        update_data = {
            "fullname": request_data.name,
            "gender": request_data.gender,
            "updatedAt": firestore.SERVER_TIMESTAMP,
            "profile_incomplete": False
        }
        
        user_ref.update(update_data)
        
        # Client'a yönlendirme yapması için net bir sinyal gönder
        return {
            "message": "User info updated successfully", 
            "profile_complete": True  # <-- BU ALANIN EKLENMESİ ÇOK ÖNEMLİ
        }
        
    except Exception as e:
        print(f"Update user info error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update user info"
        )

# Yardımcı fonksiyonlar (değişmedi)
async def get_google_user_info(access_token: str):
    """Google API'den kullanıcı bilgilerini al"""
    try:
        response = requests.get(
            f"https://www.googleapis.com/oauth2/v2/userinfo?access_token={access_token}"
        )
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        print(f"Google API error: {e}")
        return None

async def verify_apple_token(identity_token: str):
    """Apple identity token'ı doğrula"""
    try:
        # Apple'ın public keylerini al
        apple_keys_response = requests.get("https://appleid.apple.com/auth/keys")
        apple_keys = apple_keys_response.json()
        
        # Token'ı decode et
        header = jwt.get_unverified_header(identity_token)
        
        # Uygun key'i bul ve token'ı doğrula
        for key in apple_keys['keys']:
            if key['kid'] == header['kid']:
                try:
                    decoded_token = jwt.decode(
                        identity_token,
                        key=jwt.algorithms.RSAAlgorithm.from_jwk(key),
                        algorithms=['RS256'],
                        audience=settings.APPLE_CLIENT_ID if hasattr(settings, 'APPLE_CLIENT_ID') else None,
                        issuer='https://appleid.apple.com'
                    )
                    return decoded_token
                except Exception as decode_error:
                    print(f"Token decode error: {decode_error}")
                    continue
        
        return None
    except Exception as e:
        print(f"Apple token verification error: {e}")
        return None

async def create_or_update_user(uid: str, email: str, name: str, provider: str, provider_id: str):
    """Kullanıcıyı Firestore'da oluştur veya güncelle"""
    try:
        user_ref = db.collection('users').document(uid)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            # Yeni kullanıcı oluştur
            user_data = {
                "email": email,
                "fullname": name,
                "provider": provider,
                "provider_id": provider_id,
                "plan": "free",
                "createdAt": firestore.SERVER_TIMESTAMP,
                "usage": {
                    "count": 0, 
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "rewarded_count": 0
                }
            }
            
            # Eğer name ve email'dan gender çıkarabilirsek ekleyelim
            # Yoksa complete-profile'da kullanıcı kendisi girecek
            if name and len(name) > 1:
                # Bu basit bir yaklaşım, daha sofistike gender detection de eklenebilir
                user_data["profile_incomplete"] = True  # Client bu field'ı kontrol edebilir
            
            user_ref.set(user_data)
            print(f"✅ New user created: {uid}")
        else:
            # Mevcut kullanıcıyı güncelle
            user_data = user_doc.to_dict()
            update_data = {
                "email": email,
                "provider": provider,
                "provider_id": provider_id,
                "updatedAt": firestore.SERVER_TIMESTAMP
            }
            
            # Sadece boşsa güncelle
            if not user_data.get("fullname") and name:
                update_data["fullname"] = name
                
            user_ref.update(update_data)
            user_data.update(update_data)
            print(f"✅ Existing user updated: {uid}")
        
        # Güncel user data'yı al
        updated_doc = user_ref.get()
        updated_data = updated_doc.to_dict()
        
        # Profil completeness kontrolü
        profile_complete = bool(
            updated_data.get("fullname") and 
            updated_data.get("gender")
        )
        
        return {
            "uid": uid,
            "email": updated_data.get("email"),
            "name": updated_data.get("fullname"),
            "fullname": updated_data.get("fullname"),
            "gender": updated_data.get("gender"),
            "birthDate": updated_data.get("birthDate"),
            "plan": updated_data.get("plan", "free"),
            "provider": provider,
            "profile_complete": profile_complete  # Client bu field'ı kontrol edebilir
        }
        
    except Exception as e:
        print(f"Database error: {e}")
        raise e