from fastapi import APIRouter, Depends, HTTPException
from openai import OpenAI
import json
from datetime import date
from firebase_admin import firestore
from typing import List, Dict, Set, Optional
from collections import defaultdict
import random
import traceback
import asyncio
import time

from core.config import settings
from core.security import get_current_user_id
from schemas import OutfitRequest, OutfitResponse, ClothingItem

router = APIRouter(prefix="/api", tags=["outfits"])

# Dual GPT Client Setup
primary_client = OpenAI(api_key=settings.OPENAI_API_KEY)
secondary_client = OpenAI(api_key=settings.OPENAI_API_KEY2)

db = firestore.client()
PLAN_LIMITS = {"free": 2, "premium": float('inf')}

class GPTLoadBalancer:
    """GPT API yük dengeleyici - trafik ve hata durumlarına göre client seçer"""
    
    def __init__(self):
        self.primary_failures = 0
        self.secondary_failures = 0
        self.last_primary_use = 0
        self.last_secondary_use = 0
        self.max_failures = 3
        self.failure_reset_time = 300  # 5 dakika
    
    def get_available_client(self):
        """En uygun GPT client'ını seçer"""
        current_time = time.time()
        
        # Hata sayılarını sıfırla (5 dakika geçtiyse)
        if current_time - self.last_primary_use > self.failure_reset_time:
            self.primary_failures = 0
        if current_time - self.last_secondary_use > self.failure_reset_time:
            self.secondary_failures = 0
        
        # Primary'yi tercih et, ama çok fazla hata varsa secondary'yi kullan
        if self.primary_failures < self.max_failures:
            self.last_primary_use = current_time
            return primary_client, "primary"
        elif self.secondary_failures < self.max_failures:
            self.last_secondary_use = current_time
            return secondary_client, "secondary"
        else:
            # Her ikisi de problemliyse, primary'yi tekrar dene
            self.primary_failures = 0
            self.last_primary_use = current_time
            return primary_client, "primary"
    
    def report_failure(self, client_type: str):
        """API hatasını raporla"""
        if client_type == "primary":
            self.primary_failures += 1
        else:
            self.secondary_failures += 1
    
    def report_success(self, client_type: str):
        """Başarılı kullanımı raporla"""
        if client_type == "primary":
            self.primary_failures = max(0, self.primary_failures - 1)
        else:
            self.secondary_failures = max(0, self.secondary_failures - 1)

gpt_balancer = GPTLoadBalancer()

class AdvancedOutfitEngine:
    """Gelişmiş kombin öneri motoru - Akıllı filtreleme ve stil analizi"""
    
    def __init__(self):
        self.category_hierarchy = {
            'essential': ['t-shirt', 'shirt', 'jeans', 'trousers', 'sneakers', 'boots'],
            'tops': ['t-shirt', 'shirt', 'blouse', 'top', 'bodysuit', 'crop-top', 'tank-top', 
                    'sweater', 'cardigan', 'hoodie', 'sweatshirt', 'pullover'],
            'bottoms': ['jeans', 'trousers', 'leggings', 'joggers', 'skirt', 'shorts', 
                       'culottes', 'chino-trousers'],
            'dresses': ['dress', 'jumpsuit', 'romper'],
            'outerwear': ['coat', 'jacket', 'blazer', 'cardigan', 'vest'],
            'footwear': ['sneakers', 'heels', 'boots', 'sandals', 'flats', 'loafers'],
            'accessories': ['bag', 'jewelry', 'scarf', 'hat', 'belt', 'watch']
        }
        
        self.weather_priorities = {
            'hot': {
                'preferred': ['tank-top', 'shorts', 'dress', 'sandals', 'light'],
                'avoid': ['coat', 'jacket', 'boots', 'sweater', 'long']
            },
            'warm': {
                'preferred': ['t-shirt', 'shirt', 'jeans', 'sneakers', 'light'],
                'avoid': ['coat', 'heavy', 'wool']
            },
            'cool': {
                'preferred': ['sweater', 'jacket', 'jeans', 'boots'],
                'avoid': ['shorts', 'tank', 'sandals']
            },
            'cold': {
                'preferred': ['coat', 'sweater', 'boots', 'warm', 'wool'],
                'avoid': ['shorts', 'tank', 'sandals', 'crop']
            }
        }
        
        self.occasion_styles = {
            'business': ['formal', 'business', 'classic'],
            'casual': ['casual', 'comfortable'],
            'party': ['party', 'elegant', 'stylish'],
            'sport': ['sportswear', 'athletic', 'casual'],
            'formal': ['formal', 'elegant', 'business']
        }
    
    def get_category_type(self, category: str) -> str:
        """Kategoriyi ana gruba atar"""
        category_lower = category.lower()
        for group, categories in self.category_hierarchy.items():
            if category_lower in categories:
                return group
        return 'other'
    
    def calculate_item_score(self, item: ClothingItem, context: dict) -> float:
        """Her item için kapsamlı skor hesaplar"""
        score = 1.0
        
        # Mevsim uygunluğu
        weather_score = self.calculate_weather_compatibility(item, context['weather'])
        
        # Stil uygunluğu
        style_score = self.calculate_style_compatibility(item, context['occasion'])
        
        # Kullanım sıklığı (daha az kullanılanlar tercih edilir)
        freshness_score = self.calculate_freshness_score(item, context['recent_items'])
        
        # Temel önem skoru (essential item'lar öncelikli)
        importance_score = self.calculate_importance_score(item)
        
        final_score = (weather_score * 0.3 + style_score * 0.3 + 
                      freshness_score * 0.2 + importance_score * 0.2)
        
        return min(final_score, 5.0)
    
    def calculate_weather_compatibility(self, item: ClothingItem, weather: str) -> float:
        """Hava durumu uygunluğu"""
        if weather not in self.weather_priorities:
            return 2.5
        
        weather_rules = self.weather_priorities[weather]
        item_name_lower = item.name.lower()
        item_category_lower = item.category.lower()
        
        score = 2.5  # Base score
        
        # Tercih edilen kelimelerle eşleşme
        for preferred in weather_rules['preferred']:
            if preferred in item_name_lower or preferred in item_category_lower:
                score += 0.5
        
        # Kaçınılması gereken kelimelerle eşleşme
        for avoid in weather_rules['avoid']:
            if avoid in item_name_lower or avoid in item_category_lower:
                score -= 0.8
        
        return max(0.5, min(5.0, score))
    
    def calculate_style_compatibility(self, item: ClothingItem, occasion: str) -> float:
        """Stil uygunluğu"""
        item_styles = []
        if isinstance(item.style, str):
            item_styles = [s.strip() for s in item.style.split(',')]
        elif isinstance(item.style, list):
            item_styles = item.style
        
        if not item_styles:
            return 2.5
        
        # Durum için uygun stilleri bul
        suitable_styles = []
        for occ_type, styles in self.occasion_styles.items():
            if occ_type in occasion.lower():
                suitable_styles.extend(styles)
        
        if not suitable_styles:
            return 2.5
        
        # Eşleşme skorunu hesapla
        matches = sum(1 for style in item_styles if any(s in style.lower() for s in suitable_styles))
        total_styles = len(item_styles)
        
        if total_styles == 0:
            return 2.5
        
        match_ratio = matches / total_styles
        return 1.0 + (match_ratio * 3.0)  # 1.0-4.0 arası
    
    def calculate_freshness_score(self, item: ClothingItem, recent_items: Set[str]) -> float:
        """Son kullanım taze puanı"""
        if item.id in recent_items:
            return 1.0  # Yakın zamanda kullanılmış
        return 3.0  # Taze
    
    def calculate_importance_score(self, item: ClothingItem) -> float:
        """Temel önem skoru"""
        if item.category.lower() in self.category_hierarchy['essential']:
            return 3.0
        return 2.0
    
    def smart_wardrobe_selection(self, wardrobe: List[ClothingItem], context: dict, limit: int) -> List[ClothingItem]:
        """Akıllı gardrop seçimi"""
        # Her item için skor hesapla - isImageMissing field'ını kontrol et
        scored_items = []
        for item in wardrobe:
            # isImageMissing field'ı varsa kontrol et, yoksa True kabul et
            has_image = not getattr(item, 'isImageMissing', False)
            if has_image:  # Sadece resmi olan item'ları al
                score = self.calculate_item_score(item, context)
                scored_items.append((item, score))
        
        # Skor ve çeşitlilik dengesini koru
        return self.balanced_selection(scored_items, limit)
    
    def balanced_selection(self, scored_items: List[tuple], limit: int) -> List[ClothingItem]:
        """Dengeli seçim algoritması"""
        sorted_items = sorted(scored_items, key=lambda x: x[1], reverse=True)
        
        selected = []
        category_counts = defaultdict(int)
        max_per_category = max(3, limit // 8)  # Kategori başına maksimum
        
        for item, score in sorted_items:
            if len(selected) >= limit:
                break
            
            category_type = self.get_category_type(item.category)
            
            # Kategori çeşitliliğini koru
            if category_counts[category_type] >= max_per_category:
                continue
            
            selected.append(item)
            category_counts[category_type] += 1
        
        return selected
    
    def create_advanced_prompt(self, request: OutfitRequest, gender: str, wardrobe_summary: dict) -> str:
        """Gelişmiş AI prompt oluştur"""
        
        # Plan bazlı Pinterest kontrolü
        pinterest_section = ""
        if request.plan == 'premium':
            pinterest_section = ',"pinterest_links":[{"title":"Style inspiration title","url":"https://pinterest.com/..."}]'
        
        # Dil mapping sistemi
        language_names = {
            'ar': 'العربية (Arabic)',
            'bg': 'Български (Bulgarian)', 
            'de': 'Deutsch (German)',
            'el': 'Ελληνικά (Greek)',
            'en': 'English',
            'es': 'Español (Spanish)',
            'fr': 'Français (French)',
            'he': 'עברית (Hebrew)',
            'hi': 'हिन्दी (Hindi)',
            'it': 'Italiano (Italian)',
            'ja': '日本語 (Japanese)',
            'ko': '한국어 (Korean)',
            'pt': 'Português (Portuguese)',
            'ru': 'Русский (Russian)',
            'th': 'ไทย (Thai)',
            'tr': 'Türkçe (Turkish)',
            'zh': '中文 (Chinese)'
        }
        
        target_language = language_names.get(request.language, 'English')
        
        prompt = f"""You are an expert fashion stylist. Create a complete {gender} outfit for the occasion '{request.occasion}' in {request.weather_condition} weather.

CRITICAL LANGUAGE REQUIREMENT: 
You MUST write the "description" and "suggestion_tip" fields in {target_language} language. 
Do NOT use English if the target language is different.

STYLING OBJECTIVES:
1. Create a coherent, weather-appropriate outfit
2. Ensure pieces complement each other in style and color
3. Balance comfort with style appropriateness
4. Consider the formality level of the occasion

WARDROBE SUMMARY:
- Available categories: {', '.join(wardrobe_summary['categories'])}
- Color palette: {', '.join(wardrobe_summary['dominant_colors'][:8])}
- Style range: {', '.join(wardrobe_summary['styles'])}
- Total pieces: {wardrobe_summary['total_items']}

OUTFIT REQUIREMENTS:
- Include: 1 top + 1 bottom + 1 footwear OR 1 dress + 1 footwear
- Optional: outerwear, accessories (if weather/occasion appropriate)
- Maximum 6 pieces total
- Ensure color harmony and style consistency

RECENT OUTFIT CONTEXT:
Recently used items (try to avoid): {', '.join([item for outfit in request.last_5_outfits for item in outfit.items][:15])}

CRITICAL ID USAGE RULE:
You MUST use EXACT item IDs from the database below. Do NOT modify, shorten, or create new IDs.

ITEM DATABASE:
{self.create_compact_wardrobe_string(request.wardrobe)}

RESPONSE RULES:
1. Use ONLY exact item IDs from the database above (copy-paste the full ID)
2. Create creative names and descriptions for the outfit pieces
3. Use the actual category from the database for each item
4. Write "description" and "suggestion_tip" in {target_language} language ONLY
5. Provide practical styling advice

Response format:
{{
    "items": [{{"id": "exact_item_id_from_database", "name": "creative_description", "category": "actual_category_from_database"}}],
    "description": "Complete outfit description in {target_language} explaining the look and feel",
    "suggestion_tip": "Practical styling advice in {target_language} for wearing this outfit"
    {pinterest_section}
}}

LANGUAGE REMINDER: description = {target_language}, suggestion_tip = {target_language}"""
        
        return prompt
    
    def create_compact_wardrobe_string(self, wardrobe: List[ClothingItem]) -> str:
        """Kompakt gardrop listesi oluştur - ID'leri vurgulu"""
        groups = defaultdict(list)
        for item in wardrobe:
            cat_type = self.get_category_type(item.category)
            colors = item.colors or [item.color] if item.color else ['neutral']
            color_str = ','.join(colors[:2])  # İlk 2 renk
            groups[cat_type].append(f"ID:{item.id}|{item.name}|({color_str})")
        
        return " || ".join([f"{cat}_ITEMS[{' | '.join(items)}]" for cat, items in groups.items()])
    
    def analyze_wardrobe(self, wardrobe: List[ClothingItem]) -> dict:
        """Gardrop analizi"""
        categories = set()
        colors = []
        styles = set()
        
        for item in wardrobe:
            categories.add(self.get_category_type(item.category))
            if item.colors:
                colors.extend(item.colors)
            elif item.color:
                colors.append(item.color)
            
            if isinstance(item.style, list):
                styles.update(item.style)
            elif isinstance(item.style, str):
                styles.update([s.strip() for s in item.style.split(',')])
        
        # En yaygın renkleri bul
        color_counts = defaultdict(int)
        for color in colors:
            if color and not color.startswith('pattern_'):
                color_counts[color] += 1
        
        dominant_colors = sorted(color_counts.items(), key=lambda x: x[1], reverse=True)
        
        return {
            'categories': list(categories),
            'dominant_colors': [color for color, _ in dominant_colors],
            'styles': list(styles),
            'total_items': len(wardrobe)
        }
    
    def validate_outfit_structure(self, suggested_items: List[dict], wardrobe: List[ClothingItem]) -> List[dict]:
        """Kombin yapısını doğrula ve düzelt"""
        wardrobe_map = {item.id: item for item in wardrobe}
        
        valid_items = []
        category_types = set()
        invalid_ids = []
        
        # Önce geçerli item'ları filtrele ve hatalı ID'leri tespit et
        for item_dict in suggested_items:
            item_id = item_dict.get('id')
            if item_id in wardrobe_map:
                wardrobe_item = wardrobe_map[item_id]
                cat_type = self.get_category_type(wardrobe_item.category)
                
                # Aynı kategoriden birden fazla item'ı engelle (accessories hariç)
                if cat_type not in category_types or cat_type == 'accessories':
                    valid_items.append({
                        'id': wardrobe_item.id,
                        'name': wardrobe_item.name,  # Gerçek name kullan
                        'category': wardrobe_item.category  # Gerçek category kullan
                    })
                    category_types.add(cat_type)
            else:
                invalid_ids.append(item_id)
                print(f"⚠️ Invalid ID detected: {item_id}")
        
        # Hatalı ID'ler varsa log'la
        if invalid_ids:
            print(f"❌ GPT used invalid IDs: {invalid_ids}")
            print(f"Available IDs: {list(wardrobe_map.keys())[:10]}...")  # İlk 10 ID'yi göster
        
        # Temel kombin kontrolü
        has_dress = 'dresses' in category_types
        has_top = 'tops' in category_types
        has_bottom = 'bottoms' in category_types
        has_footwear = 'footwear' in category_types
        
        # Eksik parçaları tamamla
        if not has_footwear:
            print("🔍 Looking for footwear...")
            shoe = self.find_suitable_item(wardrobe, 'footwear', exclude_ids={item['id'] for item in valid_items})
            if shoe:
                valid_items.append({'id': shoe.id, 'name': shoe.name, 'category': shoe.category})
                print(f"✅ Added footwear: {shoe.name}")
            else:
                print("⚠️ No suitable footwear found")
        
        if not has_dress and (not has_top or not has_bottom):
            if not has_top:
                print("🔍 Looking for top...")
                top = self.find_suitable_item(wardrobe, 'tops', exclude_ids={item['id'] for item in valid_items})
                if top:
                    valid_items.append({'id': top.id, 'name': top.name, 'category': top.category})
                    print(f"✅ Added top: {top.name}")
            
            if not has_bottom:
                print("🔍 Looking for bottom...")
                bottom = self.find_suitable_item(wardrobe, 'bottoms', exclude_ids={item['id'] for item in valid_items})
                if bottom:
                    valid_items.append({'id': bottom.id, 'name': bottom.name, 'category': bottom.category})
                    print(f"✅ Added bottom: {bottom.name}")
        
        print(f"🎯 Final outfit: {len(valid_items)} items with categories: {[self.get_category_type(item['category']) for item in valid_items]}")
        return valid_items[:6]  # Maksimum 6 parça
    
    def find_suitable_item(self, wardrobe: List[ClothingItem], target_category: str, exclude_ids: Set[str]) -> Optional[ClothingItem]:
        """Uygun item bul"""
        candidates = [
            item for item in wardrobe 
            if (self.get_category_type(item.category) == target_category and 
                item.id not in exclude_ids and 
                not getattr(item, 'isImageMissing', False))  # Safe attribute access
        ]
        return random.choice(candidates) if candidates else None

outfit_engine = AdvancedOutfitEngine()

async def check_usage_and_get_user_data(user_id: str = Depends(get_current_user_id)):
    """Kullanım kontrolü ve kullanıcı verisi"""
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
    """GPT API'yi retry logic ile çağır"""
    
    config = {
        "free": {"max_tokens": 600, "temperature": 0.7},
        "premium": {"max_tokens": 1000, "temperature": 0.8}
    }
    
    gpt_config = config.get(plan, config["free"])
    
    for attempt in range(max_retries + 1):
        try:
            client, client_type = gpt_balancer.get_available_client()
            
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
            
            # JSON validity check
            json.loads(response_content)
            
            gpt_balancer.report_success(client_type)
            print(f"✅ GPT response received from {client_type} client (attempt {attempt + 1})")
            return response_content
            
        except Exception as e:
            print(f"❌ GPT API error on attempt {attempt + 1}: {str(e)}")
            if attempt < max_retries:
                gpt_balancer.report_failure(client_type if 'client_type' in locals() else "unknown")
                await asyncio.sleep(1 * (attempt + 1))  # Exponential backoff
            else:
                raise e

@router.post("/suggest-outfit", response_model=OutfitResponse)
async def suggest_outfit(request: OutfitRequest, user_info: dict = Depends(check_usage_and_get_user_data)):
    """Gelişmiş kombin öneri endpoint'i"""
    try:
        user_id, plan, gender = user_info["user_id"], user_info["plan"], user_info["gender"]
        
        # Akıllı gardrop seçimi
        recent_items = {item for outfit in request.last_5_outfits for item in outfit.items}
        context = {
            'weather': request.weather_condition,
            'occasion': request.occasion,
            'recent_items': recent_items
        }
        
        # Plan bazlı limit
        wardrobe_limit = 250 if plan == "premium" else 150
        selected_wardrobe = outfit_engine.smart_wardrobe_selection(
            request.wardrobe, context, wardrobe_limit
        )
        
        print(f"🎯 Selected {len(selected_wardrobe)}/{len(request.wardrobe)} wardrobe items for {plan} user")
        
        # Gardrop analizi
        wardrobe_summary = outfit_engine.analyze_wardrobe(selected_wardrobe)
        
        # Gelişmiş prompt oluştur
        prompt = outfit_engine.create_advanced_prompt(request, gender, wardrobe_summary)
        
        # GPT API çağrısı (retry logic ile)
        response_content = await call_gpt_with_retry(prompt, plan)
        
        # JSON parse
        ai_response = json.loads(response_content)
        
        # Kombin yapısını doğrula ve düzelt
        final_items = outfit_engine.validate_outfit_structure(
            ai_response.get("items", []), selected_wardrobe
        )
        
        if not final_items:
            raise HTTPException(status_code=500, detail="Could not create a valid outfit")
        
        # Kullanım sayacını artır
        db.collection('users').document(user_id).update({'usage.count': firestore.Increment(1)})
        
        # Response oluştur
        response_data = {
            "items": final_items,
            "description": ai_response.get("description", ""),
            "suggestion_tip": ai_response.get("suggestion_tip", "")
        }
        
        # Premium kullanıcılar için Pinterest linklerini ekle
        if plan == "premium" and "pinterest_links" in ai_response:
            response_data["pinterest_links"] = ai_response["pinterest_links"]
        
        print(f"✅ Outfit suggestion created successfully for {plan} user")
        return OutfitResponse(**response_data)
        
    except json.JSONDecodeError as e:
        print(f"❌ JSON Parse Error: {str(e)}")
        raise HTTPException(status_code=500, detail="AI response parsing failed")
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Outfit suggestion error: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Outfit suggestion failed: {str(e)}")

@router.get("/usage-status")
async def get_usage_status(user_id: str = Depends(get_current_user_id)):
    """Kullanım durumu"""
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