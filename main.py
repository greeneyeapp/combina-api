import uvicorn
import firebase_admin
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from firebase_admin import credentials
import json

from core.config import settings

# Firebase Admin SDK'yı başlat
try:
    cred = credentials.Certificate(settings.GOOGLE_APPLICATION_CREDENTIALS)
    firebase_admin.initialize_app(cred)
    print("Firebase Admin SDK başarıyla başlatıldı.")
except Exception as e:
    print(f"Firebase Admin SDK başlatılırken hata oluştu: {e}")

# Router'ları import et
from routers import auth, outfits, weather, users 

app = FastAPI(title="Combina API")

# 422 HATA DEBUG MIDDLEWARE - BU KISMI EKLEYİN
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """422 hatalarını detaylı şekilde log'la"""
    
    print(f"\n❌ 422 VALIDATION ERROR at {request.url}")
    print(f"❌ Method: {request.method}")
    
    # Request body'yi almaya çalış
    try:
        body = await request.body()
        if body:
            body_str = body.decode('utf-8')
            body_json = json.loads(body_str)
            print(f"❌ Request body keys: {list(body_json.keys())}")
            
            # Wardrobe sample log'la
            if 'wardrobe' in body_json and body_json['wardrobe']:
                sample_item = body_json['wardrobe'][0]
                print(f"❌ Sample wardrobe item keys: {list(sample_item.keys())}")
                print(f"❌ Sample wardrobe item values:")
                for key, value in sample_item.items():
                    print(f"    {key}: {type(value).__name__} = {value}")
                    
            # Context varsa log'la
            if 'context' in body_json:
                print(f"❌ Context: {body_json['context']}")
                
    except Exception as e:
        print(f"❌ Could not parse request body: {e}")
    
    # Validation hatalarını detaylı log'la
    print(f"❌ VALIDATION ERRORS ({len(exc.errors())} total):")
    for i, error in enumerate(exc.errors()):
        print(f"  Error {i+1}:")
        print(f"    Field: {error.get('loc')}")
        print(f"    Message: {error.get('msg')}")
        print(f"    Type: {error.get('type')}")
        print(f"    Input: {str(error.get('input', 'N/A'))[:100]}...")  # İlk 100 karakter
        print("    ---")
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

# Root endpoint'i sadece bir kere tanımla
@app.get("/")
async def root_redirect():
    return RedirectResponse(url="/docs")

# Router'ları dahil et
app.include_router(auth.router)
app.include_router(weather.router)
app.include_router(outfits.router)

# Users router'ı - hem normal hem webhook router'ını dahil et
app.include_router(users.router)  # /api/users prefix'li endpoints
app.include_router(users.webhook_router)  # /api prefix'li webhook endpoints

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=9002, reload=True)