import uvicorn
import firebase_admin
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from firebase_admin import credentials

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