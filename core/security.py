# core/security.py - Anonymous kullanıcı desteği eklendi

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from .config import settings
import secrets
import hashlib
import time

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token", auto_error=False)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

def create_anonymous_user_id(request: Request) -> str:
    """
    Client IP ve User-Agent'tan anonim kullanıcı ID'si oluşturur.
    Aynı cihaz/IP'den gelen istekler aynı ID'yi alır.
    """
    # Client IP'sini al
    client_ip = request.client.host
    if hasattr(request, "headers"):
        # Proxy arkasındaysa gerçek IP'yi almaya çalış
        forwarded_ip = request.headers.get("X-Forwarded-For") or request.headers.get("X-Real-IP")
        if forwarded_ip:
            client_ip = forwarded_ip.split(",")[0].strip()
    
    # User-Agent'ı al
    user_agent = request.headers.get("User-Agent", "unknown")
    
    # Unique bir string oluştur
    unique_string = f"{client_ip}_{user_agent}_{settings.SECRET_KEY}"
    
    # SHA256 hash'ini al ve kısalt
    hash_object = hashlib.sha256(unique_string.encode('utf-8'))
    hash_hex = hash_object.hexdigest()
    
    # Anonim kullanıcı prefix'i ile döndür
    return f"anon_{hash_hex[:16]}"

async def get_current_user_id(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme)
) -> Tuple[str, bool]:
    """
    Kullanıcı ID'sini ve anonim olup olmadığını döndürür.
    Returns: (user_id, is_anonymous)
    """
    if token:
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            user_id: str = payload.get("sub")
            
            if user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Could not validate credentials",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            # --- YENİ EKLENEN KONTROL ---
            # Token payload'ında 'type' alanı 'anonymous' ise kullanıcı anonimdir.
            user_type: Optional[str] = payload.get("type")
            if user_type == "anonymous":
                return user_id, True  # Token'ı olan anonim kullanıcı

            return user_id, False  # Authenticated (kimliği doğrulanmış) kullanıcı
            
        except JWTError:
            # Token geçersizse veya yoksa, anonim kullanıcı olarak devam et
            pass
    
    # Token yoksa veya geçersizse anonim kullanıcı oluştur
    anonymous_id = create_anonymous_user_id(request)
    return anonymous_id, True

# Geriye uyumluluk için eski fonksiyonu koruyalım
async def get_current_user_id_legacy(token: str = Depends(oauth2_scheme)):
    """Eski kod için geriye uyumlu fonksiyon - sadece authenticated kullanıcılar"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        return user_id
    except JWTError:
        raise credentials_exception

# Sadece authenticated kullanıcılar için dependency
async def require_authenticated_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme)
) -> str:
    """Sadece authenticated kullanıcılara izin verir"""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user_id
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )