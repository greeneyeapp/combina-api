import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
import json
import asyncio

# --- DEĞİŞİKLİK: Firebase başlatma kodları kaldırıldı ---
# Bu işlem artık 'core.database' modülü ilk yüklendiğinde otomatik olarak yapılıyor.
# Sadece 'db' nesnesini import etmemiz, başlatma için yeterlidir.
from core.database import db
from core.config import settings

# Router'ları import et
# Bu satır, diğer dosyaların 'core.database' üzerinden 'db'ye erişmesini sağlar.
from routers import auth, outfits, weather, users 

app = FastAPI(
    title="Combina API", 
    description="Fashion outfit suggestion API with anonymous user support",
    version="2.0.0"
)

# 422 HATA DEBUG MIDDLEWARE
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
                    print(f"      {key}: {type(value).__name__} = {value}")
                    
            # Context varsa log'la
            if 'context' in body_json:
                print(f"❌ Context: {body_json['context']}")
                
    except Exception as e:
        print(f"❌ Could not parse request body: {e}")
    
    # Validation hatalarını detaylı log'la
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

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Production'da daha kısıtlayıcı olun
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Root endpoint'i
@app.get("/")
async def root_redirect():
    return RedirectResponse(url="/docs")

@app.get("/health")
async def health_check():
    """API durumu kontrolü - anonymous kullanıcılar için de erişilebilir"""
    return {
        "status": "healthy",
        "service": "Combina API",
        "version": "2.0.0",
        "features": [
            "authenticated_users",
            "anonymous_users", 
            "outfit_suggestions",
            "weather_integration",
            "multilingual_support"
        ]
    }

# Router'ları dahil et
app.include_router(auth.router)
app.include_router(weather.router)
app.include_router(outfits.router)
app.include_router(users.router)
app.include_router(users.webhook_router)

# Startup event'i
@app.on_event("startup")
async def startup_event():
    """Uygulama başlangıcında gerekli işlemleri yap"""
    print("🚀 Combina API starting up...")
    print("✅ Anonymous user support enabled")
    print("✅ Authenticated user support enabled")
    print("✅ Multi-language outfit suggestions ready")
    
    # Anonymous cache temizleme scheduler'ı başlat (isteğe bağlı)
    from routers.outfits import cleanup_anonymous_cache
    
    async def periodic_cleanup():
        """Her 1 saatte bir anonymous cache'i temizle"""
        while True:
            await asyncio.sleep(3600)  # 1 saat bekle
            try:
                cleanup_anonymous_cache()
            except Exception as e:
                print(f"❌ Anonymous cache cleanup error: {e}")
    
    # Arka planda cleanup task'ını başlat
    asyncio.create_task(periodic_cleanup())

if __name__ == "__main__":
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=9002, 
        reload=True,
        log_level="info"
    )
