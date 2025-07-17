# outfits.py

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

# Proje yapınıza göre import yollarını güncelleyin
from core.config import settings
from core.security import get_current_user_id
# YENİ: Şema artık client'tan gelen optimize edilmiş modeli bekliyor
from schemas import OutfitRequest, OutfitResponse, OptimizedClothingItem
# YENİ: Merkezi lokalizasyon dosyamızı import ediyoruz
from core import localization

router = APIRouter(prefix="/api", tags=["outfits"])

# --- MEVCUT YAPI KORUNDU: GPT Load Balancer ve Client'lar ---
primary_client = OpenAI(api_key=settings.OPENAI_API_KEY)
secondary_client = OpenAI(api_key=settings.OPENAI_API_KEY2)
db = firestore.client()
PLAN_LIMITS = {"free": 2, "premium": None}

class GPTLoadBalancer:
    """GPT API yük dengeleyici - Bu yapı korunmuştur."""
    def __init__(self):
        self.primary_failures = 0
        self.secondary_failures = 0
        self.last_primary_use = 0
        self.last_secondary_use = 0
        self.max_failures = 3
        self.failure_reset_time = 300
    
    def get_available_client(self):
        current_time = time.time()
        if current_time - self.last_primary_use > self.failure_reset_time: self.primary_failures = 0
        if current_time - self.last_secondary_use > self.failure_reset_time: self.secondary_failures = 0
        
        if self.primary_failures < self.max_failures:
            self.last_primary_use = current_time
            return primary_client, "primary"
        elif self.secondary_failures < self.max_failures:
            self.last_secondary_use = current_time
            return secondary_client, "secondary"
        else:
            self.primary_failures = 0
            self.last_primary_use = current_time
            return primary_client, "primary"
    
    def report_failure(self, client_type: str):
        if client_type == "primary": self.primary_failures += 1
        else: self.secondary_failures += 1
    
    def report_success(self, client_type: str):
        if client_type == "primary": self.primary_failures = max(0, self.primary_failures - 1)
        else: self.secondary_failures = max(0, self.secondary_failures - 1)

gpt_balancer = GPTLoadBalancer()


class AdvancedOutfitEngine:
    """
    YENİDEN YAPILANDIRILDI: Kombin mantığı motoru.
    AI prompt'u, tam çeviri yapabilmesi için lokalizasyon verileriyle besler.
    """

    def analyze_wardrobe(self, wardrobe: List[OptimizedClothingItem]) -> Dict[str, Any]:
        """Gardırop hakkında özetleyici istatistikler çıkarır."""
        if not wardrobe:
            return {"total_items": 0, "categories": [], "dominant_colors": [], "styles": []}
        
        categories = sorted(list(set(item.category for item in wardrobe)))
        styles = sorted(list(set(style for item in wardrobe for style in item.style)))
        color_counts = {color: 0 for color in localization.TRANSLATIONS['en']['colors']}
        for item in wardrobe:
            for color in item.colors:
                if color in color_counts:
                    color_counts[color] += 1
        
        dominant_colors = sorted(color_counts, key=color_counts.get, reverse=True)
        return {"total_items": len(wardrobe), "categories": categories, "dominant_colors": dominant_colors, "styles": styles}

    def create_compact_wardrobe_string(self, wardrobe: List[OptimizedClothingItem]) -> str:
        """AI'a gönderilecek gardırop listesini kompakt bir string'e dönüştürür."""
        return "\n".join([f"ID: {item.id} | Name: {item.name} | Category: {item.category} | Colors: {', '.join(item.colors)} | Styles: {', '.join(item.style)}" for item in wardrobe])

    def create_advanced_prompt(self, request: OutfitRequest, gender: str, wardrobe_summary: Dict[str, Any]) -> str:
        """YENİ MANTIK: AI'a tam ve doğru çeviri yapması için gerekli tüm bilgileri verir."""
        lang_code = request.language
        en_occasions = localization.get_translation('en', 'occasions')
        occasion_text = en_occasions.get(request.occasion, request.occasion.replace('-', ' '))

        # Dil'e özel talimat ve kılavuzları hazırla
        target_language, critical_translation_rules = self._get_language_specific_instructions(lang_code)

        pinterest_instructions = ""
        if request.plan == "premium":
            # Pinterest sorgusunu İngilizce isteyip backend'de çevirmek daha güvenilir
            pinterest_instructions = ',"pinterest_links": [{"title": "Creative Title in {target_language}", "search_query": "A logical Pinterest search query in English"}]'

        prompt = f"""
You are an expert fashion stylist. Create a complete {gender} outfit for the occasion: '{occasion_text}'. The weather is {request.weather_condition}.

CRITICAL LANGUAGE REQUIREMENT:
You MUST write all descriptive fields ("description", "suggestion_tip", and "title" for Pinterest) in {target_language}.
{critical_translation_rules}

CONTEXT:
- Wardrobe: You are provided with {wardrobe_summary['total_items']} items. Styles: {', '.join(wardrobe_summary['styles'])}.
- Recent Outfits (Avoid these items): {', '.join([item for outfit in request.last_5_outfits for item in outfit.items][:15]) if request.last_5_outfits else "None"}

REQUIREMENTS:
- Use ONLY the exact item IDs from the database below.
- Keep "description" and "suggestion_tip" concise (1-2 sentences).

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
        """Dil koduna göre dil adını ve çeviri talimatlarını döndürür."""
        if lang_code == 'en':
            return "English", ""

        # Şu an için sadece Türkçe destekleniyor, gelecekte burası genişletilebilir.
        target_language = "Turkish"
        translations = localization.TRANSLATIONS.get(lang_code, localization.TRANSLATIONS['en'])
        
        color_guide_str = json.dumps(translations.get('colors', {}), ensure_ascii=False, indent=2)
        category_guide_str = json.dumps(translations.get('categories', {}), ensure_ascii=False, indent=2)
        occasion_guide_str = json.dumps(translations.get('occasions', {}), ensure_ascii=False, indent=2)

        return target_language, f"""
CRITICAL TRANSLATION RULES:
- When you mention a color, category, or occasion, you MUST use the exact Turkish translation from the guides below.
- Do NOT translate them yourself. Find the English key (e.g., "ice-blue") and use its exact Turkish value (e.g., "Buz Mavisi").

TURKISH COLOR GUIDE:
{color_guide_str}

TURKISH CATEGORY GUIDE:
{category_guide_str}

TURKISH OCCASION GUIDE:
{occasion_guide_str}
"""

    def validate_outfit_structure(self, items_from_ai: List[Dict[str, str]], wardrobe: List[OptimizedClothingItem]) -> List[Dict[str, str]]:
        """AI'dan gelen item listesinin yapısını ve ID'lerin geçerliliğini kontrol eder."""
        if not items_from_ai or not isinstance(items_from_ai, list): return []
        
        wardrobe_map = {item.id: item for item in wardrobe}
        validated_items = []
        for item in items_from_ai:
            if isinstance(item, dict) and all(k in item for k in ["id", "name", "category"]):
                if item["id"] in wardrobe_map:
                    original_item = wardrobe_map[item["id"]]
                    validated_items.append({
                        "id": original_item.id,
                        "name": item["name"],  # AI'ın yarattığı yaratıcı ismi (artık doğru dilde) kullan
                        "category": original_item.category
                    })
        return validated_items

    def translate_pinterest_query(self, query: str, lang_code: str) -> str:
        """Sadece Pinterest sorgusunu İngilizce'den hedef dile çevirir."""
        if lang_code == 'en' or not query: return query

        translations = localization.TRANSLATIONS.get(lang_code, localization.TRANSLATIONS['en'])
        all_keywords = {**translations.get('colors', {}), **translations.get('categories', {})}
        sorted_keywords = sorted(all_keywords.keys(), key=len, reverse=True)

        for key in sorted_keywords:
            query = query.replace(key, all_keywords[key])
        return query


outfit_engine = AdvancedOutfitEngine()

async def check_usage_and_get_user_data(user_id: str = Depends(get_current_user_id)):
    """Kullanım kontrolü ve kullanıcı verisi. Bu yapı korunmuştur."""
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

async def call_gpt_with_retry(prompt: str, plan: str, max_retries: int = 2) -> str:
    """GPT API'yi retry logic ile çağırır. Bu yapı korunmuştur."""
    config = {"free": {"max_tokens": 800, "temperature": 0.7}, "premium": {"max_tokens": 1200, "temperature": 0.8}}
    gpt_config = config.get(plan, config["free"])
    
    for attempt in range(max_retries + 1):
        client, client_type = gpt_balancer.get_available_client()
        try:
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
            if not response_content: raise ValueError("Empty response from GPT")
            json.loads(response_content)
            
            gpt_balancer.report_success(client_type)
            print(f"✅ GPT response received from {client_type} client (attempt {attempt + 1})")
            return response_content
            
        except Exception as e:
            print(f"❌ GPT API error on attempt {attempt + 1} with {client_type}: {str(e)}")
            gpt_balancer.report_failure(client_type)
            if attempt < max_retries:
                await asyncio.sleep(1)
            else:
                raise e

@router.post("/suggest-outfit", response_model=OutfitResponse)
async def suggest_outfit(request: OutfitRequest, user_info: dict = Depends(check_usage_and_get_user_data)):
    """
    YENİ MİMARİ: Gelişmiş kombin öneri endpoint'i.
    Client'tan gelen filtrelenmiş gardırobu kullanır, AI'a çeviri için kılavuz sağlar.
    """
    try:
        user_id, plan, gender = user_info["user_id"], user_info["plan"], user_info["gender"]
        
        if not request.wardrobe:
            raise HTTPException(status_code=400, detail="Wardrobe cannot be empty. Please filter on the client-side first.")
        
        wardrobe_summary = outfit_engine.analyze_wardrobe(request.wardrobe)
        prompt = outfit_engine.create_advanced_prompt(request, gender, wardrobe_summary)
        
        response_content = await call_gpt_with_retry(prompt, plan)
        ai_response = json.loads(response_content)
        
        final_items = outfit_engine.validate_outfit_structure(ai_response.get("items", []), request.wardrobe)
        if not final_items:
            raise HTTPException(status_code=500, detail="AI failed to create a valid outfit with items from the provided wardrobe.")
        
        response_data = {
            "items": final_items,
            "description": ai_response.get("description", ""),
            "suggestion_tip": ai_response.get("suggestion_tip", ""),
            "pinterest_links": []
        }
        
        if plan == "premium" and "pinterest_links" in ai_response:
            final_pinterest_links = []
            for link_idea in ai_response.get("pinterest_links", []):
                if "search_query" in link_idea and link_idea["search_query"]:
                    # Önce İngilizce sorguyu çevir
                    translated_query = outfit_engine.translate_pinterest_query(link_idea["search_query"], request.language)
                    # Sonra URL oluştur
                    encoded_query = quote(translated_query)
                    final_pinterest_links.append({
                        "title": link_idea.get("title", "Inspiration"), # Başlık zaten doğru dilde geldi
                        "url": f"https://www.pinterest.com/search/pins/?q={encoded_query}"
                    })
            response_data["pinterest_links"] = final_pinterest_links

        db.collection('users').document(user_id).update({'usage.count': firestore.Increment(1)})
        
        print(f"✅ Outfit suggestion created and provided in '{request.language}' for {plan} user")
        return OutfitResponse(**response_data)
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="Failed to parse the response from the AI service.")
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Outfit suggestion error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"An internal server error occurred: {str(e)}")


@router.get("/usage-status")
async def get_usage_status(user_id: str = Depends(get_current_user_id)):
    """Kullanım durumu"""
    try:
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        if not user_doc.exists: raise HTTPException(status_code=404, detail="User not found")
        
        user_data = user_doc.to_dict()
        plan = user_data.get("plan", "free")
        usage_data = user_data.get("usage", {})
        today = str(date.today())
        
        current_usage = usage_data.get("count", 0) if usage_data.get("date") == today else 0
        rewarded_count = usage_data.get("rewarded_count", 0) if usage_data.get("date") == today else 0
        daily_limit = PLAN_LIMITS.get(plan)
        
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

@router.get("/gpt-status")
async def get_gpt_status(user_id: str = Depends(get_current_user_id)):
    """GPT API durumları"""
    return {
        "primary_failures": gpt_balancer.primary_failures,
        "secondary_failures": gpt_balancer.secondary_failures,
        "max_failures": gpt_balancer.max_failures,
        "status": "healthy" if (gpt_balancer.primary_failures < gpt_balancer.max_failures or 
                                 gpt_balancer.secondary_failures < gpt_balancer.max_failures) else "degraded"
    }