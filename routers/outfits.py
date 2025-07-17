# routers/outfits.py (Tam ve Nihai Kod)

from fastapi import APIRouter, Depends, HTTPException
from openai import OpenAI
import json
from datetime import date
from firebase_admin import firestore
from typing import List, Dict, Any
from urllib.parse import quote
import traceback
import asyncio
import time

from core.config import settings
from core.security import get_current_user_id
from schemas import OutfitRequest, OutfitResponse, OptimizedClothingItem, SuggestedItem, PinterestLink
from core import localization

router = APIRouter(prefix="/api", tags=["outfits"])

# --- MEVCUT YAPI KORUNDU: GPT Load Balancer ve Client'lar ---
primary_client = OpenAI(api_key=settings.OPENAI_API_KEY)
secondary_client = OpenAI(api_key=settings.OPENAI_API_KEY2)
db = firestore.client()
PLAN_LIMITS = {"free": 2, "premium": None}

class GPTLoadBalancer:
    def __init__(self): self.primary_failures, self.secondary_failures, self.last_primary_use, self.last_secondary_use, self.max_failures, self.failure_reset_time = 0, 0, 0, 0, 3, 300
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
    """AI prompt yönetimi ve çeviri mantığını içerir."""

    def create_compact_wardrobe_string(self, wardrobe: List[OptimizedClothingItem]) -> str:
        return "\n".join([f"ID: {item.id} | Name: {item.name} | Category: {item.category} | Colors: {', '.join(item.colors)} | Styles: {', '.join(item.style)}" for item in wardrobe])

    def create_advanced_prompt(self, request: OutfitRequest) -> str:
        """AI'a tam ve doğru çeviri yapması için GEREKLİ ve DİNAMİK bilgileri verir."""
        lang_code, gender = request.language, request.gender
        en_occasions = localization.get_translation('en', 'occasions')
        occasion_text = en_occasions.get(request.occasion, request.occasion.replace('-', ' '))
        
        # DİNAMİK OLARAK dil ismini ve çeviri talimatlarını al
        target_language, critical_translation_rules = self._get_language_specific_instructions(lang_code)

        pinterest_instructions = ""
        if request.plan == "premium":
            pinterest_instructions = f''',"pinterest_links": [
            {{
                "title": "A specific title in {target_language} about the chosen items",
                "search_query": "A search query in English. MUST include the gender '{gender}', main item categories, and colors. Example: '{gender} blue t-shirt white linen trousers outfit'"
            }},
            {{
                "title": "A general style title in {target_language} for the occasion",
                "search_query": "A general style search query in English. MUST include the gender '{gender}'. Example: '{gender} summer smart casual style'"
            }}
        ]'''

        prompt = f"""
You are an expert fashion stylist. Create a complete {gender} outfit for the occasion: '{occasion_text}'. The weather is {request.weather_condition}.

CRITICAL LANGUAGE REQUIREMENT:
You MUST write all descriptive fields ("description", "suggestion_tip", and "title" for Pinterest) in {target_language}.
{critical_translation_rules}

CONTEXT:
- Wardrobe: You are provided with {request.context.filtered_wardrobe_size} pre-filtered items from a total of {request.context.total_wardrobe_size}.
- Recent Outfits (Avoid these item IDs): {', '.join([item for outfit in request.last_5_outfits for item in outfit.items][:15]) if request.last_5_outfits else "None"}

REQUIREMENTS:
- Use ONLY the exact item IDs from the database below.
- Keep "description" and "suggestion_tip" concise (1-2 sentences).
- For premium users, provide exactly two different Pinterest link ideas as specified.

ITEM DATABASE:
{self.create_compact_wardrobe_string(request.wardrobe)}

JSON RESPONSE STRUCTURE:
{{
    "items": [{{"id": "item_id_from_database", "name": "Creative Name in {target_language}", "category": "actual_category_from_database"}}],
    "description": "A complete outfit description in {target_language}.",
    "suggestion_tip": "A practical styling tip in {target_language}."
    {pinterest_instructions}
}}
"""
        return prompt

    def _get_language_specific_instructions(self, lang_code: str) -> (str, str):
        """
        YENİ ve DİNAMİK YAPI: Dil koduna göre dil adını ve çeviri talimatlarını döndürür.
        """
        # İngilizce için ekstra talimata gerek yok.
        if lang_code == 'en':
            return "English", ""
        
        # Diğer diller için dinamik olarak talimat oluştur
        target_language_name = localization.LANGUAGE_NAMES.get(lang_code, lang_code.capitalize())
        translations = localization.TRANSLATIONS.get(lang_code, localization.TRANSLATIONS['en'])
        
        color_guide_str = json.dumps(translations.get('colors', {}), ensure_ascii=False)
        category_guide_str = json.dumps(translations.get('categories', {}), ensure_ascii=False)
        
        # Prompt başlıkları ve talimatları artık dinamik
        return target_language_name, f"""
CRITICAL TRANSLATION RULES FOR {target_language_name.upper()}:
- When you mention a color or category, you MUST use the exact {target_language_name} translation from the guides below.
- Do NOT translate them yourself. Find the English key (e.g., "ice-blue") and use its exact {target_language_name} value.

{target_language_name.upper()} COLOR GUIDE: {color_guide_str}
{target_language_name.upper()} CATEGORY GUIDE: {category_guide_str}
"""

    def validate_outfit_structure(self, items_from_ai: List[Dict[str, str]], wardrobe: List[OptimizedClothingItem]) -> List[SuggestedItem]:
        if not items_from_ai or not isinstance(items_from_ai, list): return []
        wardrobe_map = {item.id: item for item in wardrobe}
        return [SuggestedItem(**item) for item in items_from_ai if isinstance(item, dict) and item.get("id") in wardrobe_map]

    def translate_pinterest_query(self, query: str, lang_code: str) -> str:
        if lang_code == 'en' or not query: return query
        translations = localization.TRANSLATIONS.get(lang_code, localization.TRANSLATIONS['en'])
        all_keywords = {**translations.get('colors', {}), **translations.get('categories', {})}
        sorted_keywords = sorted(all_keywords.keys(), key=len, reverse=True)
        for key in sorted_keywords: query = query.replace(key, all_keywords[key])
        return query

outfit_engine = AdvancedOutfitEngine()

async def check_usage_and_get_user_data(user_id: str = Depends(get_current_user_id)):
    today = str(date.today()); user_ref = db.collection('users').document(user_id)
    user_doc = user_ref.get();
    if not user_doc.exists: raise HTTPException(status_code=404, detail="User profile not found.")
    user_data = user_doc.to_dict(); plan = user_data.get("plan", "free")
    usage_data = user_data.get("usage", {});
    if usage_data.get("date") != today: usage_data = {"count": 0, "date": today, "rewarded_count": 0}; user_ref.update({"usage": usage_data})
    if plan == "premium": return {"user_id": user_id, "gender": user_data.get("gender", "male"), "plan": plan}
    current_usage, rewarded_count = usage_data.get("count", 0), usage_data.get("rewarded_count", 0)
    daily_limit = PLAN_LIMITS.get(plan, 2)
    if current_usage >= (daily_limit + rewarded_count): raise HTTPException(status_code=429, detail=f"Daily limit reached.")
    return {"user_id": user_id, "gender": user_data.get("gender", "male"), "plan": plan}

async def call_gpt_with_retry(prompt: str, plan: str, max_retries: int = 2) -> str:
    config = {"free": {"max_tokens": 800, "temperature": 0.75}, "premium": {"max_tokens": 1500, "temperature": 0.75}}
    gpt_config = config.get(plan, config["free"])
    for attempt in range(max_retries + 1):
        client, client_type = gpt_balancer.get_available_client()
        try:
            completion = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "system", "content": "You are an expert fashion stylist. Always respond with valid JSON."}, {"role": "user", "content": prompt}], response_format={"type": "json_object"}, **gpt_config)
            response_content = completion.choices[0].message.content
            if not response_content: raise ValueError("Empty response from GPT")
            json.loads(response_content); gpt_balancer.report_success(client_type)
            print(f"✅ GPT response received from {client_type} client (attempt {attempt + 1})")
            return response_content
        except Exception as e:
            print(f"❌ GPT API error on attempt {attempt + 1} with {client_type}: {str(e)}"); gpt_balancer.report_failure(client_type)
            if attempt < max_retries: await asyncio.sleep(1)
            else: raise e

@router.post("/suggest-outfit", response_model=OutfitResponse, summary="Creates a personalized outfit suggestion")
async def suggest_outfit(request: OutfitRequest, user_info: dict = Depends(check_usage_and_get_user_data)):
    try:
        if not request.wardrobe: raise HTTPException(status_code=400, detail="Wardrobe cannot be empty.")
        prompt = outfit_engine.create_advanced_prompt(request)
        response_content = await call_gpt_with_retry(prompt, user_info["plan"])
        ai_response = json.loads(response_content)
        final_items = outfit_engine.validate_outfit_structure(ai_response.get("items", []), request.wardrobe)
        if not final_items: raise HTTPException(status_code=500, detail="AI failed to create a valid outfit.")
        
        response_data = {"items": final_items, "description": ai_response.get("description", ""), "suggestion_tip": ai_response.get("suggestion_tip", ""), "pinterest_links": []}
        
        if user_info["plan"] == "premium" and "pinterest_links" in ai_response:
            final_pinterest_links = []
            for link_idea in ai_response.get("pinterest_links", []):
                if "search_query" in link_idea and link_idea["search_query"]:
                    translated_query = outfit_engine.translate_pinterest_query(link_idea["search_query"], request.language)
                    encoded_query = quote(translated_query)
                    final_pinterest_links.append(PinterestLink(title=link_idea.get("title", "Inspiration"), url=f"https://www.pinterest.com/search/pins/?q={encoded_query}"))
            response_data["pinterest_links"] = final_pinterest_links

        db.collection('users').document(user_info["user_id"]).update({'usage.count': firestore.Increment(1)})
        print(f"✅ Outfit suggestion created and provided in '{request.language}' for {user_info['plan']} user")
        return OutfitResponse(**response_data)
        
    except json.JSONDecodeError: raise HTTPException(status_code=502, detail="Failed to parse AI response.")
    except HTTPException: raise
    except Exception as e:
        print(f"❌ Outfit suggestion error: {traceback.format_exc()}"); raise HTTPException(status_code=500, detail=f"An internal server error occurred: {str(e)}")

@router.get("/usage-status", tags=["users"])
async def get_usage_status(user_id: str = Depends(get_current_user_id)):
    try:
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get();
        if not user_doc.exists: raise HTTPException(status_code=404, detail="User not found")
        user_data, plan, today = user_doc.to_dict(), user_data.get("plan", "free"), str(date.today())
        usage_data = user_data.get("usage", {}); current_usage = usage_data.get("count", 0) if usage_data.get("date") == today else 0
        rewarded_count = usage_data.get("rewarded_count", 0) if usage_data.get("date") == today else 0
        daily_limit = PLAN_LIMITS.get(plan)
        is_unlimited = plan == 'premium'
        remaining = "unlimited" if is_unlimited else max(0, (daily_limit + rewarded_count) - current_usage)
        effective_limit = float('inf') if is_unlimited else daily_limit + rewarded_count
        percentage_used = 0.0 if is_unlimited else (current_usage / effective_limit) * 100 if effective_limit > 0 else 0
        return {"plan": plan, "current_usage": current_usage, "rewarded_usage": rewarded_count, "daily_limit": "unlimited" if is_unlimited else daily_limit, "remaining": remaining, "is_unlimited": is_unlimited, "percentage_used": round(percentage_used, 2), "date": today}
    except Exception as e:
        print(f"Error getting usage status: {str(e)}"); raise HTTPException(status_code=500, detail="Failed to get usage status")

@router.get("/gpt-status", tags=["dev"])
async def get_gpt_status(user_id: str = Depends(get_current_user_id)):
    return {"primary_failures": gpt_balancer.primary_failures, "secondary_failures": gpt_balancer.secondary_failures, "max_failures": gpt_balancer.max_failures, "status": "healthy" if (gpt_balancer.primary_failures < gpt_balancer.max_failures or gpt_balancer.secondary_failures < gpt_balancer.max_failures) else "degraded"}