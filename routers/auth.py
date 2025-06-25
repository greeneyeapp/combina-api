from fastapi import APIRouter, Depends, HTTPException, status
from datetime import timedelta
from firebase_admin import auth

from core.security import create_access_token
from core.config import settings
from schemas import Token, IdToken

router = APIRouter()

@router.post("/token", response_model=Token)
async def login_for_access_token(token_data: IdToken):
    try:
        decoded_token = auth.verify_id_token(token_data.id_token)
        uid = decoded_token['uid']
    except Exception as e:
        print(f"Token verification error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Firebase ID token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": uid}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}