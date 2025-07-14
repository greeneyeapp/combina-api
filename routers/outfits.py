from fastapi import APIRouter, Depends, HTTPException
from openai import OpenAI
import json
from datetime import date
from firebase_admin import firestore
from typing import List, Dict, Set
from collections import defaultdict
import random

from core.config import settings
from core.security import get_current_user_id
from schemas import OutfitRequest, OutfitResponse, ClothingItem

router = APIRouter(prefix="/api", tags=["outfits"])
client = OpenAI(api_key=settings.OPENAI_API_KEY)
db = firestore.client()

# Plan limitleri
PLAN_LIMITS = {
    "free": 2, 
    "premium": float('inf')
}

class SmartOutfitEngine:
    """Yeni nesil kombin öneri motoru"""
    
    def __init__(self):
        # Weather-based filtering - keyword bazlı
        self.weather_keywords = {
            'hot': {
                'exclude_keywords': ['coat', 'jacket', 'sweater', 'boot', 'cardigan', 'long', 'warm'],
                'prefer_keywords': ['short', 'tank', 'sandal', 't-shirt', 'light'],
                'temp_range': (25, 50)
            },
            'warm': {
                'exclude_keywords': ['coat', 'heavy'],
                'prefer_keywords': ['t-shirt', 'jean', 'sneaker'],
                'temp_range': (20, 25)
            },
            'mild': {
                'exclude_keywords': [],
                'prefer_keywords': ['jean', 'trouser', 'sweater'],
                'temp_range': (15, 20)
            },
            'cool': {
                'exclude_keywords': ['short', 'tank', 'sandal'],
                'prefer_keywords': ['jacket', 'jean', 'boot'],
                'temp_range': (10, 15)
            },
            'cold': {
                'exclude_keywords': ['short', 'tank', 'sandal', 'crop'],
                'prefer_keywords': ['coat', 'sweater', 'boot', 'jacket', 'warm'],
                'temp_range': (-10, 10)
            }
        }
        
        # Occasion-based style mapping
        self.occasion_styles = {
            'casual': ['casual', 'sportswear'],
            'work': ['business', 'formal'],
            'formal': ['formal', 'business'],
            'party': ['party', 'formal'],
            'sport': ['sportswear', 'casual'],
            'date': ['party', 'casual', 'formal']
        }
        
        # Category mapping - flexible
        self.category_types = {
            'tops': ['t-shirt', 'shirt', 'blouse', 'top', 'bodysuit', 'crop-top', 'tank-top', 'sweater', 'cardigan', 'hoodie', 'turtleneck', 'polo-shirt', 'henley-shirt'],
            'bottoms': ['jeans', 'trousers', 'leggings', 'joggers', 'skirt', 'shorts', 'culottes', 'chino-trousers', 'cargo-pants'],
            'dresses': ['dress', 'jumpsuit', 'romper'],
            'outerwear': ['coat', 'trenchcoat', 'jacket', 'bomber-jacket', 'denim-jacket', 'leather-jacket', 'blazer', 'vest', 'gilet'],
            'footwear': ['sneakers', 'heels', 'boots', 'sandals', 'flats', 'loafers', 'wedges', 'classic-shoes', 'boat-shoes'],
            'bags': ['handbag', 'crossbody-bag', 'backpack', 'clutch', 'tote-bag', 'fanny-pack', 'messenger-bag', 'briefcase'],
            'accessories': ['jewelry', 'scarf', 'sunglasses', 'belt', 'hat', 'beanie', 'watch', 'tie', 'hijab-shawl']
        }
    
    def get_category_type(self, category: str) -> str:
        """Kategoriyi tip grubuna göre sınıflandır"""
        category_lower = category.lower()
        for category_type, categories in self.category_types.items():
            if category_lower in categories:
                return category_type
        return 'other'  # Bilinmeyen kategoriler için
    
    def filter_wardrobe(self, wardrobe: List[ClothingItem], weather: str, occasion: str) -> List[ClothingItem]:
        """Context-aware wardrobe filtering - flexible keyword system"""
        weather_rule = self.weather_keywords.get(weather, self.weather_keywords['mild'])
        occasion_styles = self.occasion_styles.get(occasion, ['casual'])
        
        filtered = []
        for item in wardrobe:
            # Weather check - keyword bazlı
            item_name_lower = item.name.lower()
            item_category_lower = item.category.lower()
            
            # Exclude check
            should_exclude = any(
                keyword in item_name_lower or keyword in item_category_lower 
                for keyword in weather_rule['exclude_keywords']
            )
            if should_exclude:
                continue
            
            # Style compatibility check
            item_styles = item.style if isinstance(item.style, list) else [item.style]
            if not any(style in occasion_styles for style in item_styles):
                continue
            
            filtered.append(item)
        
        return filtered
    
    def group_by_category_type(self, wardrobe: List[ClothingItem]) -> Dict[str, List[ClothingItem]]:
        """Group items by category type (tops, bottoms, footwear etc.)"""
        groups = defaultdict(list)
        for item in wardrobe:
            category_type = self.get_category_type(item.category)
            groups[category_type].append(item)
        return dict(groups)
    
    def create_compact_wardrobe(self, wardrobe: List[ClothingItem]) -> str:
        """Ultra compact wardrobe representation - flexible categories"""
        groups = self.group_by_category_type(wardrobe)  # Doğru metod ismi
        compact_parts = []
        
        for category_type, items in groups.items():
            item_strings = []
            for item in items:
                colors = item.colors[0] if item.colors else item.color or "neutral"
                item_strings.append(f"{item.id}:{item.name}({colors})")
            
            compact_parts.append(f"{category_type}[{','.join(item_strings)}]")
        
        return " | ".join(compact_parts)
    
    def validate_outfit_structure(self, suggested_items: List[Dict]) -> bool:
        """Kombin yapısını validate et - flexible"""
        suggested_categories = [item.get("category", "") for item in suggested_items]
        category_types = [self.get_category_type(cat) for cat in suggested_categories]
        
        # En az bir üst, bir alt/elbise ve bir ayakkabı olmalı
        has_top_or_dress = any(ct in ['tops', 'dresses'] for ct in category_types)
        has_bottom_or_dress = any(ct in ['bottoms', 'dresses'] for ct in category_types)
        has_footwear = any(ct == 'footwear' for ct in category_types)
        
        return has_top_or_dress and (has_bottom_or_dress or 'dresses' in category_types) and has_footwear
    
    def sample_wardrobe(self, wardrobe: List[ClothingItem], max_items: int = 30) -> List[ClothingItem]:
        """Smart sampling for large wardrobes"""
        if len(wardrobe) <= max_items:
            return wardrobe
        
        groups = self.group_by_category_type(wardrobe)
        sampled = []
        
        # Her kategori tipinden eşit sayıda al
        items_per_type = max(2, max_items // len(groups))
        
        for category_type, items in groups.items():
            sample_size = min(len(items), items_per_type)
            sampled.extend(random.sample(items, sample_size))
        
        return sampled[:max_items]
    
    def create_compact_wardrobe(self, wardrobe: List[ClothingItem]) -> str:
        """Ultra compact wardrobe representation"""
        groups = self.group_by_category(wardrobe)
        compact_parts = []
        
        for category, items in groups.items():
            item_strings = []
            for item in items:
                colors = item.colors[0] if item.colors else item.color or "neutral"
                item_strings.append(f"{item.id}:{item.name}({colors})")
            
            compact_parts.append(f"{category}[{','.join(item_strings)}]")
        
        return " | ".join(compact_parts)
    
    def get_recent_items(self, last_outfits: List) -> Set[str]:
        """Get recently used item IDs"""
        recent = set()
        for outfit in last_outfits[-3:]:  # Son 3 kombin
            recent.update(outfit.items)
        return recent
    
    def create_prompt(self, request: OutfitRequest, gender: str) -> str:
        """Yeni minimal prompt sistemi"""
        
        # 1. Wardrobe filtering & sampling
        filtered_wardrobe = self.filter_wardrobe(
            request.wardrobe, 
            request.weather_condition, 
            request.occasion
        )
        
        if len(filtered_wardrobe) > 30:
            filtered_wardrobe = self.sample_wardrobe(filtered_wardrobe, 30)
        
        # 2. Compact representation
        wardrobe_compact = self.create_compact_wardrobe(filtered_wardrobe)
        
        # 3. Recent items to avoid
        recent_items = self.get_recent_items(request.last_5_outfits)
        recent_str = f"Recently used: {','.join(list(recent_items)[:8])}" if recent_items else ""
        
        # 4. Plan-based prompt selection
        if request.plan == 'premium':
            return self._create_premium_prompt(request, gender, wardrobe_compact, recent_str)
        else:
            return self._create_free_prompt(request, gender, wardrobe_compact, recent_str)
    
    def _create_free_prompt(self, request: OutfitRequest, gender: str, wardrobe: str, recent: str) -> str:
        """Free plan minimal prompt"""
        return f"""Create {gender} outfit for {request.occasion} in {request.weather_condition} weather.
Language: {request.language}

Items: {wardrobe}
{recent}

Select: top/dress + bottom (if not dress) + footwear + optional outerwear
JSON: {{"items":[{{"id":"","name":"","category":""}}],"description":"","suggestion_tip":""}}"""
    
    def _create_premium_prompt(self, request: OutfitRequest, gender: str, wardrobe: str, recent: str) -> str:
        """Premium plan enhanced prompt"""
        return f"""Expert {gender} styling for {request.occasion} in {request.weather_condition}.
Language: {request.language}

Wardrobe: {wardrobe}
{recent}

Create stylish outfit with color harmony and fashion insights. Include top/dress, bottom (if not dress), footwear, optional outerwear/accessories.
JSON: {{"items":[{{"id":"","name":"","category":""}}],"description":"","suggestion_tip":"","pinterest_links":[{{"title":"","url":""}}]}}"""

# Global engine instance
outfit_engine = SmartOutfitEngine()

async def check_usage_and_get_user_data(user_id: str = Depends(get_current_user_id)):
    """Usage kontrolü ve user data"""
    today = str(date.today())
    user_ref = db.collection('users').document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User profile not found.")
    
    user_data = user_doc.to_dict()
    plan = user_data.get("plan", "free")

    # Usage check
    if user_data.get("usage", {}).get("date") != today:
        user_data["usage"] = {"count": 0, "date": today}
        user_ref.update({"usage": user_data["usage"]})
    
    current_usage = user_data.get("usage", {}).get("count", 0)
    limit = PLAN_LIMITS.get(plan, 0)
    
    if plan != "premium" and current_usage >= limit:
        raise HTTPException(
            status_code=429, 
            detail=f"Daily limit of {limit} requests reached for {plan.capitalize()} plan."
        )
        
    return {"user_id": user_id, "gender": user_data.get("gender", "unisex"), "plan": plan}

@router.post("/suggest-outfit", response_model=OutfitResponse)
async def suggest_outfit(request: OutfitRequest, user_info: dict = Depends(check_usage_and_get_user_data)):
    """Yeni nesil kombin önerisi"""
    user_id = user_info["user_id"]
    plan = user_info["plan"]
    
    # Gender determination
    gender = request.gender if request.gender in ['male', 'female'] else user_info.get("gender", "unisex")
    
    # Wardrobe validation
    if not request.wardrobe:
        raise HTTPException(status_code=400, detail="No wardrobe items provided.")
    
    # Create optimized prompt
    prompt = outfit_engine.create_prompt(request, gender)
    
    try:
        # Plan-based AI configuration
        ai_config = {
            "free": {"max_tokens": 500, "temperature": 0.7},
            "premium": {"max_tokens": 800, "temperature": 0.8}
        }
        
        config = ai_config.get(plan, ai_config["free"])
        
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system", 
                    "content": f"Fashion stylist. Respond in {request.language} with exact JSON format only."
                },
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            **config
        )
        
        response_content = completion.choices[0].message.content
        if not response_content:
            raise HTTPException(status_code=500, detail="AI returned empty response.")
        
        try:
            outfit_response = json.loads(response_content)
            
            # Validation
            if not outfit_response.get("items"):
                raise HTTPException(status_code=500, detail="No items in AI response.")
            
            # Check if items exist in wardrobe
            suggested_ids = {item.get("id") for item in outfit_response.get("items", [])}
            wardrobe_ids = {item.id for item in request.wardrobe}
            invalid_ids = suggested_ids - wardrobe_ids
            
            if invalid_ids:
                raise HTTPException(status_code=500, detail=f"AI suggested invalid items: {list(invalid_ids)}")
            
            # Check outfit structure with flexible validation
            if not outfit_engine.validate_outfit_structure(outfit_response.get("items", [])):
                raise HTTPException(status_code=500, detail="Incomplete outfit structure.")
                
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=500, detail=f"Invalid JSON from AI: {str(e)}")
        
        # Update usage
        db.collection('users').document(user_id).update({
            'usage.count': firestore.Increment(1)
        })
        
        # Success log
        print(f"✅ Outfit created: {len(outfit_response.get('items', []))} items, Plan: {plan}")
        
        return outfit_response
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ AI error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"AI suggestion failed: {str(e)}")

@router.get("/usage-status")
async def get_usage_status(user_id: str = Depends(get_current_user_id)):
    """Usage status endpoint"""
    today = str(date.today())
    user_ref = db.collection('users').document(user_id)
    user_doc = user_ref.get()
    
    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User not found")
    
    user_data = user_doc.to_dict()
    plan = user_data.get("plan", "free")
    usage_data = user_data.get("usage", {})
    
    current_usage = usage_data.get("count", 0) if usage_data.get("date") == today else 0
    limit = PLAN_LIMITS.get(plan, 0)
    
    return {
        "plan": plan,
        "current_usage": current_usage,
        "daily_limit": "unlimited" if plan == "premium" else limit,
        "remaining": "unlimited" if plan == "premium" else max(0, limit - current_usage),
        "is_unlimited": plan == "premium",
        "date": today
    }