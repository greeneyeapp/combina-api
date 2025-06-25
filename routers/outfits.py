from fastapi import APIRouter, Depends, HTTPException
from openai import OpenAI
import json
from datetime import date
from firebase_admin import firestore

from core.config import settings
from core.security import get_current_user_id
from schemas import OutfitRequest, OutfitResponse, ClothingItem

router = APIRouter(prefix="/api", tags=["outfits"])
client = OpenAI(api_key=settings.OPENAI_API_KEY)
db = firestore.client()

PLAN_LIMITS = {"free": 2, "standard": 10, "premium": 50}

async def check_usage_and_get_user_data(user_id: str = Depends(get_current_user_id)):
    """Usage kontrolü yapar ve kullanıcı verilerini döndürür"""
    today = str(date.today())
    user_ref = db.collection('users').document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User profile not found.")
    
    user_data = user_doc.to_dict()
    if user_data.get("usage", {}).get("date") != today:
        user_data["usage"] = {"count": 0, "date": today}
        user_ref.update({"usage": user_data["usage"]})
    
    limit = PLAN_LIMITS.get(user_data.get("plan", "free"), 0)
    if user_data.get("usage", {}).get("count", 0) >= limit:
        plan_name = user_data.get("plan", "free").capitalize()
        raise HTTPException(
            status_code=429, 
            detail=f"Daily limit of {limit} requests reached for {plan_name} plan. Please upgrade your plan or try again tomorrow."
        )
        
    return {"user_id": user_id, "gender": user_data.get("gender", "unisex")}

# Renk çevirisi fonksiyonunu kaldırdık - GPT kendisi çevirecek

def create_outfit_prompt(request: OutfitRequest, gender: str) -> str:
    """Optimize edilmiş prompt - GPT kendisi renk çevirisini yapacak"""
    
    # Wardrobe'ı olduğu gibi listele (renk çevirisi yapmadan)
    wardrobe_items = []
    for item in request.wardrobe:
        wardrobe_items.append(f"{item.id}|{item.name}|{item.category}|{item.color}")
    
    wardrobe_str = "\n".join(wardrobe_items)

    # AVOID items kısmını kaldırdık
    # avoid_items = ""
    # if request.last_5_outfits:
    #     recent_names = []
    #     for outfit in request.last_5_outfits:
    #         for it_id in outfit.items:
    #             item = next((it for it in request.wardrobe if it.id == it_id), None)
    #             if item:
    #                 recent_names.append(item.name)
    #     avoid_items = f"AVOID: {', '.join(set(recent_names))}" if recent_names else ""

    # Basit ve net prompt
    prompt = f"""Fashion stylist for {gender} user. Respond ONLY in {request.language}.

WARDROBE (ID|Name|Category|Color):
{wardrobe_str}

CONTEXT: Weather={request.weather_condition}, Occasion={request.occasion}

CRITICAL RULES - MUST FOLLOW:
1. Select 3-4 items: 1 top + 1 bottom + 1 footwear + optional outerwear
2. Use EXACT IDs/names/categories from wardrobe
3. Warm weather = NO jackets/blazers
4. Translate ALL color names to {request.language} in descriptions:
   - ivory → krem, burgundy → bordo, royalblue → koyu mavi, 
   - skyblue → açık mavi, charcoal → koyu gri, scarlet → al kırmızısı
5. Write detailed, professional descriptions in {request.language}

JSON FORMAT:
{{
"items": [{{"id": "exact_id", "name": "exact_name", "category": "exact_category"}}],
"description": "Detailed outfit description in {request.language} explaining color harmony and styling approach (min 2 sentences)",
"suggestion_tip": "Specific styling advice in {request.language} mentioning colors and occasion appropriateness (min 2 sentences)",
"pinterest_links": [
{{"title": "Specific color combination title in {request.language}", "url": "https://www.pinterest.com/search/pins/?q=specific+color+combination+{request.language}"}},
{{"title": "Occasion-specific styling title in {request.language}", "url": "https://www.pinterest.com/search/pins/?q=occasion+styling+{request.language}"}},
{{"title": "Weather-appropriate outfit title in {request.language}", "url": "https://www.pinterest.com/search/pins/?q=weather+appropriate+outfit+{request.language}"}}
]
}}

EXAMPLE PINTEREST TITLES:
✓ "Krem ve Bordo Renk Kombinleri için İlham"
✓ "Doğum Günü Partisi Erkek Kıyafet Önerileri"  
✓ "Sıcak Hava için Şık Kombinler"
✗ "Doğal stil" (too vague)
✗ "Şıklık" (too general)"""
    
    return prompt

@router.post("/suggest-outfit", response_model=OutfitResponse)
async def suggest_outfit(request: OutfitRequest, user_info: dict = Depends(check_usage_and_get_user_data)):
    """Outfit önerisi oluşturur - client'ten gelen gender bilgisini kullanır"""
    user_id = user_info["user_id"]
    
    # Client'ten gelen gender bilgisini öncelikle kullan
    if request.gender and request.gender in ['male', 'female']:
        gender = request.gender
    else:
        # Fallback: database'den al
        gender = user_info.get("gender", "unisex")
    
    # Eğer hala cinsiyet bilgisi yoksa default olarak "unisex" kullan
    if not gender:
        gender = "unisex"
    
    prompt = create_outfit_prompt(request, gender)
    
    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"You are a professional fashion stylist. Respond ONLY in {request.language}. Return JSON format with exact wardrobe items."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.3,  # Daha düşük temperature = daha hızlı
            max_tokens=800,   # Token limiti = daha hızlı
            top_p=0.9        # Daha fokuslu yanıtlar = daha hızlı
        )
        
        response_content = completion.choices[0].message.content
        if not response_content:
            raise HTTPException(status_code=500, detail="AI returned an empty response.")
        
        # Basitleştirilmiş validasyon
        try:
            outfit_response = json.loads(response_content)
            
            # Sadece temel kontroller
            if not outfit_response.get("items"):
                raise HTTPException(status_code=500, detail="No items returned.")
            
            # Footwear kontrolü (daha hızlı)
            categories = [item.get("category", "").lower() for item in outfit_response.get("items", [])]
            footwear_categories = {"sneakers", "sandals", "shoes", "boots"}
            
            if not any(cat in footwear_categories for cat in categories):
                raise HTTPException(status_code=500, detail="No footwear included.")
                
        except json.JSONDecodeError:
            raise HTTPException(status_code=500, detail="Invalid JSON.")
        
        # Usage'ı artır
        db.collection('users').document(user_id).update({
            'usage.count': firestore.Increment(1),
            'usage.date': str(date.today())
        })
        
        return outfit_response
        
    except HTTPException:
        # HTTP exceptions'ları tekrar raise et
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get suggestion from AI: {str(e)}")