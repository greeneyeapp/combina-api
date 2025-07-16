from pydantic import BaseModel, Field, validator
from typing import List, Optional, Union
from datetime import datetime

class Token(BaseModel):
    access_token: str
    token_type: str

class IdToken(BaseModel):
    id_token: str

# OAuth için yeni modeller
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

class ClothingItem(BaseModel):
    id: str
    name: str
    category: str
    subcategory: Optional[str] = None
    
    # ÇOK ÖNEMLİ: Hem eski hem yeni format desteği
    color: Optional[str] = None  # Backward compatibility için
    colors: Optional[List[str]] = None  # Yeni çoklu renk desteği
    
    season: List[str]
    style: Union[str, List[str]]  # String veya array desteği
    notes: Optional[str] = None
    createdAt: Optional[str] = None
    
    # YENİ FIELD - Eksik olan field
    isImageMissing: Optional[bool] = False  # Default olarak False
    
    @validator('colors', pre=True, always=True)
    def ensure_colors_from_color(cls, v, values):
        """color field'ından colors array'ini oluştur"""
        if v is None and 'color' in values and values['color']:
            return [values['color']]
        return v
    
    @validator('color', pre=True, always=True)
    def ensure_color_from_colors(cls, v, values):
        """colors array'inden color field'ını oluştur"""
        if v is None and 'colors' in values and values['colors'] and len(values['colors']) > 0:
            return values['colors'][0]
        return v

    class Config:
        allow_population_by_field_name = True
        fields = {
            'createdAt': 'createdAt',
            'subcategory': 'subcategory',
            'isImageMissing': 'isImageMissing'
        }
    id: str
    name: str
    category: str
    subcategory: Optional[str] = None
    
    # ÇOK ÖNEMLİ: Hem eski hem yeni format desteği
    color: Optional[str] = None  # Backward compatibility için
    colors: Optional[List[str]] = None  # Yeni çoklu renk desteği
    
    season: List[str]
    style: Union[str, List[str]]  # String veya array desteği
    notes: Optional[str] = None
    createdAt: Optional[str] = None
    
    @validator('colors', pre=True, always=True)
    def ensure_colors_from_color(cls, v, values):
        """color field'ından colors array'ini oluştur"""
        if v is None and 'color' in values and values['color']:
            return [values['color']]
        return v
    
    @validator('color', pre=True, always=True)
    def ensure_color_from_colors(cls, v, values):
        """colors array'inden color field'ını oluştur"""
        if v is None and 'colors' in values and values['colors'] and len(values['colors']) > 0:
            return values['colors'][0]
        return v

    class Config:
        allow_population_by_field_name = True
        fields = {
            'createdAt': 'createdAt',
            'subcategory': 'subcategory',
        }

class Outfit(BaseModel):
    items: List[str]
    occasion: str
    weather: Optional[str] = None
    date: str
    
    class Config:
        allow_population_by_field_name = True

class RequestContext(BaseModel):
    """Optimize edilmiş veri hakkında context bilgileri"""
    total_wardrobe_size: Optional[int] = None
    filtered_wardrobe_size: Optional[int] = None
    user_plan: Optional[str] = None
    
    class Config:
        allow_population_by_field_name = True

class PinterestLink(BaseModel):
    title: str
    url: str

class OutfitRequest(BaseModel):
    language: str = Field(..., alias='language')
    gender: Optional[str] = Field(None, alias='gender')
    plan: str = Field(..., alias='plan')
    
    wardrobe: List[ClothingItem] = Field(..., alias='wardrobe')
    last_5_outfits: List[Outfit] = Field(..., alias='last_5_outfits')
    weather_condition: str = Field(..., alias='weather_condition')
    occasion: str = Field(..., alias='occasion')
    context: Optional[RequestContext] = Field(None, alias='context')
    
    class Config:
        allow_population_by_field_name = True
        allow_population_by_alias = True

class SuggestedItem(BaseModel):
    id: str
    name: str
    category: str
    subcategory: Optional[str] = None
    
    class Config:
        allow_population_by_field_name = True

class OutfitResponse(BaseModel):
    items: List[SuggestedItem]
    description: str
    suggestion_tip: Optional[str] = None
    pinterest_links: Optional[List[PinterestLink]] = None
    
    class Config:
        allow_population_by_field_name = True

class ProfileInit(BaseModel):
    gender: str
    fullname: str
    birthDate: Optional[str] = None
    
    class Config:
        allow_population_by_field_name = True

# YENİ: Usage status için schema
class UsageStatusResponse(BaseModel):
    plan: str
    current_usage: int
    daily_limit: Union[int, str]  # "unlimited" veya sayı
    remaining: Union[int, str]    # "unlimited" veya sayı
    is_unlimited: bool
    date: str
    percentage_used: Optional[float] = None  # Free plan için yüzde
    
    class Config:
        allow_population_by_field_name = True

# YENİ: Plan güncelleme için schema
class PlanUpdateRequest(BaseModel):
    plan: str = Field(..., description="New plan (free, premium)")
    
    class Config:
        allow_population_by_field_name = True

# YENİ: Satın alma doğrulama için schema
class PurchaseVerification(BaseModel):
    customer_info: dict
    
    class Config:
        allow_population_by_field_name = True