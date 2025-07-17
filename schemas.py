# schemas.py

from pydantic import BaseModel, Field, validator
from typing import List, Optional, Union, Any, Dict

# =================================================================
# Temel ve Yetkilendirme Modelleri (Mevcut yapı korundu)
# =================================================================

class Token(BaseModel):
    access_token: str
    token_type: str

class IdToken(BaseModel):
    id_token: str

class GoogleAuthRequest(BaseModel):
    access_token: str

class AppleAuthRequest(BaseModel):
    identity_token: str
    authorization_code: Optional[str] = None
    user_info: Optional[dict] = None

class UserInfoUpdate(BaseModel):
    name: str
    gender: str
    birthDate: str

# =================================================================
# YENİ ve GÜNCELLENMİŞ MODELLER (Yeni Mimarimiz İçin)
# =================================================================

class OptimizedClothingItem(BaseModel):
    """
    YENİ: Client tarafından akıllıca filtrelendikten sonra gönderilen,
    optimize edilmiş ve hafifletilmiş kıyafet modeli.
    """
    id: str
    name: str
    category: str
    colors: List[str]
    season: List[str]
    style: List[str]

class OptimizedOutfit(BaseModel):
    """
    YENİ: Tekrarları önlemek için gönderilen, son 5 kombinin
    optimize edilmiş yapısı. outfits.py'deki `Outfit` ile aynı yapıya sahip.
    """
    items: List[str]
    occasion: str
    weather: Optional[str] = None
    date: str

class RequestContext(BaseModel):
    """
    GÜNCELLENDİ: API'nin isteği daha iyi analiz edebilmesi için
    client'tan gönderilen meta veri.
    """
    total_wardrobe_size: int
    filtered_wardrobe_size: int
    user_plan: str
    optimization_applied: bool

class PinterestLink(BaseModel):
    """Pinterest linki için yanıt modeli."""
    title: str
    url: str

class OutfitRequest(BaseModel):
    """
    GÜNCELLENDİ: /suggest-outfit endpoint'i için ana istek modeli.
    Artık optimize edilmiş modelleri kullanır.
    """
    language: str = Field(..., alias='language')
    gender: Optional[str] = Field(None, alias='gender')
    plan: str = Field(..., alias='plan')

    # EN KRİTİK DEĞİŞİKLİK: Artık hafifletilmiş modelleri bekliyoruz.
    wardrobe: List[OptimizedClothingItem] = Field(..., alias='wardrobe')
    last_5_outfits: List[OptimizedOutfit] = Field(..., alias='last_5_outfits')
    
    weather_condition: str = Field(..., alias='weather_condition')
    occasion: str = Field(..., alias='occasion')
    context: RequestContext = Field(..., alias='context')  # Artık zorunlu ve tam
    
    class Config:
        # Pydantic V2 için doğru yapılandırma
        populate_by_name = True

class SuggestedItem(BaseModel):
    id: str
    name: str
    category: str
    subcategory: Optional[str] = None

class OutfitResponse(BaseModel):
    """Yanıt modeli. Değişiklik gerekmiyor."""
    items: List[SuggestedItem]
    description: str
    suggestion_tip: Optional[str] = None
    pinterest_links: Optional[List[PinterestLink]] = None

# =================================================================
# MEVCUT (ESKİ) YAPI - Gerekliyse Tutulabilir
# =================================================================

class ClothingItem(BaseModel):
    """
    Mevcut kodun başka bir yerinde hala kullanılıyorsa bu detaylı model tutulur.
    Pydantic V2 uyarıları düzeltildi.
    """
    id: str
    name: str
    category: str
    subcategory: Optional[str] = None
    color: Optional[str] = None
    colors: Optional[List[str]] = None
    season: List[str]
    style: Union[str, List[str]]
    notes: Optional[str] = None
    createdAt: Optional[str] = None
    isImageMissing: Optional[bool] = False

    @validator('colors', pre=True, always=True)
    def ensure_colors_from_color(cls, v, values):
        if v is None and 'color' in values and values['color']:
            return [values['color']]
        return v
    
    @validator('color', pre=True, always=True)
    def ensure_color_from_colors(cls, v, values):
        if v is None and 'colors' in values and values['colors']:
            return values['colors'][0]
        return v

    class Config:
        # Pydantic V2 için doğru yapılandırma
        populate_by_name = True

# =================================================================
# Diğer Mevcut Modeller (Değişiklik Gerekmiyor)
# =================================================================

class ProfileInit(BaseModel):
    gender: str
    fullname: str
    birthDate: Optional[str] = None

class UsageStatusResponse(BaseModel):
    plan: str
    current_usage: int
    daily_limit: Union[int, str]
    remaining: Union[int, str]
    is_unlimited: bool
    date: str
    percentage_used: Optional[float] = None

class PlanUpdateRequest(BaseModel):
    plan: str = Field(..., description="New plan (free, premium)")

class PurchaseVerification(BaseModel):
    customer_info: dict