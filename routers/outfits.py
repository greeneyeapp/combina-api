from fastapi import APIRouter, Depends, HTTPException, Request
from openai import OpenAI
import json
from datetime import date, datetime
from firebase_admin import firestore
from typing import List, Dict, Any, Tuple
from urllib.parse import quote
import traceback
import asyncio
import time

from core.config import settings
from core.security import get_current_user_id, require_authenticated_user
from schemas import OutfitRequest, OutfitResponse, OptimizedClothingItem, SuggestedItem, PinterestLink
from core import localization
from core.localization import SAME_OUTFIT_ERRORS
from core.usage import PLAN_LIMITS

router = APIRouter(prefix="/api", tags=["outfits"])

primary_client = OpenAI(api_key=settings.OPENAI_API_KEY)
secondary_client = OpenAI(api_key=settings.OPENAI_API_KEY2)
db = firestore.client()

POPULAR_COLOR_COMBINATIONS = {
    "navy": {"colors": ["white", "beige", "mustard", "pink"], "effect": "Classic & Noble"},
    "black": {"colors": ["silver", "red", "white"], "effect": "Strong & Timeless"},
    "beige": {"colors": ["dark-red", "navy", "orange"], "effect": "Natural & Chic"},
    "tan": {"colors": ["dark-red", "navy", "orange"], "effect": "Natural & Chic"},
    "gray": {"colors": ["dark-red", "purple"], "effect": "Balanced & Modern"},
    "khaki": {"colors": ["dark-red", "mustard", "black"], "effect": "Comfortable & Urban"},
    "jeans": {"colors": "any", "effect": "Versatile (Joker Piece)"}
}

COLOR_HARMONY_GUIDE = """
- Monochromatic: Different tones of the same color (e.g., navy blue + ice blue).
- Analogous: Colors that are next to each other on the color wheel (e.g., red and orange).
- Complementary: Colors that are opposite each other (e.g., navy and orange, red and green).
"""

GENERAL_STYLE_PRINCIPLES = """
- Fit is Key: Clothes should fit well—not too tight, not too loose.
- Prioritize Timeless Pieces: Classic items like a white shirt, blazer, or classic trousers are always a good choice.
- Layering is Stylish: Encourage combinations like a t-shirt under a shirt and a jacket on top.
- Harmonize Accessories: Ensure bag and shoes are compatible. Use accessories like scarves or watches to enrich the look.
- Avoid Clutter: Do not use more than 3 dominant colors at once. Avoid excessive logos or patterns.
- Seasonality: Ensure fabrics are appropriate for the weather (e.g., no wool in hot weather).
"""

OCCASION_REQUIREMENTS_FEMALE = {
    "office-day": {"valid_structures": [{"top": {"blouse", "shirt", "sweater"}, "bottom": {"trousers", "mini-skirt", "midi-skirt", "long-skirt"}, "shoes": {"classic-shoes", "loafers", "heels", "sneakers", "boots"}}, {"one-piece": {"casual-dress", "jumpsuit"}, "outerwear": {"blazer", "cardigan"}, "shoes": {"classic-shoes", "loafers", "heels", "sneakers"}}], "forbidden_categories": {"track-bottom", "hoodie", "athletic-shorts", "crop-top"}},
    "business-meeting": {"valid_structures": [{"top": {"blouse", "shirt"}, "bottom": {"trousers", "mini-skirt", "midi-skirt"}, "outerwear": {"blazer", "suit-jacket"}, "shoes": {"heels", "classic-shoes"}}, {"one-piece": {"evening-dress"}, "outerwear": {"blazer"}, "shoes": {"heels"}}], "forbidden_categories": {"jeans", "sneakers", "t-shirt", "sweatshirt"}},
    "celebration": {"valid_structures": [{"one-piece": {"evening-dress", "jumpsuit", "casual-dress"}, "shoes": {"heels", "sandals", "sneakers", "flats"}}, {"top": {"blouse", "crop-top"}, "bottom": {"trousers", "mini-skirt", "midi-skirt", "long-skirt"}, "shoes": {"heels", "sneakers", "boots"}}], "forbidden_categories": {"track-bottom", "hoodie", "sporty-dress"}},
    "formal-dinner": {"valid_structures": [{"one-piece": {"evening-dress", "jumpsuit"}, "shoes": {"heels", "classic-shoes"}}, {"top": {"blouse"}, "bottom": {"trousers", "mini-skirt", "midi-skirt"}, "outerwear": {"blazer"}, "shoes": {"heels"}}], "forbidden_categories": {"sneakers", "jeans", "casual-dress", "t-shirt"}},
    "wedding": {"valid_structures": [{"one-piece": {"evening-dress", "jumpsuit", "modest-evening-dress"}, "shoes": {"heels", "sandals", "classic-shoes"}}], "forbidden_categories": {"sneakers", "boots", "jeans", "t-shirt"}},
    "yoga-pilates": {"valid_structures": [{"top": {"tank-top", "bralette", "t-shirt"}, "bottom": {"leggings", "track-bottom"}}], "forbidden_categories": {"jeans", "shirt", "blouse", "boots", "heels", "sweater", "casual-dress"}},
    "gym": {"valid_structures": [{"top": {"t-shirt", "tank-top", "track-top"}, "bottom": {"leggings", "track-bottom", "athletic-shorts"}, "shoes": {"sneakers", "casual-sport-shoes"}}], "forbidden_categories": {"jeans", "shirt", "blouse", "heels"}},
}

OCCASION_REQUIREMENTS_MALE = {
    "office-day": {"valid_structures": [{"top": {"shirt", "polo-shirt", "sweater"}, "bottom": {"trousers", "suit-trousers"}, "shoes": {"classic-shoes", "loafers", "sneakers", "boots"}}], "forbidden_categories": {"track-bottom", "hoodie", "athletic-shorts", "tank-top"}},
    "business-meeting": {"valid_structures": [{"top": {"shirt"}, "bottom": {"suit-trousers"}, "outerwear": {"suit-jacket", "blazer"}, "shoes": {"classic-shoes", "loafers"}}], "forbidden_categories": {"jeans", "sneakers", "t-shirt", "polo-shirt"}},
    "celebration": {"valid_structures": [{"top": {"shirt", "polo-shirt"}, "bottom": {"trousers", "jeans"}, "outerwear": {"blazer"}, "shoes": {"classic-shoes", "sneakers", "boots"}}], "forbidden_categories": {"track-bottom", "hoodie", "athletic-shorts"}},
    "formal-dinner": {"valid_structures": [{"top": {"shirt"}, "bottom": {"suit-trousers"}, "outerwear": {"suit-jacket", "tuxedo"}, "shoes": {"classic-shoes"}}], "forbidden_categories": {"sneakers", "jeans", "polo-shirt", "t-shirt"}},
    "wedding": {"valid_structures": [{"top": {"shirt"}, "bottom": {"suit-trousers"}, "outerwear": {"suit-jacket", "tuxedo"}, "shoes": {"classic-shoes"}}], "forbidden_categories": {"sneakers", "boots", "jeans", "polo-shirt", "t-shirt"}},
    "yoga-pilates": {"valid_structures": [{"top": {"t-shirt", "tank-top"}, "bottom": {"track-bottom", "athletic-shorts"}}], "forbidden_categories": {"jeans", "shirt", "polo-shirt", "boots", "classic-shoes", "sweater"}},
    "gym": {"valid_structures": [{"top": {"t-shirt", "tank-top"}, "bottom": {"track-bottom", "athletic-shorts"}, "shoes": {"sneakers", "casual-sport-shoes"}}], "forbidden_categories": {"jeans", "shirt", "classic-shoes", "boots"}},
}

def simplify_rules_for_client(rules_dict: Dict[str, Any]) -> Dict[str, Any]:
    simplified = {}
    for occasion, rules in rules_dict.items():
        valid_structures = rules.get("valid_structures", [])
        if not valid_structures:
            continue
        
        required_one_of: Dict[str, set] = {}
        for struct in valid_structures:
            for main_cat, sub_cats in struct.items():
                if main_cat not in required_one_of:
                    required_one_of[main_cat] = set()
                required_one_of[main_cat].update(sub_cats)
        
        simplified[occasion] = {
            "required_one_of": {k: sorted(list(v)) for k, v in required_one_of.items()}
        }
    return simplified

class GPTLoadBalancer:
    def __init__(self): 
        self.primary_failures, self.secondary_failures = 0, 0
        self.last_primary_use, self.last_secondary_use = 0, 0
        self.max_failures, self.failure_reset_time = 3, 300
    
    def get_available_client(self):
        current_time = time.time()
        if current_time - self.last_primary_use > self.failure_reset_time: self.primary_failures = 0
        if current_time - self.last_secondary_use > self.failure_reset_time: self.secondary_failures = 0
        if self.primary_failures < self.max_failures: self.last_primary_use = current_time; return primary_client, "primary"
        elif self.secondary_failures < self.max_failures: self.last_secondary_use = current_time; return secondary_client, "secondary"
        else: self.primary_failures = 0; self.last_primary_use = current_time; return primary_client, "primary"
    
    def report_failure(self, client_type: str):
        if client_type == "primary": self.primary_failures += 1
        else: self.secondary_failures += 1
    
    def report_success(self, client_type: str):
        if client_type == "primary": self.primary_failures = max(0, self.primary_failures - 1)
        else: self.secondary_failures = max(0, self.secondary_failures - 1)

gpt_balancer = GPTLoadBalancer()

class AdvancedOutfitEngine:
    def check_wardrobe_compatibility(self, occasion: str, wardrobe: List[OptimizedClothingItem], gender: str):
        requirements_map = OCCASION_REQUIREMENTS_MALE if gender == 'male' else OCCASION_REQUIREMENTS_FEMALE
        if occasion not in requirements_map: return
        
        occasion_rules = requirements_map[occasion]
        valid_structures = occasion_rules.get("valid_structures", [])
        if not valid_structures: return
        
        wardrobe_categories = {item.category for item in wardrobe}
        can_create_any_structure = any(
            all(wardrobe_categories.intersection(req_cats) for _, req_cats in struct.items()) 
            for struct in valid_structures
        )
        
        if not can_create_any_structure:
            all_possible_categories = {
                cat for struct in valid_structures 
                for cats in struct.values() for cat in cats
            }
            error_detail = f"Your wardrobe is not suitable for '{occasion}'. Please add appropriate items like: {', '.join(sorted(list(all_possible_categories)))}."
            raise HTTPException(status_code=422, detail=error_detail)

    def create_compact_wardrobe_string(self, wardrobe: List[OptimizedClothingItem]) -> str:
        return "\n".join([
            f"i:{item.id},n:{item.name},c:{item.category},cl:{';'.join(item.colors)},st:{';'.join(item.style)}" 
            for item in wardrobe
        ])

    def create_advanced_prompt(self, request: OutfitRequest, recent_outfits: List[Dict[str, Any]]) -> str:
        lang_code, gender = request.language, request.gender
        target_language = localization.LANGUAGE_NAMES.get(lang_code, "English")
        en_occasions = localization.get_translation('en', 'occasions')
        occasion_text = en_occasions.get(request.occasion, request.occasion.replace('-', ' '))
        
        avoid_combos_str = "\n".join([
            f"- Combo {i+1}: {', '.join(outfit_map.get('items', []))}" 
            for i, outfit_map in enumerate(recent_outfits) if outfit_map.get('items')
        ]) or "None"
        
        popular_combos_text = "\n".join([
            f"- For a '{details['effect']}' look, combine '{color.capitalize()}' with: {', '.join(details['colors'])}." 
            for color, details in POPULAR_COLOR_COMBINATIONS.items() if details['colors'] != "any"
        ])
        popular_combos_text += "\n- Denim Blue is a 'Joker' (versatile) piece and works with almost any color."
        
        pinterest_instructions = ""
        if request.plan == "premium":
            pinterest_instructions = f''',"pinterest_links": [ ... ]'''
        
        return f"""
You are an expert fashion stylist...
ITEM DATABASE (Format: i=id, n=name, c=category, cl=colors(;-separated), st=styles(;-separated)):
{self.create_compact_wardrobe_string(request.wardrobe)}
JSON RESPONSE STRUCTURE:
{{ "items": [...], "description": "...", "suggestion_tip": "..." {pinterest_instructions} }}"""

    def validate_outfit_structure(self, items_from_ai: List[Dict[str, str]], wardrobe: List[OptimizedClothingItem]) -> List[SuggestedItem]:
        if not items_from_ai or not isinstance(items_from_ai, list): return []
        wardrobe_map = {item.id: item for item in wardrobe}
        return [
            SuggestedItem(**item) for item in items_from_ai 
            if isinstance(item, dict) and item.get("id") in wardrobe_map
        ]

outfit_engine = AdvancedOutfitEngine()

async def check_usage_and_get_user_data(
    request: Request,
    user_data_tuple: Tuple[str, bool] = Depends(get_current_user_id)
) -> Dict[str, Any]:
    user_id, is_anonymous = user_data_tuple
    today = str(date.today())
    
    print(f"🔄 Processing {'guest' if is_anonymous else 'authenticated'} user: {user_id[:16]}...")
    
    user_ref = db.collection('users').document(user_id)
    user_doc = user_ref.get()
    
    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User profile not found.")
    
    user_data_dict = user_doc.to_dict()
    plan = user_data_dict.get("plan", "free")
    usage_data = user_data_dict.get("usage", {})
    
    if usage_data.get("date") != today:
        usage_data = {"count": 0, "date": today, "rewarded_count": 0}
        user_ref.update({"usage": usage_data})
    
    user_info = {
        "user_id": user_id,
        "gender": user_data_dict.get("gender", "unisex"),
        "plan": plan,
        "recent_outfits": user_data_dict.get("recent_outfits", []),
        "is_anonymous": is_anonymous
    }
    
    if plan == "premium":
        return user_info
    
    limit = PLAN_LIMITS.get(plan, 2)
    if usage_data.get("count", 0) >= (limit + usage_data.get("rewarded_count", 0)):
        raise HTTPException(status_code=429, detail="Daily limit reached.")
    
    return user_info

async def call_gpt_with_retry(prompt: str, plan: str, attempt: int = 1, max_retries: int = 2) -> str:
    base_temp = 0.7
    current_temp = min(base_temp + (0.1 * (attempt - 1)), 1.0)
    
    config = {
        "free": {"max_tokens": 900}, 
        "premium": {"max_tokens": 1300},
    }
    gpt_config = config.get(plan, config["free"])
    gpt_config["temperature"] = current_temp
    
    for i in range(max_retries + 1):
        client, client_type = gpt_balancer.get_available_client()
        try:
            print(f"📡 Calling GPT (Attempt: {i+1}, Temp: {current_temp}, Plan: {plan})...")
            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are an expert fashion stylist. Always respond with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                **gpt_config
            )
            
            response_content = completion.choices[0].message.content
            if not response_content:
                raise ValueError("Empty response from GPT")
            
            json.loads(response_content)
            gpt_balancer.report_success(client_type)
            return response_content
            
        except Exception as e:
            print(f"❌ GPT API error on attempt {i + 1} with {client_type}: {str(e)}")
            gpt_balancer.report_failure(client_type)
            if i < max_retries:
                await asyncio.sleep(1)
            else:
                raise e

@router.get("/occasion-rules", tags=["config"])
async def get_occasion_rules(
    request: Request,
    user_data: Tuple[str, bool] = Depends(get_current_user_id)
):
    user_id, is_anonymous = user_data
    print(f"🔧 Serving occasion rules to {'guest' if is_anonymous else 'authenticated'} user: {user_id[:16]}...")
    
    simplified_female = simplify_rules_for_client(OCCASION_REQUIREMENTS_FEMALE)
    simplified_male = simplify_rules_for_client(OCCASION_REQUIREMENTS_MALE)
    
    return {"female": simplified_female, "male": simplified_male}

@router.post("/suggest-outfit", response_model=OutfitResponse, summary="Creates a personalized outfit suggestion")
async def suggest_outfit(
    request: OutfitRequest, 
    user_info: dict = Depends(check_usage_and_get_user_data)
):
    try:
        outfit_engine.check_wardrobe_compatibility(
            request.occasion, request.wardrobe, user_info["gender"]
        )
        
        requirements_map = (OCCASION_REQUIREMENTS_MALE if user_info["gender"] == 'male' 
                          else OCCASION_REQUIREMENTS_FEMALE)
        occasion_rules = requirements_map.get(request.occasion, {})
        forbidden_categories = occasion_rules.get("forbidden_categories", set())
        
        filtered_wardrobe = [
            item for item in request.wardrobe 
            if item.category not in forbidden_categories
        ]
        request.wardrobe = filtered_wardrobe if filtered_wardrobe else request.wardrobe
        
        if not request.wardrobe:
            raise HTTPException(status_code=400, detail="Wardrobe cannot be empty.")

        max_attempts = 2
        final_items = None
        ai_response = None
        base_prompt = outfit_engine.create_advanced_prompt(request, user_info["recent_outfits"])
        existing_outfits_ids = [
            sorted(outfit.get("items", [])) 
            for outfit in user_info.get("recent_outfits", [])
        ]
        hard_avoid_ids = set()

        for attempt in range(1, max_attempts + 1):
            print(f"🤖 AI outfit generation attempt {attempt}/{max_attempts} for {user_info['plan']} user...")
            
            current_prompt = base_prompt
            if hard_avoid_ids:
                avoid_prompt = f"\nCRITICAL AVOIDANCE RULE: You are strictly forbidden from using any of these item IDs: {', '.join(hard_avoid_ids)}\n"
                current_prompt += avoid_prompt

            response_content = await call_gpt_with_retry(
                current_prompt, user_info["plan"], attempt=attempt
            )
            current_ai_response = json.loads(response_content)
            validated_items = outfit_engine.validate_outfit_structure(
                current_ai_response.get("items", []), request.wardrobe
            )
            
            if not validated_items: continue
            new_outfit_ids = sorted([item.id for item in validated_items])
            
            if not user_info["is_anonymous"]:
                if (new_outfit_ids in existing_outfits_ids or 
                    any(item_id in hard_avoid_ids for item_id in new_outfit_ids)):
                    for item_id in new_outfit_ids: hard_avoid_ids.add(item_id)
                    continue
            
            final_items = validated_items
            ai_response = current_ai_response
            break
        
        if not final_items:
            error_message = SAME_OUTFIT_ERRORS.get(request.language, SAME_OUTFIT_ERRORS["en"])
            raise HTTPException(status_code=422, detail=error_message)

        response_data = {
            "items": final_items, 
            "description": ai_response.get("description", ""), 
            "suggestion_tip": ai_response.get("suggestion_tip", ""), 
            "pinterest_links": []
        }
        
        if user_info["plan"] == "premium" and "pinterest_links" in ai_response:
            final_pinterest_links = []
            for link_idea in ai_response.get("pinterest_links", []):
                if "search_query" in link_idea and link_idea["search_query"]:
                    encoded_query = quote(link_idea["search_query"])
                    final_pinterest_links.append(PinterestLink(
                        title=link_idea.get("title", "Inspiration"), 
                        url=f"https://www.pinterest.com/search/pins/?q={encoded_query}"
                    ))
            response_data["pinterest_links"] = final_pinterest_links
        
        new_outfit_map = {"items": sorted([item.id for item in final_items])}
        updated_outfits = [new_outfit_map] + user_info.get("recent_outfits", [])
        trimmed_outfits = updated_outfits[:5]

        db.collection('users').document(user_info["user_id"]).update({
            'usage.count': firestore.Increment(1), 
            'recent_outfits': trimmed_outfits
        })
        print(f"✅ Suggestion provided for {'guest' if user_info['is_anonymous'] else 'authenticated'} user ({user_info['plan']} plan) in '{request.language}'")
        
        return OutfitResponse(**response_data)
        
    except HTTPException as http_exc:
        raise http_exc
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="Failed to parse AI response.")
    except Exception as e:
        print(f"❌ Unhandled error in suggest_outfit: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"An internal server error occurred: {str(e)}")

@router.get("/usage-status", tags=["users"])
async def get_usage_status(
    request: Request,
    user_data_tuple: Tuple[str, bool] = Depends(get_current_user_id)
):
    try:
        user_id, is_anonymous = user_data_tuple
        today = str(date.today())
        
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_data_dict = user_doc.to_dict()
        plan = user_data_dict.get("plan", "free")
        usage_data = user_data_dict.get("usage", {})
        
        current_usage = usage_data.get("count", 0) if usage_data.get("date") == today else 0
        rewarded_count = usage_data.get("rewarded_count", 0) if usage_data.get("date") == today else 0
        
        is_unlimited = plan == 'premium'
        daily_limit = PLAN_LIMITS.get(plan)
        remaining = "unlimited" if is_unlimited else max(0, ((daily_limit or 0) + rewarded_count) - current_usage)
        
        effective_limit = float('inf') if is_unlimited else (daily_limit or 0) + rewarded_count
        percentage_used = 0.0 if is_unlimited else (current_usage / effective_limit) * 100 if effective_limit > 0 else 0
        
        return {
            "plan": plan, "current_usage": current_usage, "rewarded_usage": rewarded_count,
            "daily_limit": "unlimited" if is_unlimited else daily_limit,
            "remaining": remaining, "is_unlimited": is_unlimited,
            "percentage_used": round(percentage_used, 2), "date": today,
            "is_anonymous": is_anonymous
        }
            
    except Exception as e:
        print(f"Error getting usage status: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get usage status")

@router.get("/gpt-status", tags=["dev"])
async def get_gpt_status(
    request: Request,
    user_data: Tuple[str, bool] = Depends(get_current_user_id)
):
    return {
        "primary_failures": gpt_balancer.primary_failures,
        "secondary_failures": gpt_balancer.secondary_failures,
        "max_failures": gpt_balancer.max_failures,
        "status": "healthy" if (gpt_balancer.primary_failures < gpt_balancer.max_failures or 
                              gpt_balancer.secondary_failures < gpt_balancer.max_failures) else "degraded"
    }