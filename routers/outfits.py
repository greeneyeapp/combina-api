# routers/outfits.py

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
from schemas import OutfitRequest, OutfitResponse, OptimizedClothingItem, SuggestedItem, PinterestLink
from core import localization

router = APIRouter(prefix="/api", tags=["outfits"])

# --- MEVCUT YAPI KORUNDU: GPT Load Balancer ve Client'lar ---
primary_client = OpenAI(api_key=settings.OPENAI_API_KEY)
secondary_client = OpenAI(api_key=settings.OPENAI_API_KEY2)
db = firestore.client()
PLAN_LIMITS = {"free": 2, "premium": None}

OCCASION_REQUIREMENTS_FEMALE = {
    # === AKTİF & SPOR ===
    # Bu etkinlikler için herhangi bir spor giysisi yeterlidir (VEYA mantığı)
    "gym": {"sportswear": {"leggings", "track-bottom", "athletic-shorts", "sports-bra", "track-top", "sweatshirt", "hoodie", "t-shirt", "sneakers", "casual-sport-shoes"}},
    "yoga-pilates": {"sportswear": {"leggings", "track-bottom", "bralette", "tank-top", "t-shirt"}},
    "outdoor-sports": {"sportswear": {"track-bottom", "athletic-shorts", "leggings", "track-top", "sweatshirt", "hoodie", "raincoat", "sneakers", "boots"}},
    "hiking": {"bottom": {"track-bottom", "leggings"}, "shoes": {"boots", "sneakers"}, "outerwear": {"raincoat", "puffer-coat"}},

    # === İŞ & PROFESYONEL ===
    # Bu etkinlikler için ayrı gruplardan parçalar zorunludur (VE mantığı)
    "office-day": {"top": {"blouse", "shirt"}, "bottom": {"trousers", "skirt", "dress-pants"}, "shoes": {"classic-shoes", "loafers", "heels"}},
    "business-meeting": {"top": {"blazer", "shirt", "blouse"}, "bottom": {"trousers", "skirt", "dress-pants"}, "shoes": {"classic-shoes", "heels"}},
    "business-lunch": {"top": {"blouse", "shirt", "blazer"}, "bottom": {"trousers", "skirt", "linen-trousers"}, "shoes": {"classic-shoes", "heels", "sandals"}},
    
    # === KUTLAMA & RESMİ ===
    # 'one-piece' veya standart 'top'+'bottom' kombinasyonu olabilir
    "wedding": {"one-piece": {"evening-dress", "jumpsuit"}, "shoes": {"heels", "classic-shoes"}},
    "special-event": {"one-piece": {"evening-dress", "jumpsuit"}, "shoes": {"heels"}},
    "celebration": {"one-piece": {"evening-dress", "casual-dress", "jumpsuit"}, "shoes": {"heels"}},
    "formal-dinner": {"one-piece": {"evening-dress", "jumpsuit"}, "top": {"blouse", "blazer"}, "bottom": {"trousers"}, "shoes": {"heels"}},

    # === GÜNLÜK & SOSYAL ===
    "daily-errands": {"top": {"t-shirt", "sweatshirt"}, "bottom": {"jeans", "leggings"}, "shoes": {"sneakers"}},
    "shopping": {"top": {"t-shirt", "blouse"}, "bottom": {"jeans", "skirt"}, "shoes": {"sneakers", "sandals"}},
    "house-party": {"top": {"blouse", "t-shirt", "crop-top"}, "bottom": {"jeans", "skirt"}, "shoes": {"sneakers", "boots"}},
    "date-night": {"one-piece": {"casual-dress", "evening-dress"}, "top": {"blouse", "shirt"}, "bottom": {"jeans", "skirt"}, "shoes": {"heels", "boots"}},
    "brunch": {"one-piece": {"casual-dress"}, "top": {"blouse", "t-shirt"}, "bottom": {"jeans", "skirt"}, "shoes": {"sandals", "sneakers"}},
    "friends-gathering": {"top": {"t-shirt", "sweatshirt"}, "bottom": {"jeans"}, "shoes": {"sneakers"}},
    "cinema": {"top": {"hoodie", "t-shirt"}, "bottom": {"jeans", "track-bottom"}, "shoes": {"sneakers"}},
    "concert": {"top": {"t-shirt", "crop-top"}, "bottom": {"jeans", "denim-shorts"}, "outerwear": {"denim-jacket", "leather-jacket"}, "shoes": {"boots", "sneakers"}},
    "cafe": {"top": {"cardigan", "blouse", "t-shirt"}, "bottom": {"jeans", "skirt"}, "shoes": {"sneakers", "loafers"}},
    
    # === SEYAHAT & ÖZEL ===
    "travel": {"top": {"t-shirt", "sweatshirt"}, "bottom": {"jeans", "track-bottom"}, "shoes": {"sneakers"}},
    "weekend-getaway": {"top": {"t-shirt", "cardigan"}, "bottom": {"jeans"}, "shoes": {"sneakers"}},
    "holiday": {"top": {"tank-top", "t-shirt"}, "bottom": {"fabric-shorts", "skirt"}, "shoes": {"sandals"}},
    "festival": {"top": {"crop-top", "t-shirt", "tank-top"}, "bottom": {"denim-shorts"}, "shoes": {"boots"}},
    "sightseeing": {"top": {"t-shirt"}, "bottom": {"jeans", "fabric-shorts"}, "shoes": {"sneakers"}}
}

OCCASION_REQUIREMENTS_MALE = {
    # === AKTİF & SPOR ===
    "gym": {"sportswear": {"track-bottom", "athletic-shorts", "track-top", "sweatshirt", "hoodie", "t-shirt", "sneakers", "casual-sport-shoes"}},
    "yoga-pilates": {"sportswear": {"track-bottom", "athletic-shorts", "t-shirt", "tank-top"}},
    "outdoor-sports": {"sportswear": {"track-bottom", "athletic-shorts", "track-top", "sweatshirt", "hoodie", "raincoat", "sneakers", "boots"}},
    "hiking": {"bottom": {"track-bottom"}, "shoes": {"boots", "sneakers"}, "outerwear": {"raincoat", "puffer-coat"}},

    # === İŞ & PROFESYONEL ===
    "office-day": {"top": {"shirt", "polo-shirt"}, "bottom": {"trousers", "dress-pants"}, "shoes": {"classic-shoes", "loafers"}},
    "business-meeting": {"top": {"shirt"}, "bottom": {"suit-trousers", "dress-pants"}, "outerwear": {"suit-jacket", "blazer"}, "shoes": {"classic-shoes"}},
    "business-lunch": {"top": {"shirt", "polo-shirt"}, "bottom": {"trousers", "linen-trousers"}, "shoes": {"classic-shoes", "loafers"}},
    
    # === KUTLAMA & RESMİ ===
    "wedding": {"top": {"shirt"}, "bottom": {"suit-trousers"}, "outerwear": {"suit-jacket", "tuxedo"}, "shoes": {"classic-shoes"}},
    "special-event": {"top": {"shirt"}, "bottom": {"suit-trousers"}, "outerwear": {"suit-jacket", "tuxedo"}, "shoes": {"classic-shoes"}},
    "celebration": {"top": {"shirt"}, "bottom": {"trousers", "jeans"}, "outerwear": {"blazer"}, "shoes": {"classic-shoes", "boots"}},
    "formal-dinner": {"top": {"shirt"}, "bottom": {"suit-trousers"}, "outerwear": {"suit-jacket", "tuxedo"}, "shoes": {"classic-shoes"}},

    # === GÜNLÜK & SOSYAL ===
    "daily-errands": {"top": {"t-shirt", "sweatshirt"}, "bottom": {"jeans", "track-bottom"}, "shoes": {"sneakers"}},
    "shopping": {"top": {"t-shirt", "polo-shirt"}, "bottom": {"jeans"}, "shoes": {"sneakers"}},
    "house-party": {"top": {"shirt", "t-shirt", "polo-shirt"}, "bottom": {"jeans"}, "shoes": {"sneakers"}},
    "date-night": {"top": {"shirt", "t-shirt"}, "bottom": {"jeans", "trousers"}, "outerwear": {"blazer"}, "shoes": {"classic-shoes", "boots"}},
    "brunch": {"top": {"shirt", "polo-shirt", "t-shirt"}, "bottom": {"jeans", "fabric-shorts"}, "shoes": {"sandals", "sneakers"}},
    "friends-gathering": {"top": {"t-shirt", "sweatshirt", "hoodie"}, "bottom": {"jeans"}, "shoes": {"sneakers"}},
    "cinema": {"top": {"hoodie", "t-shirt"}, "bottom": {"jeans", "track-bottom"}, "shoes": {"sneakers"}},
    "concert": {"top": {"t-shirt"}, "bottom": {"jeans"}, "outerwear": {"denim-jacket", "leather-jacket"}, "shoes": {"boots"}},
    "cafe": {"top": {"shirt", "cardigan", "t-shirt"}, "bottom": {"jeans"}, "shoes": {"sneakers", "loafers"}},
    
    # === SEYAHAT & ÖZEL ===
    "travel": {"top": {"t-shirt", "sweatshirt"}, "bottom": {"jeans", "track-bottom"}, "shoes": {"sneakers"}},
    "weekend-getaway": {"top": {"t-shirt", "polo-shirt"}, "bottom": {"jeans"}, "shoes": {"sneakers"}},
    "holiday": {"top": {"t-shirt", "polo-shirt", "tank-top"}, "bottom": {"fabric-shorts"}, "shoes": {"sandals"}},
    "festival": {"top": {"t-shirt", "tank-top"}, "bottom": {"denim-shorts"}, "shoes": {"boots"}},
    "sightseeing": {"top": {"t-shirt"}, "bottom": {"jeans", "fabric-shorts"}, "shoes": {"sneakers"}}
}
# --- HARİTALARIN SONU ---

class GPTLoadBalancer:
    def __init__(self): self.primary_failures, self.secondary_failures, self.last_primary_use, self.last_secondary_use, self.max_failures, self.failure_reset_time = 0, 0, 0, 0, 3, 300
    def get_available_client(self):
        current_time = time.time();
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
    """NİHAİ YAPI: AI için verimli prompt oluşturur ve gelen yanıtı backend'de işler."""
    
    def check_wardrobe_compatibility(self, occasion: str, wardrobe: List[OptimizedClothingItem], gender: str):
        """
        NİHAİ VERSİYON: Gardırobun, etkinlik için gerekli KATEGORİ GRUPLARINA sahip olup olmadığını kontrol eder.
        """
        requirements_map = OCCASION_REQUIREMENTS_MALE if gender == 'male' else OCCASION_REQUIREMENTS_FEMALE
        
        if occasion not in requirements_map:
            return # Bu etkinlik için bir kural yoksa geç

        required_groups = requirements_map[occasion]
        wardrobe_categories = {item.category for item in wardrobe}
        
        # Eğer 'one-piece' kuralı varsa, onu öncelikli kontrol et
        if 'one-piece' in required_groups:
            # Hem 'one-piece' hem de gerekli 'shoes' var mı?
            has_one_piece = bool(wardrobe_categories.intersection(required_groups['one-piece']))
            has_shoes = bool(wardrobe_categories.intersection(required_groups.get('shoes', set())))
            # Eğer geçerli bir 'one-piece' kombinasyonu varsa, kontrolden geç
            if has_one_piece and has_shoes:
                return

        # Standart grup kontrolü: Gerekli her gruptan en az bir parça var mı?
        all_groups_satisfied = True
        all_missing_categories = set()

        for group, categories_in_group in required_groups.items():
            # 'one-piece' zaten kontrol edildi, atla.
            if group == 'one-piece': continue

            # Gardıropta bu gruptan bir ürün var mı?
            if not wardrobe_categories.intersection(categories_in_group):
                all_groups_satisfied = False
                # Eksik olan tüm kategorileri biriktir
                all_missing_categories.update(categories_in_group)

        # Eğer tüm gruplar (top, bottom, shoes vb.) karşılanıyorsa, kontrolden geç
        if all_groups_satisfied:
            return

        # Eğer buraya ulaştıysak, gardırop yetersizdir. Hata fırlat.
        if all_missing_categories:
            missing_types = ", ".join(sorted(list(all_missing_categories)))
            error_detail = (
                f"Your wardrobe is not suitable for '{occasion}'. "
                f"Please add items like: {missing_types}."
            )
            raise HTTPException(status_code=422, detail=error_detail)
        """
        Verilen etkinlik ve CİNSİYET için gardırobun uygun olup olmadığını kontrol eder.
        'unisex' durumunda erkek ve kadın kurallarını dinamik olarak birleştirir.
        """
        required_categories = set()

        # Adım 1: Cinsiyete göre doğru kural setini belirle
        if gender == 'male':
            # Sadece erkek kurallarını kullan
            requirements_map = OCCASION_REQUIREMENTS_MALE
            if occasion in requirements_map:
                required_categories = requirements_map[occasion]

        elif gender == 'female':
            # Sadece kadın kurallarını kullan
            requirements_map = OCCASION_REQUIREMENTS_FEMALE
            if occasion in requirements_map:
                required_categories = requirements_map[occasion]
        
        else:  # Bu blok 'unisex' ve tanımsız diğer tüm durumları yakalar
            # Hem erkek hem de kadın listesinden kuralları güvenli bir şekilde al
            male_reqs = OCCASION_REQUIREMENTS_MALE.get(occasion, set())
            female_reqs = OCCASION_REQUIREMENTS_FEMALE.get(occasion, set())
            
            # İki kural setini birleştir (Python'da set'ler için birleşim operatörü '|')
            required_categories = male_reqs | female_reqs

        # Adım 2: Kontrolü yap
        # Eğer bu etkinlik için hiçbir kural tanımlanmamışsa, kontrolden geç
        if not required_categories:
            return

        wardrobe_categories = {item.category for item in wardrobe}

        if not wardrobe_categories.intersection(required_categories):
            # Hata mesajının her zaman aynı sırada olması için sıralama ekledim (testler için iyi)
            missing_types = ", ".join(sorted(list(required_categories)))
            
            error_detail = (
                f"Your wardrobe does not have suitable items for '{occasion}'. "
                f"Please add items like: {missing_types}."
            )
            raise HTTPException(status_code=422, detail=error_detail)

    def create_compact_wardrobe_string(self, wardrobe: List[OptimizedClothingItem]) -> str:
        return "\n".join([f"ID: {item.id} | Name: {item.name} | Category: {item.category} | Colors: {', '.join(item.colors)} | Styles: {', '.join(item.style)}" for item in wardrobe])

    def create_advanced_prompt(self, request: OutfitRequest) -> str:
        """NİHAİ PROMPT: Token açısından verimli, 3'lü Pinterest linki talimatı içeren prompt."""
        lang_code, gender = request.language, request.gender
        target_language = localization.LANGUAGE_NAMES.get(lang_code, "English")
        en_occasions = localization.get_translation('en', 'occasions')
        occasion_text = en_occasions.get(request.occasion, request.occasion.replace('-', ' '))

        pinterest_instructions = ""
        if request.plan == "premium":
            # GÜNCELLENDİ: 3 farklı ve akıllı Pinterest linki için talimatlar
            pinterest_instructions = f''',"pinterest_links": [
            {{
                "title": "A specific title in {target_language} about the exact outfit combo",
                "search_query": "A search query in English for the exact outfit. MUST include gender '{gender}', main item categories, and colors. Example: '{gender} blue t-shirt white linen trousers outfit'"
            }},
            {{
                "title": "A title in {target_language} on how to style ONE KEY ITEM",
                "search_query": "A search query in English on how to style ONE KEY ITEM from the outfit (e.g., the trousers, a jacket). MUST include gender '{gender}'. Example: 'how to style white linen trousers for {gender}'"
            }},
            {{
                "title": "A general style inspiration title in {target_language} for the occasion",
                "search_query": "A general style search query in English for the occasion and season. MUST include gender '{gender}'. Example: '{gender} summer daily errands style'"
            }}
        ]'''

        prompt = f"""
You are an expert fashion stylist. Create a complete {gender} outfit for the occasion: '{occasion_text}'. The weather is {request.weather_condition}.

CRITICAL LANGUAGE REQUIREMENT:
- You MUST write all descriptive fields ("description", "suggestion_tip", and "title" for Pinterest) in {target_language}.
- Do NOT use English if the target language is different.

CONTEXT:
- Wardrobe: You are provided with {request.context.filtered_wardrobe_size} pre-filtered items.
- Recent Outfits (Avoid these item IDs): {', '.join([item for outfit in request.last_5_outfits for item in outfit.items][:15]) if request.last_5_outfits else "None"}

CRITICAL FASHION LOGIC:
- A complete outfit must consist of either (1) a top piece AND a bottom piece, OR (2) a one-piece item like a dress or jumpsuit.
- **DO NOT combine a top (like a t-shirt, blouse, shirt) with a dress.** A dress is a standalone main item.
- Only combine outerwear (like jackets, cardigans) with a complete outfit (top+bottom or a dress).
- Ensure the styles of the selected items are cohesive and logical for the occasion.
- Avoid selecting multiple items from the same core category (e.g., do not choose two different tops or two different trousers for one outfit).

REQUIREMENTS:
- Use ONLY the exact item IDs from the database below.
- Keep "description" and "suggestion_tip" concise (1-2 sentences).
- For premium users, provide exactly THREE different Pinterest link ideas as specified.

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

    def validate_outfit_structure(self, items_from_ai: List[Dict[str, str]], wardrobe: List[OptimizedClothingItem]) -> List[SuggestedItem]:
        if not items_from_ai or not isinstance(items_from_ai, list): return []
        wardrobe_map = {item.id: item for item in wardrobe}
        return [SuggestedItem(**item) for item in items_from_ai if isinstance(item, dict) and item.get("id") in wardrobe_map]

    def standardize_terminology(self, text: str, lang_code: str) -> str:
        # Bu fonksiyon, AI'dan gelen dildeki genel terimleri (örn: "açık mavi")
        # bizim standartlarımıza (örn: "Buz Mavisi") çevirmek için kullanılabilir.
        # Şimdilik, AI'ın doğrudan doğru dili kullandığını varsayıyoruz.
        return text

    def translate_pinterest_query(self, query: str, lang_code: str) -> str:
        if lang_code == 'en' or not query: return query
        translations = localization.TRANSLATIONS.get(lang_code, localization.TRANSLATIONS['en'])
        all_keywords = {**translations.get('colors', {}), **translations.get('categories', {})}
        sorted_keywords = sorted(all_keywords.keys(), key=len, reverse=True)
        for key in sorted_keywords:
            query = query.replace(key, all_keywords[key])
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
    config = {"free": {"max_tokens": 800, "temperature": 0.75}, "premium": {"max_tokens": 1200, "temperature": 0.75}}
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
        outfit_engine.check_wardrobe_compatibility(request.occasion, request.wardrobe, request.gender)

        if not request.wardrobe: 
            raise HTTPException(status_code=400, detail="Wardrobe cannot be empty.")
        
        prompt = outfit_engine.create_advanced_prompt(request)
        response_content = await call_gpt_with_retry(prompt, user_info["plan"])
        ai_response = json.loads(response_content)
        
        final_items = outfit_engine.validate_outfit_structure(ai_response.get("items", []), request.wardrobe)
        if not final_items: 
            raise HTTPException(status_code=500, detail="AI failed to create a valid outfit.")
        
        description = outfit_engine.standardize_terminology(ai_response.get("description", ""), request.language)
        suggestion_tip = outfit_engine.standardize_terminology(ai_response.get("suggestion_tip", ""), request.language)
        
        response_data = {"items": final_items, "description": description, "suggestion_tip": suggestion_tip, "pinterest_links": []}
        
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