# schemas.py

from pydantic import BaseModel, Field, validator
from typing import List, Optional, Union, Any, Dict

# Temel ve Yetkilendirme Modelleri
class Token(BaseModel):
    access_token: str
    token_type: str

class GoogleAuthRequest(BaseModel):
    access_token: str

class AppleAuthRequest(BaseModel):
    identity_token: str
    authorization_code: Optional[str] = None
    user_info: Optional[dict] = None

class UserInfoUpdate(BaseModel):
    name: str
    gender: str

# YENİ MİMARİ İÇİN GÜNCELLENMİŞ MODELLER
class OptimizedClothingItem(BaseModel):
    """Client tarafından filtrelenmiş, optimize kıyafet modeli."""
    id: str
    name: str
    category: str
    colors: List[str]
    season: List[str]
    style: List[str]

class OptimizedOutfit(BaseModel):
    """Optimize edilmiş son 5 kombin yapısı."""
    items: List[str]
    occasion: str
    weather: Optional[str] = None
    date: str

class RequestContext(BaseModel):
    """Client'tan gönderilen meta veri."""
    total_wardrobe_size: int
    filtered_wardrobe_size: int
    user_plan: str
    optimization_applied: bool

class PinterestLink(BaseModel):
    """Pinterest linki için yanıt modeli."""
    title: str
    url: str

class OutfitRequest(BaseModel):
    """/suggest-outfit endpoint'i için ana istek modeli."""
    language: str
    plan: str
    gender: str
    wardrobe: List[OptimizedClothingItem]
    last_5_outfits: List[OptimizedOutfit]
    weather_condition: str
    occasion: str
    context: RequestContext
    
    class Config:
        populate_by_name = True

class SuggestedItem(BaseModel):
    id: str
    name: str
    category: str

class OutfitResponse(BaseModel):
    """/suggest-outfit endpoint'i için son kullanıcıya dönen yanıt modeli."""
    items: List[SuggestedItem]
    description: str
    suggestion_tip: str
    pinterest_links: Optional[List[PinterestLink]] = None

# Mevcut diğer modeller (Pydantic V2 uyarıları giderildi)
class ClothingItem(BaseModel):
    """Eski, detaylı kıyafet modeli (başka bir yerde kullanılıyorsa)."""
    id: str; name: str; category: str; subcategory: Optional[str] = None
    color: Optional[str] = None; colors: Optional[List[str]] = None
    season: List[str]; style: Union[str, List[str]]; notes: Optional[str] = None
    createdAt: Optional[str] = None; isImageMissing: Optional[bool] = False

    @validator('colors', pre=True, always=True)
    def ensure_colors_from_color(cls, v, values):
        if v is None and 'color' in values and values['color']: return [values['color']]
        return v
    
    @validator('color', pre=True, always=True)
    def ensure_color_from_colors(cls, v, values):
        if v is None and 'colors' in values and values['colors']: return values['colors'][0]
        return v

    class Config: populate_by_name = True

class ProfileInit(BaseModel):
    gender: str; fullname: str

class UsageStatusResponse(BaseModel):
    plan: str; current_usage: int; daily_limit: Union[int, str]; remaining: Union[int, str]
    is_unlimited: bool; date: str; percentage_used: Optional[float] = None

class PlanUpdateRequest(BaseModel):
    plan: str = Field(..., description="New plan (free, premium)")

class PurchaseVerification(BaseModel):
    customer_info: dict
    
class AnonymousSessionStart(BaseModel):
    session_id: str
    language: str
    gender: str
    anonymous_id: Optional[str] = None

# --- YENİ EKLENEN MODELLER ---

class DailyUsage(BaseModel):
    """Kullanım durumu için model."""
    daily_limit: Union[int, str]
    rewarded_count: int
    current_usage: int
    remaining: Union[int, str]
    percentage_used: float
    date: str

class UserProfileResponse(BaseModel):
    """Kullanıcı profili yanıtı için genel model."""
    user_id: str
    fullname: Optional[str] = None
    email: Optional[str] = None
    gender: Optional[str] = None
    plan: str
    usage: DailyUsage
    created_at: Optional[Any] = None
    isAnonymous: bool
    profile_complete: bool

class AnonymousSessionResponse(BaseModel):
    """Anonim oturum başlatma yanıtı için model."""
    session_id: str
    access_token: str
    user_info: UserProfileResponse
