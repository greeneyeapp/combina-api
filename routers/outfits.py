# kodlar/outfits.py - Tüm Endpoint'leri ve Düzeltmeleri İçeren Tam Kod

from fastapi import APIRouter, Depends, HTTPException
from openai import OpenAI
import json
from datetime import date
from firebase_admin import firestore
from typing import List, Dict, Set
from collections import defaultdict
import random
import traceback

from core.config import settings
from core.security import get_current_user_id
from schemas import OutfitRequest, OutfitResponse, ClothingItem

router = APIRouter(prefix="/api", tags=["outfits"])
client = OpenAI(api_key=settings.OPENAI_API_KEY)
db = firestore.client()

PLAN_LIMITS = {"free": 2, "premium": float('inf')}

class SmartOutfitEngine:
    """Yeni nesil kombin öneri motoru - Hata düzeltme ve kendi kendini iyileştirme mantığı ile"""
    
    def __init__(self):
        self.category_types = {
            'tops': ['t-shirt', 'shirt', 'blouse', 'top', 'bodysuit', 'crop-top', 'tank-top', 'sweater', 'cardigan', 'hoodie', 'turtleneck', 'polo-shirt', 'henley-shirt'],
            'bottoms': ['jeans', 'trousers', 'leggings', 'joggers', 'skirt', 'shorts', 'culottes', 'chino-trousers', 'cargo-pants'],
            'dresses': ['dress', 'jumpsuit', 'romper'],
            'outerwear': ['coat', 'trenchcoat', 'jacket', 'bomber-jacket', 'denim-jacket', 'leather-jacket', 'blazer', 'vest', 'gilet'],
            'footwear': ['sneakers', 'heels', 'boots', 'sandals', 'flats', 'loafers', 'wedges', 'classic-shoes', 'boat-shoes'],
            'bags': ['handbag', 'crossbody-bag', 'backpack', 'clutch', 'tote-bag', 'fanny-pack', 'messenger-bag', 'briefcase'],
            'accessories': ['jewelry', 'scarf', 'sunglasses', 'belt', 'hat', 'beanie', 'watch', 'tie', 'hijab-shawl']
        }
        self.weather_keywords = {
            'hot': {'exclude_keywords': ['coat', 'jacket', 'sweater', 'boot', 'cardigan', 'long', 'warm'], 'prefer_keywords': ['short', 'tank', 'sandal', 't-shirt', 'light']},
            'warm': {'exclude_keywords': ['coat', 'heavy'], 'prefer_keywords': ['t-shirt', 'jean', 'sneaker']},
            'mild': {'exclude_keywords': [], 'prefer_keywords': ['jean', 'trouser', 'sweater']},
            'cool': {'exclude_keywords': ['short', 'tank', 'sandal'], 'prefer_keywords': ['jacket', 'jean', 'boot']},
            'cold': {'exclude_keywords': ['short', 'tank', 'sandal', 'crop'], 'prefer_keywords': ['coat', 'sweater', 'boot', 'jacket', 'warm']}
        }
        self.occasion_styles = {
            'casual': ['casual', 'sportswear'], 'work': ['business', 'formal'], 'formal': ['formal', 'business'],
            'party': ['party', 'formal'], 'sport': ['sportswear', 'casual'], 'date': ['party', 'casual', 'formal']
        }

    def get_category_type(self, category: str) -> str:
        category_lower = category.lower()
        for cat_type, categories in self.category_types.items():
            if category_lower in categories:
                return cat_type
        return 'other'

    def create_compact_wardrobe(self, wardrobe: List[ClothingItem]) -> str:
        groups = defaultdict(list)
        for item in wardrobe:
            cat_type = self.get_category_type(item.category)
            if cat_type != 'other':
                groups[cat_type].append(f"{item.id}:{item.name}({','.join(item.colors or [item.color])})")
        return " | ".join([f"{cat_type}[{','.join(items)}]" for cat_type, items in groups.items()])

    def create_prompt(self, request: OutfitRequest, gender: str) -> str:
        wardrobe_str = self.create_compact_wardrobe(request.wardrobe)
        recent_str = f"Recently used item IDs (avoid these if possible): {','.join(list({i for o in request.last_5_outfits for i in o.items}))}"
        ask_for_pinterest = ""
        if request.plan == 'premium':
            ask_for_pinterest = ',"pinterest_links":[{"title":"","url":""}]'
        
        return f"""You are a fashion stylist. Create a {gender} outfit for '{request.occasion}' in {request.weather_condition} weather.
Respond in {request.language}.
Your available items are: {wardrobe_str}
{recent_str}

RULES:
1. Your primary goal is to pick logical items for a complete outfit.
2. You MUST select item IDs ONLY from the list provided. Do NOT invent IDs.
3. For each item in the JSON response, use the exact 'id' from the list. The 'name' and 'category' should be a short, creative description, NOT the exact text from the item list.
4. The final outfit must be logical: (1 top + 1 bottom + 1 footwear) OR (1 dress + 1 footwear). Do not combine a dress with a top or bottom.
5. Do not suggest more than one item from the same category type (e.g., two tops), except for accessories.

Respond in this exact JSON format: {{"items":[{{"id":"","name":"","category":""}}],"description":"","suggestion_tip":""{ask_for_pinterest}}}."""
        
    def build_and_validate_outfit(self, ai_items: List[Dict], wardrobe: List[ClothingItem]) -> List[Dict] | None:
        print("🔍 Validating and building final outfit...")
        wardrobe_map = {item.id: item for item in wardrobe}
        
        valid_items_by_type = defaultdict(list)
        for item in ai_items:
            item_id = item.get("id")
            if item_id in wardrobe_map:
                correct_item = wardrobe_map[item_id]
                cat_type = self.get_category_type(correct_item.category)
                if cat_type != 'other':
                    valid_items_by_type[cat_type].append(correct_item)

        final_items = []
        for cat_type, items in valid_items_by_type.items():
            if cat_type != 'accessories' and len(items) > 1:
                print(f"   ⚠️ Duplicate category '{cat_type}' found. Picking one randomly.")
                final_items.append(random.choice(items))
            else:
                final_items.extend(items)
        
        final_types = {self.get_category_type(item.category) for item in final_items}
        
        if 'dresses' in final_types:
            final_items = [item for item in final_items if self.get_category_type(item.category) not in ['tops', 'bottoms']]
        elif not ('tops' in final_types and 'bottoms' in final_types):
            if 'tops' in final_types and 'bottoms' not in final_types:
                bottom = next((item for item in wardrobe if self.get_category_type(item.category) == 'bottoms'), None)
                if bottom: final_items.append(bottom)
            elif 'bottoms' in final_types and 'tops' not in final_types:
                top = next((item for item in wardrobe if self.get_category_type(item.category) == 'tops'), None)
                if top: final_items.append(top)

        if 'footwear' not in {self.get_category_type(item.category) for item in final_items}:
            shoe = next((item for item in wardrobe if self.get_category_type(item.category) == 'footwear'), None)
            if shoe: final_items.append(shoe)

        final_category_types = {self.get_category_type(item.category) for item in final_items}
        is_dress_combo = 'dresses' in final_category_types and 'footwear' in final_category_types
        is_regular_combo = 'tops' in final_category_types and 'bottoms' in final_category_types and 'footwear' in final_category_types

        if not (is_dress_combo or is_regular_combo):
            print("   ❌ CRITICAL: Could not build a valid outfit structure.")
            return None

        print("   ✅ Final outfit is valid and complete.")
        return [{"id": item.id, "name": item.name, "category": item.category} for item in final_items]

outfit_engine = SmartOutfitEngine()

async def check_usage_and_get_user_data(user_id: str = Depends(get_current_user_id)):
    """Kullanım kontrolü ve kullanıcı verisi getirme (Ödüllü reklam mantığı eklendi)"""
    today = str(date.today())
    user_ref = db.collection('users').document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User profile not found.")
    
    user_data = user_doc.to_dict()
    plan = user_data.get("plan", "free")
    
    usage_data = user_data.get("usage", {})
    if usage_data.get("date") != today:
        usage_data = {"count": 0, "date": today, "rewarded_count": 0}
        user_ref.update({"usage": usage_data})
    
    if plan == "premium":
        return {"user_id": user_id, "gender": user_data.get("gender", "unisex"), "plan": plan}

    current_usage = usage_data.get("count", 0)
    rewarded_count = usage_data.get("rewarded_count", 0)
    daily_limit = PLAN_LIMITS.get(plan, 2)
    effective_limit = daily_limit + rewarded_count
    
    if current_usage >= effective_limit:
        raise HTTPException(status_code=429, detail=f"Daily limit of {effective_limit} requests reached.")
    
    return {"user_id": user_id, "gender": user_data.get("gender", "unisex"), "plan": plan}

@router.post("/suggest-outfit", response_model=OutfitResponse)
async def suggest_outfit(request: OutfitRequest, user_info: dict = Depends(check_usage_and_get_user_data)):
    """AI'dan gelen veriyi doğrulayan ve düzelten son kombin öneri endpoint'i"""
    try:
        user_id, plan, gender = user_info["user_id"], user_info["plan"], user_info["gender"]
        
        prompt = outfit_engine.create_prompt(request, gender)
        
        ai_config = {"free": {"max_tokens": 500}, "premium": {"max_tokens": 800}}
        config = ai_config.get(plan, ai_config["free"])

        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful fashion assistant."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
            **config
        )
        
        response_content = completion.choices[0].message.content
        if not response_content:
            raise HTTPException(status_code=500, detail="AI returned empty response.")

        print(f"   📝 Raw AI Response: {response_content}")
        ai_response_data = json.loads(response_content)

        final_items = outfit_engine.build_and_validate_outfit(
            ai_response_data.get("items", []),
            request.wardrobe
        )

        if not final_items:
            raise HTTPException(status_code=500, detail="Failed to construct a valid outfit from AI suggestion.")

        db.collection('users').document(user_id).update({'usage.count': firestore.Increment(1)})
        
        return OutfitResponse(
            items=final_items,
            description=ai_response_data.get("description", ""),
            suggestion_tip=ai_response_data.get("suggestion_tip", ""),
            pinterest_links=ai_response_data.get("pinterest_links", [])
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ CRITICAL ERROR in suggest-outfit: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"AI suggestion failed: {str(e)}")

# ÖNCEKİ KODDA EKSİK OLAN FONKSİYON
@router.get("/usage-status")
async def get_usage_status(user_id: str = Depends(get_current_user_id)):
    """Kullanıcının mevcut kullanım durumunu döndürür"""
    try:
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_data = user_doc.to_dict()
        plan = user_data.get("plan", "free")
        usage_data = user_data.get("usage", {})
        today = str(date.today())
        
        current_usage = usage_data.get("count", 0) if usage_data.get("date") == today else 0
        rewarded_count = usage_data.get("rewarded_count", 0) if usage_data.get("date") == today else 0
        daily_limit = PLAN_LIMITS.get(plan, 2)
        
        return {
            "plan": plan,
            "current_usage": current_usage,
            "rewarded_usage": rewarded_count,
            "daily_limit": "unlimited" if plan == "premium" else daily_limit,
            "remaining": "unlimited" if plan == "premium" else max(0, (daily_limit + rewarded_count) - current_usage),
            "date": today
        }
    except Exception as e:
        print(f"Error getting usage status: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get usage status")