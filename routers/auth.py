from fastapi import APIRouter, Depends, HTTPException, status, Request, Body
from datetime import timedelta, datetime
from firebase_admin import firestore
import requests
import jwt
import uuid
from typing import Optional, Tuple
from pydantic import BaseModel
import secrets
from core.security import create_access_token, get_current_user_id, require_authenticated_user
from core.usage import get_or_create_daily_usage
from core.config import settings
from schemas import AnonymousSessionStart, AnonymousSessionResponse, UserProfileResponse

router = APIRouter()
db = firestore.client()

class GoogleAuthRequest(BaseModel):
    access_token: str

class AppleAuthRequest(BaseModel):
    identity_token: str
    authorization_code: Optional[str] = None
    user_info: Optional[dict] = None

class UserInfoUpdate(BaseModel):
    name: str
    gender: str

class AnonymousUserInfo(BaseModel):
    session_id: str
    language: Optional[str] = "en"
    gender: Optional[str] = "unisex"

@router.post("/auth/google")
async def google_auth(request: GoogleAuthRequest):
    try:
        google_user_info = await get_google_user_info(request.access_token)
        if not google_user_info:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google access token")
        
        user_id = f"google_{google_user_info['id']}"
        user_info = await create_or_update_user(
            uid=user_id, email=google_user_info['email'],
            name=google_user_info.get('name', ''), provider='google', provider_id=google_user_info['id']
        )
        
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(data={"sub": user_id}, expires_delta=access_token_expires)
        
        return {"access_token": access_token, "token_type": "bearer", "user_info": user_info}
    except Exception as e:
        print(f"Google auth error: {e}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google authentication failed")

@router.post("/auth/apple")
async def apple_auth(request: AppleAuthRequest):
    try:
        apple_user_info = await verify_apple_token(request.identity_token)
        if not apple_user_info or not isinstance(apple_user_info, dict):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Apple identity token")
        
        full_name = ""
        if request.user_info and isinstance(request.user_info.get('name'), dict):
            name_data = request.user_info['name']
            full_name = f"{name_data.get('givenName', '')} {name_data.get('familyName', '')}".strip()
        elif request.user_info and isinstance(request.user_info.get('name'), str):
             full_name = request.user_info['name']

        if not full_name:
            if apple_user_info.get('email'):
                full_name = apple_user_info.get('email').split('@')[0]
            else:
                apple_sub = apple_user_info.get('sub', secrets.token_hex(4))
                full_name = f"User_{apple_sub[:8]}"
        
        user_id = f"apple_{apple_user_info['sub']}"
        user_info = await create_or_update_user(
            uid=user_id, email=apple_user_info.get('email', ''), name=full_name,
            provider='apple', provider_id=apple_user_info['sub']
        )
        
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(data={"sub": user_id}, expires_delta=access_token_expires)
        
        return {"access_token": access_token, "token_type": "bearer", "user_info": user_info}
    except Exception as e:
        print(f"Apple auth error: {e}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Apple authentication failed.")

@router.post("/auth/anonymous", response_model=AnonymousSessionResponse)
async def start_anonymous_session(request: Request, session_data: AnonymousSessionStart):
    user_id = session_data.anonymous_id
    user_ref = None
    user_doc = None

    if user_id and user_id.startswith("anon_"):
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        if not user_doc.exists:
            user_id = None
    
    if not user_id:
        user_id = f"anon_{uuid.uuid4().hex[:16]}"
        user_ref = db.collection('users').document(user_id)
        
        user_data = {
            "createdAt": firestore.SERVER_TIMESTAMP,
            "plan": "free",
            "language": session_data.language,
            "gender": session_data.gender,
            "profile_complete": False, 
            "is_anonymous": True
        }
        user_ref.set(user_data)
        user_doc = user_ref.get()

    user_info_dict = user_doc.to_dict()
    
    fullname = user_info_dict.get("fullname")
    gender = user_info_dict.get("gender")
    is_profile_complete = bool(fullname and gender and gender != 'unisex')

    if user_info_dict.get("profile_complete") != is_profile_complete:
         user_ref.update({"profile_complete": is_profile_complete})

    user_response = UserProfileResponse(
        user_id=user_id,
        fullname=user_info_dict.get("fullname"),
        email=user_info_dict.get("email"),
        gender=user_info_dict.get("gender"),
        plan=user_info_dict.get("plan", "free"),
        usage=get_or_create_daily_usage(user_id),
        created_at=user_info_dict.get("createdAt"),
        isAnonymous=True,
        profile_complete=is_profile_complete
    )

    access_token = create_access_token(data={"sub": user_id, "type": "anonymous"})
    
    return AnonymousSessionResponse(
        session_id=user_id,
        access_token=access_token,
        user_info=user_response
    )

@router.post("/auth/convert-anonymous")
async def convert_anonymous_to_authenticated(
    request: Request,
    conversion_data: dict = Body(...),
    user_data: Tuple[str, bool] = Depends(get_current_user_id)
):
    user_id, is_anonymous = user_data
    
    if not is_anonymous:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This endpoint is only for guest users"
        )
    
    try:
        oauth_token = conversion_data.get("oauth_token")
        provider = conversion_data.get("provider")
        
        if not oauth_token or not provider:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth token and provider are required")
        
        guest_user_ref = db.collection('users').document(user_id)
        guest_user_doc = guest_user_ref.get()
        guest_usage = guest_user_doc.to_dict().get("usage", {}) if guest_user_doc.exists else {}
        
        if provider == "google":
            google_user_info = await get_google_user_info(oauth_token)
            if not google_user_info:
                raise HTTPException(status_code=401, detail="Invalid Google token")
            
            new_user_id = f"google_{google_user_info['id']}"
            user_info = await create_or_update_user(
                uid=new_user_id, email=google_user_info['email'], name=google_user_info.get('name', ''),
                provider='google', provider_id=google_user_info['id']
            )
        
        elif provider == "apple":
            apple_user_info = await verify_apple_token(oauth_token)
            if not apple_user_info:
                raise HTTPException(status_code=401, detail="Invalid Apple token")

            full_name = conversion_data.get("name", "") or (apple_user_info.get('email', '').split('@')[0] if apple_user_info.get('email') else f"User_{apple_user_info['sub'][:8]}")
            
            new_user_id = f"apple_{apple_user_info['sub']}"
            user_info = await create_or_update_user(
                uid=new_user_id, email=apple_user_info.get('email', ''), name=full_name,
                provider='apple', provider_id=apple_user_info['sub']
            )
        
        else:
            raise HTTPException(status_code=400, detail="Unsupported provider")
        
        if guest_usage.get("count", 0) > 0:
            user_ref = db.collection('users').document(new_user_id)
            user_ref.update({
                "usage": guest_usage,
                "conversion_date": firestore.SERVER_TIMESTAMP
            })

        guest_user_ref.delete()
        
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(data={"sub": new_user_id}, expires_delta=access_token_expires)
        
        return {
            "access_token": access_token, "token_type": "bearer",
            "user_info": user_info, "converted_from_anonymous": True,
            "anonymous_usage_transferred": guest_usage.get("count", 0)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Guest user conversion error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to convert guest user")

@router.get("/auth/anonymous/status")
async def get_anonymous_status(
    request: Request,
    user_data: Tuple[str, bool] = Depends(get_current_user_id)
):
    user_id, is_anonymous = user_data
    
    if not is_anonymous:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This endpoint is only for guest users")
    
    try:
        usage_status = get_or_create_daily_usage(user_id)
        
        return {
            "session_id": user_id, "plan": "free",
            "usage": {
                "current_usage": usage_status.current_usage,
                "daily_limit": usage_status.daily_limit,
                "remaining": usage_status.remaining,
                "date": usage_status.date
            },
            "is_anonymous": True
        }
    except Exception as e:
        print(f"Guest status error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get guest status")

@router.post("/api/users/update-info")
async def update_user_info(
    request_data: UserInfoUpdate,
    user_id: str = Depends(require_authenticated_user)
):
    try:
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
        update_data = {
            "fullname": request_data.name, "gender": request_data.gender,
            "updatedAt": firestore.SERVER_TIMESTAMP, "profile_incomplete": False
        }
        user_ref.update(update_data)
        
        return {"message": "User info updated successfully", "profile_complete": True}
    except Exception as e:
        print(f"Update user info error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update user info")

async def get_google_user_info(access_token: str):
    try:
        response = requests.get(f"https://www.googleapis.com/oauth2/v2/userinfo?access_token={access_token}")
        if response.status_code == 200: return response.json()
        return None
    except Exception as e:
        print(f"Google API error: {e}")
        return None

async def verify_apple_token(identity_token: str):
    try:
        apple_keys_response = requests.get("https://appleid.apple.com/auth/keys")
        apple_keys = apple_keys_response.json()
        header = jwt.get_unverified_header(identity_token)
        for key in apple_keys['keys']:
            if key['kid'] == header['kid']:
                try:
                    return jwt.decode(
                        identity_token, key=jwt.algorithms.RSAAlgorithm.from_jwk(key), algorithms=['RS256'],
                        audience=settings.APPLE_CLIENT_ID if hasattr(settings, 'APPLE_CLIENT_ID') else None,
                        issuer='https://appleid.apple.com'
                    )
                except Exception as decode_error:
                    print(f"Token decode error: {decode_error}")
                    continue
        return None
    except Exception as e:
        print(f"Apple token verification error: {e}")
        return None

async def create_or_update_user(uid: str, email: str, name: str, provider: str, provider_id: str):
    try:
        user_ref = db.collection('users').document(uid)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            user_data = {
                "email": email, "fullname": name, "provider": provider,
                "provider_id": provider_id, "plan": "free",
                "createdAt": firestore.SERVER_TIMESTAMP,
                "usage": {"count": 0, "date": datetime.now().strftime("%Y-%m-%d"), "rewarded_count": 0},
                "is_anonymous": False
            }
            if name and len(name) > 1:
                user_data["profile_incomplete"] = True
            user_ref.set(user_data)
        else:
            user_data = user_doc.to_dict()
            update_data = {
                "email": email, "provider": provider, "provider_id": provider_id,
                "updatedAt": firestore.SERVER_TIMESTAMP,
                "is_anonymous": False
            }
            if not user_data.get("fullname") and name:
                update_data["fullname"] = name
            user_ref.update(update_data)
            user_data.update(update_data)
        
        updated_doc = user_ref.get()
        updated_data = updated_doc.to_dict()
        profile_complete = bool(updated_data.get("fullname") and updated_data.get("gender"))
        
        return {
            "uid": uid, "email": updated_data.get("email"), "name": updated_data.get("fullname"),
            "fullname": updated_data.get("fullname"), "gender": updated_data.get("gender"),
            "birthDate": updated_data.get("birthDate"), "plan": updated_data.get("plan", "free"),
            "provider": provider, "profile_complete": profile_complete
        }
    except Exception as e:
        print(f"Database error: {e}")
        raise e