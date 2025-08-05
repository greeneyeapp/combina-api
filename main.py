import uvicorn
import firebase_admin
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from firebase_admin import credentials, firestore
import json
import asyncio

from core.config import settings

try:
    cred = credentials.Certificate(settings.GOOGLE_APPLICATION_CREDENTIALS)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    print("✅ Firebase Admin SDK başarıyla başlatıldı.")
except Exception as e:
    print(f"❌ Firebase Admin SDK başlatılırken hata oluştu: {e}")
    raise e

db = firestore.client()

from routers import auth, outfits, weather, users 

app = FastAPI(
    title="Combina API", 
    description="Fashion outfit suggestion API with unified user model",
    version="2.1.0"
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    print(f"\n❌ 422 VALIDATION ERROR at {request.url}")
    print(f"❌ Method: {request.method}")
    try:
        body = await request.body()
        if body:
            body_str = body.decode('utf-8')
            body_json = json.loads(body_str)
            print(f"❌ Request body keys: {list(body_json.keys())}")
            if 'wardrobe' in body_json and body_json['wardrobe']:
                sample_item = body_json['wardrobe'][0]
                print(f"❌ Sample wardrobe item keys: {list(sample_item.keys())}")
                print(f"❌ Sample wardrobe item values:")
                for key, value in sample_item.items():
                    print(f"      {key}: {type(value).__name__} = {value}")
            if 'context' in body_json:
                print(f"❌ Context: {body_json['context']}")
    except Exception as e:
        print(f"❌ Could not parse request body: {e}")
    
    print(f"❌ VALIDATION ERRORS ({len(exc.errors())} total):")
    for i, error in enumerate(exc.errors()):
        print(f"  Error {i+1}:")
        print(f"     Field: {error.get('loc')}")
        print(f"     Message: {error.get('msg')}")
        print(f"     Type: {error.get('type')}")
        print(f"     Input: {str(error.get('input', 'N/A'))[:100]}...")
        print("     ---")
    print("❌ END OF VALIDATION ERRORS\n")
    
    return JSONResponse(
        status_code=422,
        content={
            "detail": exc.errors(),
            "message": "Request validation failed",
            "debug": {
                "url": str(request.url),
                "method": request.method,
                "error_count": len(exc.errors())
            }
        }
    )

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root_redirect():
    return RedirectResponse(url="/docs")

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "Combina API",
        "version": "2.1.0",
        "features": [
            "authenticated_users",
            "guest_users", 
            "outfit_suggestions",
            "weather_integration",
            "multilingual_support"
        ]
    }

app.include_router(auth.router)
app.include_router(weather.router)
app.include_router(outfits.router)
app.include_router(users.router)
app.include_router(users.webhook_router)

@app.on_event("startup")
async def startup_event():
    print("🚀 Combina API starting up...")
    print("✅ Guest user support enabled (as 'free' plan)")
    print("✅ Authenticated user support enabled")
    print("✅ Multi-language outfit suggestions ready")
    # --- DEĞİŞİKLİK: Anonymous cache temizleme ile ilgili tüm bölüm kaldırıldı ---

if __name__ == "__main__":
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=9002, 
        reload=True,
        log_level="info"
    )