import httpx
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timedelta

from core.config import settings
from core.security import get_current_user_id

router = APIRouter(
    prefix="/api",
    tags=["weather"],
    dependencies=[Depends(get_current_user_id)]
)

WEATHER_CACHE = {}
CACHE_DURATION = timedelta(hours=1)

async def _get_city_name_from_geocoding(lat: float, lon: float) -> str:
    """Reverse geocoding API'sini kullanarak şehir ismini al"""
    url = "http://api.openweathermap.org/geo/1.0/reverse"
    params = {
        "lat": lat,
        "lon": lon,
        "limit": 1,
        "appid": settings.OPENWEATHER_API_KEY
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            if data and len(data) > 0:
                location = data[0]
                # Önce state/il bilgisini kontrol et, yoksa name'i kullan
                city_name = location.get("state") or location.get("name")
                return city_name
            else:
                return f"{round(lat, 2)}_{round(lon, 2)}"
        except Exception:
            return f"{round(lat, 2)}_{round(lon, 2)}"

async def _get_city_name_from_weather(lat: float, lon: float) -> str:
    """Weather API'sinden şehir ismini al (fallback)"""
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "lat": lat,
        "lon": lon,
        "appid": settings.OPENWEATHER_API_KEY,
        "units": "metric",
        "lang": "en"
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("name", f"{round(lat, 2)}_{round(lon, 2)}")
        except Exception:
            return f"{round(lat, 2)}_{round(lon, 2)}"

async def _get_city_name(lat: float, lon: float) -> str:
    """Önce geocoding, başarısız olursa weather API'sini kullan"""
    # Önce reverse geocoding dene
    city_name = await _get_city_name_from_geocoding(lat, lon)
    
    # Eğer sadece koordinat döndüyse, weather API'sini dene
    if "_" in city_name and city_name.replace(".", "").replace("_", "").replace("-", "").isdigit():
        city_name = await _get_city_name_from_weather(lat, lon)
    
    return city_name

@router.get("/weather")
async def get_weather_data(lat: float, lon: float):
    city_name = await _get_city_name(lat, lon)
    cache_key = f"weather_{city_name.lower()}"
    current_time = datetime.utcnow()

    # Cache kontrolü
    if cache_key in WEATHER_CACHE:
        cached_data = WEATHER_CACHE[cache_key]
        if current_time - cached_data["timestamp"] < CACHE_DURATION:
            return cached_data["data"]

    # API'den güncel veri çek
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "lat": lat,
        "lon": lon,
        "appid": settings.OPENWEATHER_API_KEY,
        "units": "metric",
        "lang": "en"
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            weather_data = response.json()

            # Cache için şehir ismini kullan
            cache_city = city_name.lower()
            final_cache_key = f"weather_{cache_city}"
            
            WEATHER_CACHE[final_cache_key] = {
                "timestamp": current_time,
                "data": weather_data
            }
            return weather_data
            
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=f"Error from OpenWeatherMap: {e.response.text}")
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="Could not connect to OpenWeatherMap API.")