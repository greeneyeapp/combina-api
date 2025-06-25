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

def translate_color_name(color: str, target_language: str) -> str:
    """Renk isimlerini hedef dile çevirir"""
    color_translations = {
        "tr": {
            "black": "siyah", "white": "beyaz", "ivory": "krem", "beige": "bej",
            "charcoal": "koyu gri", "skyblue": "açık mavi", "royalblue": "koyu mavi",
            "burgundy": "bordo", "scarlet": "al kırmızısı", "navy": "lacivert",
            "gray": "gri", "grey": "gri", "brown": "kahverengi", "green": "yeşil", 
            "blue": "mavi", "red": "kırmızı", "yellow": "sarı", "orange": "turuncu", 
            "purple": "mor", "pink": "pembe", "cream": "krem", "khaki": "haki", 
            "olive": "zeytin yeşili", "gold": "altın", "silver": "gümüş"
        },
        "en": {
            "black": "black", "white": "white", "ivory": "ivory", "beige": "beige",
            "charcoal": "charcoal", "skyblue": "sky blue", "royalblue": "royal blue",
            "burgundy": "burgundy", "scarlet": "scarlet", "navy": "navy",
            "gray": "gray", "grey": "grey", "brown": "brown", "green": "green", 
            "blue": "blue", "red": "red", "yellow": "yellow", "orange": "orange", 
            "purple": "purple", "pink": "pink", "cream": "cream", "khaki": "khaki", 
            "olive": "olive", "gold": "gold", "silver": "silver"
        }
    }
    
    if target_language in color_translations:
        return color_translations[target_language].get(color.lower(), color)
    return color

def create_outfit_prompt(request: OutfitRequest, gender: str) -> str:
    """Geliştirilmiş prompt oluşturur - renk çevirisi ve mantık kontrolleri ile"""
    
    # Wardrobe'daki renkleri çevir
    translated_wardrobe = []
    for item in request.wardrobe:
        translated_color = translate_color_name(item.color, request.language)
        translated_wardrobe.append(
            f"ID: {item.id} | Name: {item.name} | Category: {item.category} | Color: {translated_color} | Style: {item.style} | Season: {', '.join(item.season)}"
        )
    
    wardrobe_str = "\n".join(translated_wardrobe)

    # Son 5 kombin kontrolü
    last_outfits_str = ""
    if request.last_5_outfits:
        recent_items = []
        for outfit in request.last_5_outfits:
            item_names = [it.name for it_id in outfit.items for it in request.wardrobe if it.id == it_id]
            recent_items.extend(item_names)
        last_outfits_str = f"AVOID REPEATING THESE ITEMS: {', '.join(set(recent_items))}" if recent_items else ""

    lang_code = request.language if request.language in ["tr", "en"] else "en"

    prompt = f"""You are an expert fashion stylist. Create a professional outfit recommendation for {gender} user in {request.language}.

USER'S WARDROBE (with translated colors):
{wardrobe_str}

CURRENT CONTEXT: 
- Weather: {request.weather_condition}
- Occasion: {request.occasion}
{last_outfits_str}

CRITICAL STYLING RULES - FOLLOW EXACTLY:
1. Use EXACT item IDs, names, and categories from the wardrobe above
2. Select ONLY 3-4 items total: 1 top + 1 bottom + 1 footwear + (optional outerwear)
3. NEVER select multiple items from same category (example: never 2 trousers, never 2 shirts)
4. For warm weather: DO NOT select jackets/blazers unless absolutely necessary
5. For males: exclude any dress/skirt items completely
6. MANDATORY: Always include exactly 1 footwear item
7. Use EXACT names and categories from wardrobe - do not modify them
8. Write ALL content in {request.language} using translated color names

OUTFIT LOGIC VALIDATION:
- Check that you have: 1 top (shirt/t-shirt) + 1 bottom (trousers/jeans/joggers) + 1 footwear
- For warm weather: shirt + trousers/jeans + sandals/sneakers (NO jacket needed)
- For cool weather: shirt + trousers + shoes + optional jacket/blazer

LANGUAGE AND COLOR REQUIREMENTS:
- All descriptions must be in {request.language}
- Use translated color names consistently (krem not ivory, bordo not burgundy, etc.)
- Pinterest titles must be natural sentences in {request.language}
- Pinterest URLs should include {lang_code} language code

REQUIRED JSON FORMAT:
{{
"items": [
{{"id": "EXACT_item_id_from_wardrobe", "name": "EXACT_item_name_from_wardrobe", "category": "EXACT_category_from_wardrobe"}}
],
"description": "Professional outfit description in {request.language} highlighting translated colors and styling approach",
"suggestion_tip": "Specific styling advice in {request.language} mentioning translated colors and textures",
"pinterest_links": [
{{"title": "Natural title in {request.language} about color combination", "url": "https://www.pinterest.com/search/pins/?q=translated+color+terms+{lang_code}"}},
{{"title": "Elegant title in {request.language} about styling technique", "url": "https://www.pinterest.com/search/pins/?q=style+coordination+{lang_code}"}},
{{"title": "Sophisticated title in {request.language} for the occasion", "url": "https://www.pinterest.com/search/pins/?q=occasion+outfit+{lang_code}"}}
]
}}

PINTEREST TITLE EXAMPLES (in {request.language}):
✓ Good Turkish: "Sıcak Havalar için Krem ve Bordo Renk Kombinleri"
✓ Good Turkish: "Günlük Şıklık için Erkek Kıyafet Önerileri"  
✓ Good Turkish: "Rahat ve Şık Yaz Kombinleri"
✓ Good English: "Professional Cream and Burgundy Color Combinations"
✓ Good English: "Casual Elegance for Men's Daily Style"
✗ Avoid: URL-style phrases like "krem+gomlek+bordo+pantolon"
✗ Avoid: Mixed language terms (English+Turkish)

VALIDATION CHECKLIST:
- ✓ Exactly 3-4 items selected?
- ✓ No duplicate categories?
- ✓ Includes footwear?
- ✓ Weather appropriate?
- ✓ All text in {request.language}?
- ✓ Exact IDs/names/categories used?
- ✓ Translated color names used?

IMPORTANT: Use EXACT item names and categories from the wardrobe. Do not modify or translate item names - only translate color names in descriptions!"""
    
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
                {"role": "system", "content": f"You are a professional fashion stylist that responds ONLY in perfect {request.language} and strictly in the required JSON format. Use exact item names/categories from wardrobe and translated color names in descriptions. Follow the validation checklist."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.7
        )
        
        response_content = completion.choices[0].message.content
        if not response_content:
            raise HTTPException(status_code=500, detail="AI returned an empty response.")
        
        # JSON response'u parse et ve validate et
        try:
            outfit_response = json.loads(response_content)
            
            # Temel validasyon
            if not outfit_response.get("items") or len(outfit_response.get("items", [])) == 0:
                raise HTTPException(status_code=500, detail="AI returned invalid outfit with no items.")
            
            # Footwear kontrolü
            has_footwear = any(
                item.get("category", "").lower() in ["sneakers", "sandals", "shoes", "boots"] 
                for item in outfit_response.get("items", [])
            )
            
            if not has_footwear:
                raise HTTPException(status_code=500, detail="AI did not include required footwear.")
                
        except json.JSONDecodeError:
            raise HTTPException(status_code=500, detail="AI returned invalid JSON format.")
        
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