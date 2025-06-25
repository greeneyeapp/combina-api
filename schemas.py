from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class Token(BaseModel):
    access_token: str
    token_type: str

class IdToken(BaseModel):
    id_token: str

class ClothingItem(BaseModel):
    id: str
    name: str
    category: str
    subcategory: Optional[str] = None      
    color: str
    season: List[str]
    style: str
    notes: Optional[str] = None
    createdAt: Optional[str] = None        

    class Config:
        allow_population_by_field_name = True
        fields = {
            'createdAt': 'createdAt',
            'subcategory': 'subcategory',
        }

class Outfit(BaseModel):
    items: List[str]
    occasion: str
    date: str

    class Config:
        allow_population_by_field_name = True
        
class PinterestLink(BaseModel):
    title: str
    url: str

class OutfitRequest(BaseModel):
    language: str = Field(..., alias='language')
    gender: Optional[str] = Field(None, alias='gender')
    wardrobe: List[ClothingItem] = Field(..., alias='wardrobe')
    last_5_outfits: List[Outfit] = Field(..., alias='last_5_outfits')
    weather_condition: str = Field(..., alias='weather_condition')
    occasion: str = Field(..., alias='occasion')
    
    class Config:
        allow_population_by_field_name = True
        alias_generator = lambda s: ''.join(
            part.capitalize() if i else part for i, part in enumerate(s.split('_'))
        )
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
    pinterest_links: List[PinterestLink]  

    class Config:
        allow_population_by_field_name = True

class ProfileInit(BaseModel):
    gender: str
    fullname: str
    birthDate: Optional[str] = None

    class Config:
        allow_population_by_field_name = True