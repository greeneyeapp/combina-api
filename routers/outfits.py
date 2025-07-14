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

# Plan limitleri
PLAN_LIMITS = {
    "free": 2, 
    "premium": float('inf')
}

class SmartOutfitEngine:
    """Yeni nesil kombin öneri motoru - Full Debug Version"""
    
    def __init__(self):
        print("🔧 SmartOutfitEngine initializing...")
        
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
        
        # Category mapping - English only (client sends English categories)
        self.category_types = {
            'tops': ['t-shirt', 'shirt', 'blouse', 'top', 'bodysuit', 'crop-top', 'tank-top', 'sweater', 'cardigan', 'hoodie', 'turtleneck', 'polo-shirt', 'henley-shirt'],
            'bottoms': ['jeans', 'trousers', 'leggings', 'joggers', 'skirt', 'shorts', 'culottes', 'chino-trousers', 'cargo-pants', 'bottom', 'bottoms'],
            'dresses': ['dress', 'jumpsuit', 'romper'],
            'outerwear': ['coat', 'trenchcoat', 'jacket', 'bomber-jacket', 'denim-jacket', 'leather-jacket', 'blazer', 'vest', 'gilet', 'outerwear'],
            'footwear': ['sneakers', 'heels', 'boots', 'sandals', 'flats', 'loafers', 'wedges', 'classic-shoes', 'boat-shoes', 'footwear', 'shoes'],
            'bags': ['handbag', 'crossbody-bag', 'backpack', 'clutch', 'tote-bag', 'fanny-pack', 'messenger-bag', 'briefcase', 'bag', 'bags'],
            'accessories': ['jewelry', 'scarf', 'sunglasses', 'belt', 'hat', 'beanie', 'watch', 'tie', 'hijab-shawl', 'accessory', 'accessories']
        }
        
        print("✅ SmartOutfitEngine initialized successfully")
    
    def get_category_type(self, category: str) -> str:
        """Kategoriyi tip grubuna göre sınıflandır"""
        print(f"   🔍 Classifying category: {category}")
        category_lower = category.lower()
        for category_type, categories in self.category_types.items():
            if category_lower in categories:
                print(f"   ✅ Category '{category}' classified as '{category_type}'")
                return category_type
        print(f"   ⚠️ Category '{category}' classified as 'other'")
        return 'other'  # Bilinmeyen kategoriler için
    
    def filter_wardrobe(self, wardrobe: List[ClothingItem], weather: str, occasion: str) -> List[ClothingItem]:
        """Context-aware wardrobe filtering - flexible keyword system"""
        print(f"🔍 Filtering wardrobe: {len(wardrobe)} items for {weather} weather, {occasion} occasion")
        
        weather_rule = self.weather_keywords.get(weather, self.weather_keywords['mild'])
        occasion_styles = self.occasion_styles.get(occasion, ['casual'])
        
        print(f"   📋 Weather rule: exclude={weather_rule['exclude_keywords']}")
        print(f"   📋 Occasion styles: {occasion_styles}")
        
        filtered = []
        excluded_count = 0
        
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
                excluded_count += 1
                continue
            
            # Style compatibility check
            item_styles = item.style if isinstance(item.style, list) else [item.style]
            if not any(style in occasion_styles for style in item_styles):
                excluded_count += 1
                continue
            
            filtered.append(item)
        
        print(f"   ✅ Filtered result: {len(filtered)} items kept, {excluded_count} excluded")
        return filtered
    
    def group_by_category_type(self, wardrobe: List[ClothingItem]) -> Dict[str, List[ClothingItem]]:
        """Group items by category type (tops, bottoms, footwear etc.)"""
        print(f"🔍 Grouping {len(wardrobe)} items by category type")
        groups = defaultdict(list)
        
        for item in wardrobe:
            category_type = self.get_category_type(item.category)
            groups[category_type].append(item)
        
        group_summary = {k: len(v) for k, v in groups.items()}
        print(f"   ✅ Groups created: {group_summary}")
        return dict(groups)
    
    def create_compact_wardrobe(self, wardrobe: List[ClothingItem]) -> str:
        """Ultra compact wardrobe representation - flexible categories"""
        print(f"🔍 Creating compact wardrobe representation for {len(wardrobe)} items")
        
        groups = self.group_by_category_type(wardrobe)
        compact_parts = []
        
        for category_type, items in groups.items():
            item_strings = []
            for item in items:
                colors = item.colors[0] if item.colors else item.color or "neutral"
                item_strings.append(f"{item.id}:{item.name}({colors})")
            
            compact_parts.append(f"{category_type}[{','.join(item_strings)}]")
        
        compact_result = " | ".join(compact_parts)
        print(f"   ✅ Compact wardrobe created - Length: {len(compact_result)} chars")
        print(f"   📝 Preview: {compact_result[:100]}...")
        return compact_result
    
    def sample_wardrobe(self, wardrobe: List[ClothingItem], max_items: int = 30) -> List[ClothingItem]:
        """Smart sampling for large wardrobes"""
        print(f"🔍 Sampling wardrobe: {len(wardrobe)} items → max {max_items}")
        
        if len(wardrobe) <= max_items:
            print(f"   ✅ No sampling needed: {len(wardrobe)} <= {max_items}")
            return wardrobe
        
        groups = self.group_by_category_type(wardrobe)
        sampled = []
        
        # Her kategori tipinden eşit sayıda al
        items_per_type = max(2, max_items // len(groups))
        print(f"   📊 Items per type: {items_per_type}")
        
        for category_type, items in groups.items():
            sample_size = min(len(items), items_per_type)
            sampled_items = random.sample(items, sample_size)
            sampled.extend(sampled_items)
            print(f"   ✅ {category_type}: {sample_size}/{len(items)} items sampled")
        
        final_sample = sampled[:max_items]
        print(f"   ✅ Final sample: {len(final_sample)} items")
        return final_sample
    
    def get_recent_items(self, last_outfits: List) -> Set[str]:
        """Get recently used item IDs"""
        print(f"🔍 Extracting recent items from {len(last_outfits)} outfits")
        
        recent = set()
        for outfit in last_outfits[-3:]:  # Son 3 kombin
            recent.update(outfit.items)
        
        print(f"   ✅ Recent items found: {len(recent)} unique items")
        print(f"   📋 Recent IDs: {list(recent)[:10]}..." if recent else "   📋 No recent items")
        return recent
    
    def validate_outfit_structure(self, suggested_items: List[Dict]) -> bool:
        """Kombin yapısını validate et - daha esnek erkek kuralları"""
        print(f"🔍 Validating outfit structure for {len(suggested_items)} items")
        
        suggested_categories = [item.get("category", "") for item in suggested_items]
        category_types = [self.get_category_type(cat) for cat in suggested_categories]
        
        print(f"   📋 Suggested categories: {suggested_categories}")
        print(f"   📋 Category types: {category_types}")
        
        # Temel kontroller
        has_top_or_dress = any(ct in ['tops', 'dresses'] for ct in category_types)
        has_bottom_or_dress = any(ct in ['bottoms', 'dresses'] for ct in category_types)
        has_footwear = any(ct == 'footwear' for ct in category_types)
        has_dress = 'dresses' in category_types
        
        print(f"   📊 Structure check:")
        print(f"      - Has top/dress: {has_top_or_dress}")
        print(f"      - Has bottom/dress: {has_bottom_or_dress}")
        print(f"      - Has footwear: {has_footwear}")
        print(f"      - Has dress: {has_dress}")
        
        # İdeal validation: (Top + Bottom + Footwear) VEYA (Dress + Footwear)
        ideal_valid = has_footwear and (
            (has_top_or_dress and has_bottom_or_dress) or has_dress
        )
        
        if ideal_valid:
            print(f"   ✅ Structure valid (ideal): {ideal_valid}")
            return True
        
        # Esnek validation: En az top + footwear varsa geçerli say
        minimal_valid = has_top_or_dress and has_footwear
        if minimal_valid:
            print(f"   ⚠️ Structure valid (minimal): top + footwear only")
            return True
        
        print(f"   ❌ Structure invalid: missing essential items")
        return False
    
    def create_prompt(self, request: OutfitRequest, gender: str) -> str:
        """Yeni minimal prompt sistemi"""
        print(f"🔍 Creating prompt for {gender} user")
        
        # 1. Wardrobe filtering & sampling
        print(f"   Step 1: Filtering wardrobe")
        filtered_wardrobe = self.filter_wardrobe(
            request.wardrobe, 
            request.weather_condition, 
            request.occasion
        )
        
        print(f"   Step 2: Sampling if needed")
        if len(filtered_wardrobe) > 30:
            filtered_wardrobe = self.sample_wardrobe(filtered_wardrobe, 30)
        
        # 2. Compact representation
        print(f"   Step 3: Creating compact representation")
        wardrobe_compact = self.create_compact_wardrobe(filtered_wardrobe)
        
        # 3. Recent items to avoid
        print(f"   Step 4: Processing recent items")
        recent_items = self.get_recent_items(request.last_5_outfits)
        recent_str = f"Recently used: {','.join(list(recent_items)[:8])}" if recent_items else ""
        
        # 4. Plan-based prompt selection
        print(f"   Step 5: Selecting prompt template for {request.plan} plan")
        if request.plan == 'premium':
            prompt = self._create_premium_prompt(request, gender, wardrobe_compact, recent_str)
        else:
            prompt = self._create_free_prompt(request, gender, wardrobe_compact, recent_str)
        
        print(f"   ✅ Prompt created - Length: {len(prompt)} chars")
        return prompt
    
    def _create_free_prompt(self, request: OutfitRequest, gender: str, wardrobe: str, recent: str) -> str:
        """Free plan minimal prompt"""
        print(f"   🔸 Creating FREE plan prompt")
        
        structure_req = "REQUIRED: top + bottom + footwear. OPTIONAL: outerwear/accessories"
        if gender == "female":
            structure_req = "REQUIRED: (top + bottom + footwear) OR (dress + footwear). OPTIONAL: outerwear/accessories"
            
        return f"""Create {gender} outfit for {request.occasion} in {request.weather_condition} weather.
Response language: {request.language}

Available items: {wardrobe}
{recent}

{structure_req}
- Use EXACT category names from wardrobe (keep English: top, bottom, footwear, outerwear, dress, etc.)
- Translate only name and description to {request.language}
- MUST include at least 3 items for complete outfit

JSON format:
{{"items":[{{"id":"exact_id","name":"translated_name","category":"english_category"}}],"description":"description_in_{request.language}","suggestion_tip":"tip_in_{request.language}"}}"""
    
    def _create_premium_prompt(self, request: OutfitRequest, gender: str, wardrobe: str, recent: str) -> str:
        """Premium plan enhanced prompt"""
        print(f"   💎 Creating PREMIUM plan prompt")
        
        structure_req = "REQUIRED: top + bottom + footwear. OPTIONAL: outerwear/accessories"
        if gender == "female":
            structure_req = "REQUIRED: (top + bottom + footwear) OR (dress + footwear). OPTIONAL: outerwear/accessories"
            
        return f"""Expert {gender} styling for {request.occasion} in {request.weather_condition}.
Response language: {request.language}

Wardrobe: {wardrobe}
{recent}

Create complete outfit with color harmony and fashion principles.
{structure_req}
- Use EXACT category names from wardrobe (keep English: top, bottom, footwear, outerwear, dress, etc.)
- Translate only name, description, and tips to {request.language}
- MUST include at least 3 items for complete outfit

JSON format:
{{"items":[{{"id":"exact_id","name":"translated_name","category":"english_category"}}],"description":"description_in_{request.language}","suggestion_tip":"tip_in_{request.language}","pinterest_links":[{{"title":"title_in_{request.language}","url":"pinterest_url"}}]}}"""

# Global engine instance
print("🚀 Initializing SmartOutfitEngine...")
outfit_engine = SmartOutfitEngine()
print("✅ SmartOutfitEngine ready!")

async def check_usage_and_get_user_data(user_id: str = Depends(get_current_user_id)):
    """Usage kontrolü ve user data"""
    print(f"🔍 Checking usage for user: {user_id[:8]}...")
    
    today = str(date.today())
    user_ref = db.collection('users').document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        print(f"   ❌ User not found: {user_id[:8]}")
        raise HTTPException(status_code=404, detail="User profile not found.")
    
    user_data = user_doc.to_dict()
    plan = user_data.get("plan", "free")
    print(f"   ✅ User found - Plan: {plan}")

    # Usage check
    if user_data.get("usage", {}).get("date") != today:
        print(f"   🔄 Resetting daily usage for new day")
        user_data["usage"] = {"count": 0, "date": today}
        user_ref.update({"usage": user_data["usage"]})
    
    current_usage = user_data.get("usage", {}).get("count", 0)
    limit = PLAN_LIMITS.get(plan, 0)
    
    print(f"   📊 Usage check: {current_usage}/{limit if limit != float('inf') else 'unlimited'}")
    
    if plan != "premium" and current_usage >= limit:
        print(f"   ❌ Usage limit exceeded")
        raise HTTPException(
            status_code=429, 
            detail=f"Daily limit of {limit} requests reached for {plan.capitalize()} plan."
        )
    
    print(f"   ✅ Usage check passed")
    return {"user_id": user_id, "gender": user_data.get("gender", "unisex"), "plan": plan}

@router.post("/suggest-outfit", response_model=OutfitResponse)
async def suggest_outfit(request: OutfitRequest, user_info: dict = Depends(check_usage_and_get_user_data)):
    """Yeni nesil kombin önerisi - Full Debug Version"""
    try:
        print(f"🚀 ========== OUTFIT SUGGESTION START ==========")
        print(f"🔍 Step 1: Initial data extraction")
        
        user_id = user_info["user_id"]
        plan = user_info["plan"]
        print(f"   ✅ User ID: {user_id[:8]}..., Plan: {plan}")
        
        # Gender determination
        gender = request.gender if request.gender in ['male', 'female'] else user_info.get("gender", "unisex")
        print(f"   ✅ Gender determined: {gender}")
        
        # Request data
        print(f"🔍 Step 2: Request validation")
        print(f"   ✅ Occasion: {request.occasion}")
        print(f"   ✅ Weather: {request.weather_condition}")
        print(f"   ✅ Language: {request.language}")
        print(f"   ✅ Wardrobe size: {len(request.wardrobe)}")
        print(f"   ✅ Last outfits count: {len(request.last_5_outfits)}")
        
        # Wardrobe validation
        if not request.wardrobe:
            print(f"   ❌ No wardrobe items provided")
            raise HTTPException(status_code=400, detail="No wardrobe items provided.")
        
        print(f"🔍 Step 3: Creating prompt")
        # Create optimized prompt
        prompt = outfit_engine.create_prompt(request, gender)
        print(f"   ✅ Prompt created - Length: {len(prompt)} chars")
        print(f"   📝 Prompt preview: {prompt[:200]}...")
        
        print(f"🔍 Step 4: AI Configuration")
        # Plan-based AI configuration
        ai_config = {
            "free": {"max_tokens": 500, "temperature": 0.7},
            "premium": {"max_tokens": 800, "temperature": 0.8}
        }
        
        config = ai_config.get(plan, ai_config["free"])
        print(f"   ✅ AI Config: {config}")
        
        print(f"🔍 Step 5: OpenAI API Call")
        print(f"   🔄 Calling OpenAI API...")
        
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
        print(f"   ✅ OpenAI API call successful")
        
        print(f"🔍 Step 6: Processing AI Response")
        response_content = completion.choices[0].message.content
        print(f"   ✅ Response received - Length: {len(response_content) if response_content else 0} chars")
        
        if not response_content:
            print(f"   ❌ AI returned empty response")
            raise HTTPException(status_code=500, detail="AI returned empty response.")
        
        print(f"   📝 AI Response: {response_content}")
        
        print(f"🔍 Step 7: JSON Parsing")
        try:
            outfit_response = json.loads(response_content)
            print(f"   ✅ JSON parsed successfully")
            print(f"   📊 Response keys: {list(outfit_response.keys())}")
        except json.JSONDecodeError as e:
            print(f"   ❌ JSON decode error: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Invalid JSON from AI: {str(e)}")
        
        print(f"🔍 Step 8: Validation")
        if not outfit_response.get("items"):
            print(f"   ❌ No items in AI response")
            raise HTTPException(status_code=500, detail="No items in AI response.")
        
        print(f"   ✅ Items count: {len(outfit_response.get('items', []))}")
        
        # Check if items exist in wardrobe
        suggested_ids = {item.get("id") for item in outfit_response.get("items", [])}
        wardrobe_ids = {item.id for item in request.wardrobe}
        invalid_ids = suggested_ids - wardrobe_ids
        
        print(f"   📋 Suggested IDs: {suggested_ids}")
        print(f"   📋 Wardrobe IDs (first 10): {list(wardrobe_ids)[:10]}...")
        
        if invalid_ids:
            print(f"   ❌ Invalid item IDs: {invalid_ids}")
            raise HTTPException(status_code=500, detail=f"AI suggested invalid items: {list(invalid_ids)}")
        
        print(f"   ✅ All suggested items exist in wardrobe")
        
        # Check outfit structure with flexible validation
        print(f"🔍 Step 9: Outfit Structure Validation")
        if not outfit_engine.validate_outfit_structure(outfit_response.get("items", [])):
            print(f"   ❌ Incomplete outfit structure")
            raise HTTPException(status_code=500, detail="Incomplete outfit structure.")
        
        print(f"   ✅ Outfit structure is valid")
        
        print(f"🔍 Step 10: Database Update")
        # Update usage
        db.collection('users').document(user_id).update({
            'usage.count': firestore.Increment(1)
        })
        print(f"   ✅ Usage count updated")
        
        # Success log
        suggestion_count = len(outfit_response.get("items", []))
        has_pinterest = bool(outfit_response.get("pinterest_links"))
        print(f"🎉 SUCCESS: Outfit created - {suggestion_count} items, Plan: {plan}, Pinterest: {has_pinterest}")
        print(f"🚀 ========== OUTFIT SUGGESTION END ==========")
        
        return outfit_response
        
    except HTTPException:
        print(f"🚀 ========== OUTFIT SUGGESTION END (HTTP ERROR) ==========")
        raise
    except Exception as e:
        print(f"❌ CRITICAL ERROR in suggest_outfit:")
        print(f"   Error type: {type(e).__name__}")
        print(f"   Error message: {str(e)}")
        print(f"   Full traceback: {traceback.format_exc()}")
        print(f"🚀 ========== OUTFIT SUGGESTION END (FATAL ERROR) ==========")
        raise HTTPException(status_code=500, detail=f"AI suggestion failed: {str(e)}")

@router.get("/usage-status")
async def get_usage_status(user_id: str = Depends(get_current_user_id)):
    """Usage status endpoint"""
    print(f"🔍 Getting usage status for user: {user_id[:8]}...")
    
    today = str(date.today())
    user_ref = db.collection('users').document(user_id)
    user_doc = user_ref.get()
    
    if not user_doc.exists:
        print(f"   ❌ User not found")
        raise HTTPException(status_code=404, detail="User not found")
    
    user_data = user_doc.to_dict()
    plan = user_data.get("plan", "free")
    usage_data = user_data.get("usage", {})
    
    current_usage = usage_data.get("count", 0) if usage_data.get("date") == today else 0
    limit = PLAN_LIMITS.get(plan, 0)
    
    result = {
        "plan": plan,
        "current_usage": current_usage,
        "daily_limit": "unlimited" if plan == "premium" else limit,
        "remaining": "unlimited" if plan == "premium" else max(0, limit - current_usage),
        "is_unlimited": plan == "premium",
        "date": today
    }
    
    print(f"   ✅ Usage status: {result}")
    return result