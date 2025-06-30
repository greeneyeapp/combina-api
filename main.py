# main.py

import uvicorn
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

# Router'ları import et
# Bu kısım, router dosyalarının içindeki URL tanımlarını doğrudan kullanacak.
from routers import auth, outfits, weather, users 

app = FastAPI(
    title="Combina API",
    description="Combina uygulaması için geliştirilen API.",
    version="1.1.0" # Sürümü güncelledik
)

# CORS ayarları
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", tags=["Root"], include_in_schema=False)
async def root_redirect():
    """Ana dizine gelen istekleri /docs adresine yönlendirir."""
    return RedirectResponse(url="/docs")


# --- EN ÖNEMLİ DÜZELTME ---
# Router'ları HİÇBİR prefix eklemeden, orijinal halleriyle dahil ediyoruz.
# Böylece client'ın bildiği URL'ler tekrar çalışacak.

# auth.py içindeki "/auth/google" yolunu aktif eder.
app.include_router(auth.router) 

# outfits.py içindeki "/api" prefix'ini ve "/suggest-outfit" yolunu aktif eder.
app.include_router(outfits.router)

# users.py içindeki yolları aktif eder.
app.include_router(users.router) 

# Diğer router'larınızı da buraya ekleyebilirsiniz.
app.include_router(weather.router)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=9002, reload=True)