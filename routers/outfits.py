from fastapi import APIRouter, Depends, HTTPException
from openai import OpenAI
import json
from datetime import date
from firebase_admin import firestore
from typing import List, Optional

from core.config import settings
from core.security import get_current_user_id
from schemas import OutfitRequest, OutfitResponse, ClothingItem

router = APIRouter(prefix="/api", tags=["outfits"])
client = OpenAI(api_key=settings.OPENAI_API_KEY)
db = firestore.client()

# Güncellenmiş plan limitleri - Premium sınırsız
PLAN_LIMITS = {
    "free": 2, 
    "premium": float('inf')  # Sınırsız
}

async def check_usage_and_get_user_data(user_id: str = Depends(get_current_user_id)):
    """Usage kontrolü yapar ve kullanıcı verilerini döndürür"""
    today = str(date.today())
    user_ref = db.collection('users').document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User profile not found.")
    
    user_data = user_doc.to_dict()
    plan = user_data.get("plan", "free")

    # Usage verilerini kontrol et/başlat
    if user_data.get("usage", {}).get("date") != today:
        user_data["usage"] = {"count": 0, "date": today}
        user_ref.update({"usage": user_data["usage"]})
    
    limit = PLAN_LIMITS.get(plan, 0)
    current_usage = user_data.get("usage", {}).get("count", 0)
    
    # Premium planı için sınırsız kontrol
    if plan == "premium":
        # Premium kullanıcılar için limit kontrolü yok
        pass
    elif current_usage >= limit:
        plan_name = plan.capitalize()
        raise HTTPException(
            status_code=429, 
            detail=f"Daily limit of {limit} requests reached for {plan_name} plan. Please upgrade your plan or try again tomorrow."
        )
        
    return {"user_id": user_id, "gender": user_data.get("gender", "unisex"), "plan": plan}


def create_outfit_prompt(request: OutfitRequest, gender: str) -> str:
    """Plana göre dinamik olarak prompt oluşturur - yeni optimized format destekli."""
    
    # Yeni optimized format - colors array ve style array destekli
    wardrobe_items = []
    for item in request.wardrobe:
        # Çoklu renk desteği - colors varsa onu kullan, yoksa color'dan oluştur
        if hasattr(item, 'colors') and item.colors:
            colors_str = ",".join(item.colors)
        else:
            colors_str = item.color
            
        # Çoklu stil desteği - style array veya string olabilir
        if hasattr(item, 'style'):
            if isinstance(item.style, list):
                styles_str = ",".join(item.style)
            else:
                styles_str = item.style
        else:
            styles_str = 'casual'
            
        # Mevsim desteği
        seasons_str = ",".join(item.season) if hasattr(item, 'season') and item.season else 'all'
        
        wardrobe_items.append(f"{item.id}|{item.name}|{item.category}|{colors_str}|{styles_str}|{seasons_str}")
    
    wardrobe_str = "\n".join(wardrobe_items)

    # Recent items analizi - yeni format ile
    recent_items_info = ""
    if request.last_5_outfits:
        recent_items = {
            item.name for outfit in request.last_5_outfits 
            for item_id in outfit.items
            if (item := next((it for it in request.wardrobe if it.id == item_id), None))
        }
        if recent_items:
            recent_items_info = f"RECENTLY USED: {', '.join(recent_items)} - Try to suggest different items for variety."

    # Context bilgileri - yeni format ile
    context_info = ""
    if hasattr(request, 'context') and request.context:
        total_wardrobe = getattr(request.context, 'total_wardrobe_size', len(request.wardrobe))
        filtered_wardrobe = getattr(request.context, 'filtered_wardrobe_size', len(request.wardrobe))
        context_info = f"WARDROBE INFO: Total items: {total_wardrobe}, Filtered for relevance: {filtered_wardrobe}"

    # Premium plan için Pinterest links
    pinterest_json_format = ""
    if request.plan == 'premium':
        pinterest_json_format = f'''
"pinterest_links": [
    {{"title": "Specific color + gender combination title in {request.language}", "url": "https://www.pinterest.com/search/pins/?q=selected+colors+{gender}+kombin+{request.language}"}},
    {{"title": "Gender + occasion specific styling title in {request.language}", "url": "https://www.pinterest.com/search/pins/?q={gender}+occasion+outfit+{request.language}"}},
    {{"title": "Gender + weather appropriate outfit title in {request.language}", "url": "https://www.pinterest.com/search/pins/?q={gender}+weather+kıyafet+{request.language}"}}
]'''

    prompt = f"""Fashion stylist for {gender} user. Respond ONLY in {request.language}.

WARDROBE (ID|Name|Category|Colors|Styles|Seasons):
{wardrobe_str}

CONTEXT: Weather={request.weather_condition}, Occasion={request.occasion}
{context_info}
{recent_items_info}

STYLING RULES:
1. Select 3-4 items: 1 top + 1 bottom + 1 footwear + optional outerwear/accessories.
2. Use EXACT IDs/names/categories from wardrobe.
3. Consider weather: 
   - Hot weather (25°C+) = Light fabrics, no heavy outerwear
   - Cold weather (10°C-) = Layers, warm outerwear required
   - Match season tags with weather condition
4. Consider occasion appropriateness using style tags.
5. Use color combinations that work well together.
6. Translate color names to {request.language} in descriptions.
7. Create variety - avoid recently used items when possible.
8. For premium users, provide detailed styling tips and color theory insights.

JSON FORMAT:
{{
"items": [{{"id": "exact_id", "name": "exact_name", "category": "exact_category"}}],
"description": "Detailed outfit description in {request.language} with translated colors and styling rationale",
"suggestion_tip": "{"Advanced styling advice with color theory and fashion principles" if request.plan == "premium" else "Simple styling tip"} in {request.language}"
{',' if pinterest_json_format else ''} {pinterest_json_format}
}}

PINTEREST EXAMPLES (Premium only):
✓ "Mavi ve Beyaz {gender.title()} Kombin Önerileri"
✓ "{gender.title()} {request.occasion.replace('-', ' ').title()} Kıyafet Fikirleri"  
✓ "{request.weather_condition.title()} Hava {gender.title()} Kombinler"
✗ "Renk kombinasyonları" (too generic)
✗ "Günlük stil önerileri" (no gender, too vague)"""
    
    return prompt


@router.post("/suggest-outfit", response_model=OutfitResponse)
async def suggest_outfit(request: OutfitRequest, user_info: dict = Depends(check_usage_and_get_user_data)):
    """Outfit önerisi oluşturur - optimized format ve sınırsız premium destekli"""
    user_id = user_info["user_id"]
    plan = user_info["plan"]
    
    # Client'tan gelen gender bilgisini kullan, yoksa veritabanından al
    gender = request.gender if request.gender in ['male', 'female'] else user_info.get("gender", "unisex")
    
    # Wardrobe boyut kontrolü - performans için
    wardrobe_size = len(request.wardrobe)
    if wardrobe_size == 0:
        raise HTTPException(status_code=400, detail="No wardrobe items provided.")
    
    # Büyük wardrobe'lar için log
    if wardrobe_size > 200:
        print(f"⚠️ Large wardrobe detected: {wardrobe_size} items for user {user_id[:8]}...")
    
    prompt = create_outfit_prompt(request, gender)
    
    try:
        # Plan bazlı model ve token limitleri
        max_tokens = 1200 if plan == "premium" else 800
        temperature = 0.9 if plan == "premium" else 0.8
        
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system", 
                    "content": f"You are a professional fashion stylist for {plan} plan users. Respond ONLY in {request.language}. Return JSON format with exact wardrobe items."
                },
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=0.9,
            seed=None
        )
        
        response_content = completion.choices[0].message.content
        if not response_content:
            raise HTTPException(status_code=500, detail="AI returned an empty response.")
        
        try:
            outfit_response = json.loads(response_content)
            
            if not outfit_response.get("items"):
                raise HTTPException(status_code=500, detail="No items returned by AI.")
            
            # Validasyon: Footwear kontrolü
            categories = {item.get("category", "").lower() for item in outfit_response.get("items", [])}
            footwear_subcategories = {
                "sneakers", "heels", "boots", "sandals", "flats", "loafers", 
                "wedges", "classic-shoes", "boat-shoes"
            }

            if not any(cat in footwear_subcategories for cat in categories):
                raise HTTPException(status_code=500, detail="No footwear included in outfit suggestion.")
            
            # Validasyon: Item ID'lerin wardrobe'da olup olmadığı
            suggested_ids = {item.get("id") for item in outfit_response.get("items", [])}
            wardrobe_ids = {item.id for item in request.wardrobe}
            invalid_ids = suggested_ids - wardrobe_ids
            
            if invalid_ids:
                raise HTTPException(
                    status_code=500, 
                    detail=f"AI suggested non-existent items: {list(invalid_ids)}"
                )
                
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=500, detail=f"Invalid JSON response from AI: {str(e)}")
        
        # Usage'ı artır - Premium için de say ama limit yok
        db.collection('users').document(user_id).update({
            'usage.count': firestore.Increment(1),
            'usage.date': str(date.today())
        })
        
        # Success log
        suggestion_count = len(outfit_response.get("items", []))
        has_pinterest = bool(outfit_response.get("pinterest_links"))
        print(f"✅ Outfit suggestion created: {suggestion_count} items, Plan: {plan}, Pinterest: {has_pinterest}")
        
        return outfit_response
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ AI suggestion error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get suggestion from AI: {str(e)}")


# Yardımcı endpoint - kullanıcının günlük usage durumunu kontrol etmek için
@router.get("/usage-status")
async def get_usage_status(user_id: str = Depends(get_current_user_id)):
    """Kullanıcının günlük kullanım durumunu döndürür"""
    today = str(date.today())
    user_ref = db.collection('users').document(user_id)
    user_doc = user_ref.get()
    
    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User not found")
    
    user_data = user_doc.to_dict()
    plan = user_data.get("plan", "free")
    usage_data = user_data.get("usage", {})
    
    # Bugünün usage'ı yoksa sıfırla
    if usage_data.get("date") != today:
        current_usage = 0
    else:
        current_usage = usage_data.get("count", 0)
    
    limit = PLAN_LIMITS.get(plan, 0)
    
    return {
        "plan": plan,
        "current_usage": current_usage,
        "daily_limit": "unlimited" if plan == "premium" else limit,
        "remaining": "unlimited" if plan == "premium" else max(0, limit - current_usage),
        "is_unlimited": plan == "premium",
        "date": today
    }