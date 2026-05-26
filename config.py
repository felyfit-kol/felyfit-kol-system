"""Constantes y parametros del sistema. Tunables sin tocar logica."""

# ============================================================
# PR PACK — COGS estandar (en MXN)
# ============================================================
STANDARD_PR_PACK_COGS_MXN = 469.80  # 69.80 empaque + 150 legging + 200 legging + 50 calcetas
STANDARD_PR_PACK_RETAIL_MXN = 1_400  # valor retail para comunicar a creadora

# ============================================================
# EMV — Multiplicadores (MXN). Estos definen cuanto vale cada accion.
# Editables desde la UI Settings sin tocar codigo.
# ============================================================
EMV_MULTIPLIERS = {
    "like_mxn": 0.30,
    "comment_mxn": 3.00,
    "save_mxn": 5.00,
    "share_mxn": 6.00,
    "view_mxn": 0.05,
    "follower_mxn": 12.00,  # por nuevo follower atribuible
}

POST_VALUE_BY_TIER_MXN = {
    "nano": 800,
    "micro": 2_500,
    "mid": 7_000,
    "macro": 20_000,
    "mega": 60_000,
}

EMV_TARGET_RATIO = 3.0  # KPI quarterly del brief — minimo aceptable (Total Ratio)

# ============================================================
# Tiers de seguidores (en miles, K). Followers entre [low, high).
# ============================================================
TIERS_K = [
    ("nano", 1, 10),
    ("micro", 10, 50),
    ("mid", 50, 150),
    ("macro", 150, 500),
    ("mega", 500, 10_000),
]

# ============================================================
# Fit Score — pesos (suma = 100)
# ============================================================
FIT_SCORE_WEIGHTS = {
    "engagement_rate": 40,    # ER es el predictor numero 1 de resultado
    "niche_relevance": 25,    # cuanto matchea con activewear/wellness/fitness
    "tier_band": 20,          # bonus por estar en 10K-150K (sweet spot costo/beneficio)
    "location_mx": 10,        # bonus por MX
    "bot_flag_penalty": -5,   # se resta si pinta a bots
}

# Targets para normalizar cada subscore (0..1) antes de aplicar peso
FIT_SCORE_TARGETS = {
    "er_min_acceptable": 0.025,   # 2.5%
    "er_full_score_at": 0.06,     # 6% = puntaje completo en ER
    "sweet_spot_followers_k_low": 10,
    "sweet_spot_followers_k_high": 100,
    "max_likes_to_comments_ratio": 80,
    # Para cuentas con < followers_floor_for_full_er_score followers, el ER cuenta menos
    # porque pocos likes pueden inflar ER artificialmente
    "followers_floor_for_full_er_score": 5_000,
}

# Nichos relevantes (matcheo en bio + hashtags + captions)
RELEVANT_NICHES = {
    # EN
    "fitness", "wellness", "activewear", "yoga", "pilates",
    "running", "gym", "athleisure", "fit", "fitgirl", "gymrat",
    "barre", "cycling", "spinning", "crossfit", "strength",
    "mind", "body", "soul", "selfcare", "movement",
    "athlete", "training", "workout", "coach", "pt",
    "lifestyle", "healthy", "nutrition",
    # ES
    "salud", "movimiento", "mujeresfit", "wellnessmexico",
    "deportiva", "atleta", "atletismo", "entrenamiento",
    "calistenia", "calisthenics", "deporte", "correr", "ciclismo",
    "saludable", "vida", "bienestar", "alimentacion",
}

# ============================================================
# Apify — actor IDs (no cambiar a menos que migremos de actor)
# ============================================================
APIFY_ACTORS = {
    "instagram_profile": "apify/instagram-profile-scraper",
    "instagram_hashtag": "apify/instagram-hashtag-scraper",
    "instagram_scraper": "apify/instagram-scraper",
    "instagram_post": "apify/instagram-post-scraper",
    "instagram_stories": "gordian/instagram-story-scraper",  # $0.001/story
}

# ============================================================
# FelyFit brand mentions — para detectar en stories
# ============================================================
FELYFIT_HANDLES = ["felyfit_mx", "felyfit", "felyfitmx"]
FELYFIT_HASHTAGS = ["felyfit", "felyfit_mx", "felyfitmexico"]
FELYFIT_KEYWORDS_IN_CAPTION = ["felyfit", "fely fit"]  # case-insensitive contains


# ============================================================
# Multiplicadores EMV por tipo de contenido
# El EMV base se estima por 1 post normal de grid. Otros formatos
# multiplican según alcance orgánico esperado y persistencia.
# ============================================================
CONTENT_TYPE_EMV_MULTIPLIERS = {
    "reel":      1.6,   # alto alcance orgánico, video > foto
    "carousel":  1.2,   # más swipes = más engagement
    "post":      1.0,   # base
    "live":      1.4,   # alta intent, replay disponible
    "story":     0.30,  # individual; corto, expira 24h
}

CONTENT_TYPE_LABELS = {
    "reel":      "🎬 Reel",
    "carousel":  "🎠 Carousel",
    "post":      "🖼️ Post grid",
    "live":      "📡 Live",
    "story":     "📸 Story",
}

# ============================================================
# Scouting — defaults para discovery
# ============================================================
SCOUTING_DEFAULTS = {
    "hashtags_seed": [
        "activewearmexico", "fitnessmx", "pilatesmx",
        "yogamx", "wellnessmx", "athleisuremx",
        "mujeresfit", "fitmomex", "gymgirlmx",
        "correrenmexico", "pilatesreformermx",
        "movimientoymujer", "saludymovimiento",
    ],
    "competitor_handles_seed": [
        "alo.yoga", "setactive", "stripzone_mx",
        "cottonon.mx", "gymsharkmx", "adidaswomenmx",
    ],
    "max_candidates_per_hashtag_run": 50,
}


# ============================================================
# CANDIDATA IDEAL — Filtros estrictos. Las que no pasan se BORRAN del DB.
# Cubrimos de nano a macro/mega; el ER min se ajusta por tier
# (cuentas grandes naturalmente tienen ER mas bajo).
# ============================================================
IDEAL_CRITERIA = {
    # Followers — piso de 10K (decisión Lucy 2026-05-18: cuentas <10K no
    # justifican el costo de outreach/PR, aunque sean individuales con buen ER).
    # Esto deja fuera el tier `nano` por completo; el primer tier real es micro.
    "followers_min": 10_000,
    "followers_max": 1_500_000,

    # ER por tier — bigger accounts get more lenient threshold.
    # Ajustados a la realidad MX 2026: ER promedio en fitness ha bajado.
    # Nano queda alto pero el floor de followers_min ya lo descarta antes.
    "er_min_by_tier": {
        "nano":  0.035,   # no aplica con floor 10K, dejado por completitud
        "micro": 0.020,   # 2.0%+ (10K-50K)
        "mid":   0.015,   # 1.5%+ (50K-150K)
        "macro": 0.010,   # 1.0%+ (150K-500K)
        "mega":  0.007,   # 0.7%+ (500K+)
    },
    "er_max": 0.20,       # arriba: sospechoso de bot inflation

    # Calidad de contenido
    "min_niche_match_score": 0.3,  # relajado: la mayor parte no escribe keywords completos
    "min_posts_last_12": 3,
    "max_likes_to_comments_ratio": 80,

    # Anti-fake-audience (audience genuinamente engaged, no compradas)
    "min_follower_following_ratio": 2.0,  # debe tener >2x mas followers que following

    # Actividad (recency)
    "max_days_since_last_post": 30,  # debe haber publicado en ultimos 30 dias

    # Tipo de cuenta
    "exclude_private": True,
    "exclude_business_account_unless_creator": True,

    # Filtros de handle (descartar marcas antes de gastar enrichment)
    "skip_handle_keywords": [
        "studio", "shop", "store", "brand", "boutique", "tienda",
        "official", "_oficial", "wear", "company", "inc", "app",
        "studios", "estudio",
        # Gimnasios / academias / clubs
        "gym", "gimnasio", "academy", "academia", "_club",
        # Suplementos / equipamiento
        "supplements", "suplementos", "supps", "nutrition",
    ],
    # Si full_name contiene estos -> es marca/estudio, no creadora individual
    "skip_fullname_keywords": [
        "studio", "estudio", "boutique", "official", "oficial",
        "store", "shop", "tienda", "brand", "marca",
        "gym", "gimnasio", "academy", "academia", "club deportivo",
        "supplements", "suplementos", "supps", "nutrition", "nutrici",
        "federación", "federacion", "federation", "comunidad",
    ],
}

# ============================================================
# Tracking — defaults
# ============================================================
# Temas para scout multi-hashtag — el sistema itera hasta tener target aptas.
# Cada tema es lista ordenada (más relevante MX-céntrico primero).
HASHTAG_THEMES = {
    "Fitness MX (general)": [
        # Hashtags MX-céntricos amplios
        "fitnessmexico", "mujeresfit", "fitnessmx", "fitmomex",
        "gymgirlmx", "fitnessmotivacion", "entrenamientomx",
        "deportemexico", "personaltrainermexico",
        # Más MX-specific
        "mujerfit", "fitlatina", "fitlife", "fitnesslifestyle",
        "trainerinmexico", "coachfitness", "vidafitness",
        "saludyfitness", "bodybuildingmx", "transformacionfit",
        # Ciudades
        "fitcdmx", "fitmonterrey", "fitguadalajara",
    ],
    "Yoga MX": [
        "yogamx", "yogamexico", "yogainstructormx", "yogacdmx",
        "yogateacher", "yogalifemx",
        "yogamty", "yogagdl", "yogaqueretaro", "yogaeveryday",
        "yogainspiration", "yogapose", "yogalifestyle",
    ],
    "Pilates MX": [
        "pilatesmx", "pilatesreformermx", "pilatesinstructormx",
        "pilatesmexico", "pilatesreformer",
        "pilatescdmx", "pilatesmty", "pilatesgdl",
        "pilateslove", "pilatesbody", "pilatestime",
    ],
    "Running MX": [
        "correrenmexico", "runnersmx", "corremx", "runningmexico",
        "maratoncdmx", "atletismomx",
        "runnersworld", "runnergirl", "marathonmexico",
        "trailrunningmexico", "ultramaraton",
    ],
    "Wellness MX": [
        "wellnessmx", "wellnessmexico", "saludymovimiento",
        "movimientoymujer", "bienestarmx", "vidasanamx",
        "lifestylefit", "mujersaludable", "salud", "balanceenlavida",
        "selfcaremujer", "rutinadiaria",
    ],
    "Activewear / Athleisure MX": [
        "activewearmexico", "athleisuremx", "ropadeportivamexico",
        "gymwearmx", "fitnessfashion",
        "ootdfitness", "gymoutfitmx", "leggings",
    ],
    "Crossfit / Strength MX": [
        "crossfitmexico", "crossfitmx", "strengthtrainingmx",
        "gymtimemx", "pesasmx",
        "powerliftingmx", "strongwoman", "crossfitgirl",
        "musculacionmx",
    ],
}


TRACKING_DAYS_DEFAULT = 14
TRACKING_DAILY_REFRESH = True

# ============================================================
# Lark
# ============================================================
LARK_CREADORAS_TABLE_ID = "tblLoIuuuGTyyWB1"  # tabla "Creadoras IG"
LARK_STATUS_ON_APPROVE = "Prospecting"  # status que se setea cuando aprobamos candidata
