import uvicorn
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

from routers import auth, outfits, weather, users 

app = FastAPI(
    title="Combina API",
    description="Combina uygulaması için geliştirilen API.",
    version="1.0.1"
)

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

app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(weather.router, prefix="/api/v1/weather", tags=["Weather"])
app.include_router(outfits.router, prefix="/api/v1/outfits", tags=["Outfits"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=9002, reload=True)