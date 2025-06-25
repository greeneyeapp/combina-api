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

def create_outfit_prompt(request: OutfitRequest, gender: str) -> str:
    """Outfit önerisi için prompt oluşturur"""
    # Detaylı wardrobe listesi - renk ve style bilgisi vurgulanıyor
    wardrobe_str = "\n".join(
        f"ID: {item.id} | {item.name} | {item.category} | Color: {item.color} | Style: {item.style} | Season: {', '.join(item.season)}"
        for item in request.wardrobe
    )

    # Son 5 kombin - kısa format
    last_outfits_str = ""
    if request.last_5_outfits:
        recent_items = []
        for outfit in request.last_5_outfits:
            item_names = [it.name for it_id in outfit.items for it in request.wardrobe if it.id == it_id]
            recent_items.extend(item_names)
        last_outfits_str = f"AVOID REPEATING: {', '.join(set(recent_items))}" if recent_items else ""

    prompt = f"""You are an expert fashion stylist. Create a thoughtful outfit recommendation for {gender} user in {request.language}.

    USER'S WARDROBE:
    {wardrobe_str}

    CURRENT CONTEXT: 
    - Weather: {request.weather_condition}
    - Occasion: {request.occasion}
    {last_outfits_str}

    STYLING REQUIREMENTS:
    1. Select items ONLY from the provided wardrobe
    2. For males: exclude any dress/skirt items
    3. Always include footwear (shoes/boots/sandals)
    4. For cool/cold/rainy weather: prioritize outerwear if available
    5. Create cohesive color palette using actual item colors
    6. Write description and tip in {request.language} with warm, friendly tone

    PINTEREST LINK STRATEGY:
    - Use EXACT colors from selected items in URLs
    - Create 3 distinct searches with ELEGANT, READABLE titles
    - Write titles as normal sentences, not URL format
    - Focus on styling inspiration, not literal item names

    REQUIRED JSON FORMAT:
    {{
    "items": [{{"id": "exact_item_id", "name": "exact_item_name", "category": "exact_category"}}],
    "description": "Detailed outfit description highlighting colors and styling in {request.language}",
    "suggestion_tip": "Specific styling advice mentioning colors/textures in {request.language}",
    "pinterest_links": [
    {{"title": "Elegant title describing the overall look inspiration", "url": "https://www.pinterest.com/search/pins/?q=actual+colors+items+occasion"}},
    {{"title": "Stylish title about color coordination or styling tips", "url": "https://www.pinterest.com/search/pins/?q=color+combination+styling+tips"}},
    {{"title": "Sophisticated title for similar occasion outfits", "url": "https://www.pinterest.com/search/pins/?q=season+occasion+style+inspiration"}}
    ]
    }}

    PINTEREST TITLE EXAMPLES:
    ✓ Good: "Chic Blue & Lilac Color Combinations for Work"
    ✓ Good: "Elegant Layering Ideas for Cool Weather"
    ✓ Good: "Sophisticated Casual Outfits with Colorful Accents"
    ✗ Avoid: "Light+blue+tshirt+turquoise+boots+formal+work"
    ✗ Avoid: "Layering+raincoat+style+tips+color+contrast"

    The title should be natural, elegant language that describes styling inspiration."""
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
                {"role": "system", "content": f"You are a professional fashion stylist that responds in perfect {request.language} and strictly in the required JSON format. Use translated color names consistently."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        
        response_content = completion.choices[0].message.content
        if not response_content:
            raise HTTPException(status_code=500, detail="AI returned an empty response.")
        
        # Usage'ı artır
        db.collection('users').document(user_id).update({
            'usage.count': firestore.Increment(1),
            'usage.date': str(date.today())
        })
        
        return json.loads(response_content)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get suggestion from AI: {e}")