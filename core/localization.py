# kodlar/localization.py

"""
Uygulama genelindeki tüm metin anahtarlarının dil çevirilerini içerir.
Yeni bir dil eklemek için, 'TRANSLATIONS' sözlüğüne yeni bir anahtar 
(örn: 'de' Almanca için) ve ilgili çeviri sözlüklerini ekleyin.
"""

TRANSLATIONS = {
    "en": {
        "colors": {
            "white": "White", "gray": "Gray", "fume": "Charcoal", "black": "Black",
            "cream": "Cream", "beige": "Beige", "tan": "Tan", "cinnamon": "Cinnamon",
            "earth": "Earth", "chestnut": "Chestnut", "plum": "Plum", "khaki": "Khaki",
            "lemon": "Lemon", "yellow": "Yellow", "gold": "Gold", "mustard": "Mustard",
            "peach": "Peach", "apricot": "Apricot", "salmon": "Salmon", "orange": "Orange",
            "dusty-pink": "Dusty Rose", "coral": "Coral", "pomegranate-red": "Pomegranate",
            "red": "Red", "cherry-red": "Cherry", "dark-red": "Burgundy", "pink": "Pink",
            "fuchsia": "Fuchsia", "lilac": "Lilac", "lavender": "Lavender", "violet": "Violet",
            "purple": "Purple", "ice-blue": "Ice Blue", "turquoise": "Turquoise", "blue": "Blue",
            "saxony-blue": "Royal Blue", "navy": "Navy", "mint": "Mint", "water-green": "Aqua Green",
            "grass-green": "Grass Green", "emerald": "Emerald", "green": "Green", "olive": "Olive",
            "silver": "Silver", "bronze": "Bronze", "leopard": "Leopard", "zebra": "Zebra",
            "snakeskin": "Snakeskin", "striped": "Striped", "plaid": "Plaid", "floral": "Floral",
            "polka-dot": "Polka Dot"
        },
        "categories": {
            # Ana kategoriler (AI'ın doğrudan kullanması gerekmese de referans için)
            "top": "Top Wear", "bottom": "Bottom Wear", "dresses-jumpsuits": "Dresses & Jumpsuits",
            "outerwear": "Outerwear", "shoes": "Shoes", "bags": "Bags", "accessories": "Accessories", "suits": "Suits",
            # Alt Kategoriler (AI'ın kullanacağı asıl anahtarlar)
            "t-shirt": "T-Shirt", "blouse": "Blouse", "shirt": "Shirt", "sweater": "Sweater", "pullover": "Pullover",
            "sweatshirt": "Sweatshirt", "hoodie": "Hoodie", "track-top": "Track Top", "crop-top": "Crop Top",
            "tank-top": "Tank Top", "bodysuit": "Bodysuit", "vest": "Vest", "tunic": "Tunic", "bralette": "Bralette",
            "jeans": "Jeans", "trousers": "Trousers", "linen-trousers": "Linen Trousers", "leggings": "Leggings",
            "track-bottom": "Track Bottom", "mini-skirt": "Mini Skirt", "midi-skirt": "Midi Skirt", "long-skirt": "Long Skirt",
            "denim-shorts": "Denim Shorts", "fabric-shorts": "Fabric Shorts", "athletic-shorts": "Athletic Shorts",
            "bermuda-shorts": "Bermuda Shorts", "capri-pants": "Capri Pants", "casual-dress": "Casual Dress",
            "evening-dress": "Evening Dress", "sporty-dress": "Sporty Dress", "modest-dress": "Modest Dress",
            "modest-evening-dress": "Modest Evening Dress", "jumpsuit": "Jumpsuit", "romper": "Romper",
            "puffer-coat": "Puffer Coat", "raincoat": "Raincoat", "denim-jacket": "Denim Jacket",
            "leather-jacket": "Leather Jacket", "fabric-jacket": "Fabric Jacket", "bomber-jacket": "Bomber Jacket",
            "overcoat": "Overcoat", "coat": "Coat", "trenchcoat": "Trenchcoat", "blazer": "Blazer",
            "cardigan": "Cardigan", "abaya": "Abaya", "sneakers": "Sneakers", "casual-sport-shoes": "Casual Sport Shoes",
            "heels": "Heels", "boots": "Boots", "tall-boots": "Tall Boots", "flats": "Flats", "loafers": "Loafers",
            "bootie": "Bootie", "sandals": "Sandals", "slippers": "Slippers", "classic-shoes": "Classic Shoes",
            "handbag": "Handbag", "backpack": "Backpack", "shoulder-bag": "Shoulder Bag", "briefcase": "Briefcase",
            "crossbody-bag": "Crossbody Bag", "necklace": "Necklace", "earrings": "Earrings", "ring": "Ring",
            "bracelet": "Bracelet", "scarf": "Scarf", "hijab": "Hijab", "shawl": "Shawl", "sunglasses": "Sunglasses",
            "belt": "Belt", "hat": "Hat", "watch": "Watch", "tie": "Tie", "suit-jacket": "Suit Jacket",
            "suit-trousers": "Suit Trousers", "tuxedo": "Tuxedo", "polo-shirt": "Polo Shirt"
        },
        "occasions": {
            "categories": {
                "casual": "Casual", "work": "Work & Professional", "formal": "Celebration & Formal",
                "social": "Social", "active": "Active & Sports", "special": "Travel & Special"
            },
            "daily-errands": "Daily Errands", "friends-gathering": "Friends Gathering", "weekend-brunch": "Weekend Brunch",
            "coffee-date": "Coffee", "shopping": "Shopping", "walk": "A Walk", "office-day": "Day at the Office",
            "business-meeting": "Business Meeting", "business-lunch": "Business Lunch", "networking": "Networking Event",
            "university": "University / Class", "wedding": "Wedding", "special-event": "Special Event",
            "celebration": "Celebration", "formal-dinner": "Formal Dinner", "dinner-date": "Dinner Date",
            "birthday-party": "Birthday Party", "concert": "Concert", "night-out": "Night Out",
            "house-party": "House Party", "gym": "Gym / Fitness", "yoga-pilates": "Yoga / Pilates",
            "outdoor-sports": "Outdoor Sports", "hiking": "Hiking", "travel": "Travel",
            "weekend-getaway": "Weekend Getaway", "holiday": "Holiday", "festival": "Festival", "sightseeing": "Sightseeing"
        }
    },
    "tr": {
        "colors": {
            "white": "Beyaz", "gray": "Gri", "fume": "Füme", "black": "Siyah", "cream": "Krem",
            "beige": "Bej", "tan": "Taba", "cinnamon": "Tarçın", "earth": "Toprak", "chestnut": "Kestane",
            "plum": "Mürdüm", "khaki": "Haki", "lemon": "Limon", "yellow": "Sarı", "gold": "Altın",
            "mustard": "Hardal", "peach": "Şeftali", "apricot": "Yavruağzı", "salmon": "Somon",
            "orange": "Portakal", "dusty-pink": "Toz Pembe", "coral": "Mercan", "pomegranate-red": "Nar Çiçeği",
            "red": "Kırmızı", "cherry-red": "Kiraz", "dark-red": "Vişne", "pink": "Pembe", "fuchsia": "Fuşya",
            "lilac": "Leylak", "lavender": "Lavanta", "violet": "Menekşe", "purple": "Mor",
            "ice-blue": "Buz Mavisi", "turquoise": "Turkuaz", "blue": "Mavi", "saxony-blue": "Saks Mavisi",
            "navy": "Lacivert", "mint": "Nane", "water-green": "Su Yeşili", "grass-green": "Çimen Yeşili",
            "emerald": "Zümrüt", "green": "Yeşil", "olive": "Zeytin Yeşili", "silver": "Gümüş",
            "bronze": "Bronz", "leopard": "Leopar", "zebra": "Zebra", "snakeskin": "Yılan",
            "striped": "Çizgili", "plaid": "Kareli", "floral": "Çiçekli", "polka-dot": "Puantiye"
        },
        "categories": {
            "top": "Üst Giyim", "bottom": "Alt Giyim", "dresses-jumpsuits": "Elbise & Tulum",
            "outerwear": "Dış Giyim", "shoes": "Ayakkabı", "bags": "Çanta", "accessories": "Aksesuar", "suits": "Takım Elbise",
            "t-shirt": "Tişört", "blouse": "Bluz", "shirt": "Gömlek", "sweater": "Kazak", "pullover": "Süveter",
            "sweatshirt": "Sweatshirt", "hoodie": "Kapüşonlu Sweatshirt", "track-top": "Eşofman Üstü",
            "crop-top": "Crop Top", "tank-top": "Atlet", "bodysuit": "Bodysuit", "vest": "Yelek",
            "tunic": "Tunik", "bralette": "Bralet", "jeans": "Kot Pantolon", "trousers": "Kumaş Pantolon",
            "linen-trousers": "Keten Pantolon", "leggings": "Tayt", "track-bottom": "Eşofman Altı",
            "mini-skirt": "Mini Etek", "midi-skirt": "Midi Etek", "long-skirt": "Uzun Etek",
            "denim-shorts": "Kot Şort", "fabric-shorts": "Kumaş Şort", "athletic-shorts": "Spor Şort",
            "bermuda-shorts": "Bermuda Şort", "capri-pants": "Kapri", "casual-dress": "Günlük Elbise",
            "evening-dress": "Gece Elbisesi", "sporty-dress": "Spor Elbise", "modest-dress": "Tesettür Elbise",
            "modest-evening-dress": "Tesettür Abiye", "jumpsuit": "Tulum", "romper": "Şort Tulum",
            "puffer-coat": "Şişme Mont", "raincoat": "Yağmurluk", "denim-jacket": "Kot Ceket",
            "leather-jacket": "Deri Ceket", "fabric-jacket": "Kumaş Ceket", "bomber-jacket": "Bomber Ceket",
            "overcoat": "Palto", "coat": "Kaban", "trenchcoat": "Trençkot", "blazer": "Blazer",
            "cardigan": "Hırka", "abaya": "Ferace", "sneakers": "Sneakers", "casual-sport-shoes": "Casual Spor",
            "heels": "Topuklu Ayakkabı", "boots": "Bot", "tall-boots": "Çizme", "flats": "Babet",
            "loafers": "Loafer", "bootie": "Bot", "sandals": "Sandalet", "slippers": "Terlik",
            "classic-shoes": "Klasik Ayakkabı", "handbag": "El Çantası", "backpack": "Sırt Çantası",
            "shoulder-bag": "Omuz Çantası", "briefcase": "Evrak Çantası", "crossbody-bag": "Çapraz Çanta",
            "necklace": "Kolye", "earrings": "Küpe", "ring": "Yüzük", "bracelet": "Bileklik",
            "scarf": "Eşarp", "hijab": "Başörtüsü", "shawl": "Şal", "sunglasses": "Güneş Gözlüğü",
            "belt": "Kemer", "hat": "Şapka", "watch": "Saat", "tie": "Kravat", "suit-jacket": "Takım Ceket",
            "suit-trousers": "Takım Pantolon", "tuxedo": "Smokin", "polo-shirt": "Polo Tişört"
        },        "occasions": {
        "categories": {
                "casual": "Günlük", "work": "İş & Profesyonel", "formal": "Kutlama & Resmi",
                "social": "Sosyal", "active": "Aktif & Spor", "special": "Seyahat & Özel"
            },
            "daily-errands": "Günlük İşler", "friends-gathering": "Arkadaş Buluşması", "weekend-brunch": "Hafta Sonu Kahvaltısı",
            "coffee-date": "Kahve", "shopping": "Alışveriş", "walk": "Yürüyüş", "office-day": "Ofis Günü",
            "business-meeting": "İş Toplantısı", "business-lunch": "İş Yemeği", "networking": "Sektörel Buluşma",
            "university": "Üniversite / Ders", "wedding": "Düğün", "special-event": "Özel Etkinlik",
            "celebration": "Kutlama", "formal-dinner": "Resmi Akşam Yemeği", "dinner-date": "Akşam Yemeği Randevusu",
            "birthday-party": "Doğum Günü Partisi", "concert": "Konser", "night-out": "Gece Dışarı Çıkma",
            "house-party": "Ev Partisi", "gym": "Spor Salonu / Fitness", "yoga-pilates": "Yoga / Pilates",
            "outdoor-sports": "Açık Hava Sporları", "hiking": "Doğa Yürüyüşü", "travel": "Seyahat",
            "weekend-getaway": "Hafta Sonu Kaçamağı", "holiday": "Tatil", "festival": "Festival", "gezi": "Gezi"
        }
    }
}

def get_translation(lang_code: str, key: str, default_lang: str = 'en'):
    """
    Belirtilen dil ve anahtar için çeviriyi alır.
    Bulamazsa, varsayılan dildeki çeviriyi döner.
    """
    return TRANSLATIONS.get(lang_code, TRANSLATIONS[default_lang]).get(key, {})