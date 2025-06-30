from fastapi import APIRouter, Depends, HTTPException, status
from datetime import timedelta, datetime
from firebase_admin import firestore
import requests
import jwt
from typing import Optional
from pydantic import BaseModel
import secrets
from core.security import create_access_token, get_current_user_id
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
    birthDate: str

# Google OAuth endpoint
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
        print(f"Apple auth error: {e}") # Bunu isterseniz kalıcı loglama sisteminiz için saklayabilirsiniz.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Apple authentication failed."
        )

# Kullanıcı bilgi güncelleme endpoint'i
@router.post("/api/users/update-info")
async def update_user_info(
    request: UserInfoUpdate,
    user_id: str = Depends(get_current_user_id)
):
    """Kullanıcı bilgilerini güncelle"""
    try:
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Bilgileri güncelle
        update_data = {
            "fullname": request.name,
            "gender": request.gender,
            "birthDate": request.birthDate,
            "updatedAt": firestore.SERVER_TIMESTAMP
        }
        
        # Yaş hesapla
        try:
            birth_date = datetime.fromisoformat(request.birthDate.replace('Z', '+00:00'))
            today = datetime.now()
            age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
            update_data["age"] = age
        except ValueError:
            print(f"Invalid birth date format: {request.birthDate}")
        
        user_ref.update(update_data)
        
        return {"message": "User info updated successfully"}
        
    except Exception as e:
        print(f"Update user info error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update user info"
        )

# Yardımcı fonksiyonlar
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
                "usage": {"count": 0, "date": datetime.now().strftime("%Y-%m-%d")}
            }
            user_ref.set(user_data)
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
            if not user_data.get("fullname"):
                update_data["fullname"] = name
                
            user_ref.update(update_data)
            user_data.update(update_data)
        
        # Güncel user data'yı al
        updated_doc = user_ref.get()
        updated_data = updated_doc.to_dict()
        
        return {
            "uid": uid,
            "email": updated_data.get("email"),
            "name": updated_data.get("fullname"),
            "gender": updated_data.get("gender"),
            "birthDate": updated_data.get("birthDate"),
            "plan": updated_data.get("plan", "free"),
            "provider": provider
        }
        
    except Exception as e:
        print(f"Database error: {e}")
        raise e