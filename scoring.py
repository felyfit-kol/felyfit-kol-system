"""Formulas: Fit Score, EMV, Max Cash Investable, ratios.

Toda decision numerica del sistema vive aqui. UI y CLI son tontas, solo llaman estas.
"""

import json
import re
from typing import Dict, List, Optional, Tuple

import config


# ============================================================
# Tier classification
# ============================================================
def tier_from_followers(followers: int) -> str:
    k = (followers or 0) / 1000
    for name, low, high in config.TIERS_K:
        if low <= k < high:
            return name
    return "nano" if k < 1 else "mega"


# ============================================================
# Fit Score
# ============================================================
def _norm_er(er: Optional[float], followers: int = 0) -> float:
    """Engagement rate score 0..1. Below min = 0, at or above target = 1.

    Penaliza ER de cuentas muy chicas (donde el ER se distorsiona).
    """
    if er is None:
        return 0.0
    lo = config.FIT_SCORE_TARGETS["er_min_acceptable"]
    hi = config.FIT_SCORE_TARGETS["er_full_score_at"]
    if er <= lo:
        return 0.0
    if er >= hi:
        base = 1.0
    else:
        base = (er - lo) / (hi - lo)
    # Discount si followers < piso (ER no es confiable)
    floor = config.FIT_SCORE_TARGETS["followers_floor_for_full_er_score"]
    if followers and followers < floor:
        base = base * (followers / floor)  # escala lineal: 2.5K followers = 0.5x del score
    return base


def _norm_niche(bio: Optional[str], hashtags: Optional[List[str]], mentions: Optional[List[str]]) -> float:
    """Niche relevance score 0..1. Cuenta cuantas senales tienen overlap con RELEVANT_NICHES."""
    text_blobs = []
    if bio:
        text_blobs.append(bio.lower())
    if hashtags:
        text_blobs.extend(h.lower().lstrip("#") for h in hashtags)
    if mentions:
        text_blobs.extend(m.lower().lstrip("@") for m in mentions)

    if not text_blobs:
        return 0.0

    relevant = config.RELEVANT_NICHES
    hits = 0
    for blob in text_blobs:
        # tokens approx
        tokens = re.findall(r"[a-zA-ZáéíóúñÁÉÍÓÚÑ]+", blob)
        for tok in tokens:
            if tok.lower() in relevant:
                hits += 1
                break  # cuenta una vez por blob
    # 0 hits -> 0, 1 hit -> 0.5, 3+ -> 1.0
    if hits == 0:
        return 0.0
    if hits == 1:
        return 0.5
    if hits == 2:
        return 0.8
    return 1.0


def _norm_tier_band(followers: int) -> float:
    """1.0 si estas dentro del sweet spot de followers, 0.5 si fuera por poco, 0.2 si lejos."""
    k = (followers or 0) / 1000
    lo = config.FIT_SCORE_TARGETS["sweet_spot_followers_k_low"]
    hi = config.FIT_SCORE_TARGETS["sweet_spot_followers_k_high"]
    if lo <= k <= hi:
        return 1.0
    # cerca: dentro de 50% del rango
    if k > hi:
        ratio = k / hi
        if ratio < 1.5:
            return 0.7
        if ratio < 3:
            return 0.4
        return 0.2
    # debajo del minimo
    ratio = k / lo if lo else 0
    if ratio > 0.5:
        return 0.5
    return 0.1


def _norm_location_mx(estimated_city: Optional[str]) -> float:
    if not estimated_city:
        return 0.5  # incierto, no penalizamos full
    mx_keywords = {"mexico", "mx", "cdmx", "monterrey", "guadalajara", "puebla",
                   "queretaro", "merida", "cancun", "tijuana", "pachuca", "cuernavaca"}
    return 1.0 if estimated_city.lower() in mx_keywords else 0.0


# ============================================================
# Pais detection — heuristic por bio + ciudad
# ============================================================
COUNTRY_SIGNALS = {
    "MX": ["🇲🇽", "méxico", "mexico", " mx ", "mx,", "mx.", "cdmx", "monterrey", "guadalajara",
           "puebla", "queretaro", "merida", "cancun", "tijuana", "pachuca", "cuernavaca",
           "playa del carmen", "oaxaca", "morelia", "leon", "san luis potosi", "veracruz"],
    "US": ["🇺🇸", "usa", "united states", " ny ", " la ", "miami", "los angeles",
           "new york", "houston", "texas", "california", "florida"],
    "AR": ["🇦🇷", "argentina", "buenos aires", "córdoba", "rosario"],
    "CO": ["🇨🇴", "colombia", "bogotá", "bogota", "medellín", "medellin", "cali"],
    "ES": ["🇪🇸", "españa", "spain", "madrid", "barcelona", "valencia", "sevilla"],
    "PE": ["🇵🇪", "perú", "peru", "lima"],
    "CL": ["🇨🇱", "chile", "santiago"],
    "BR": ["🇧🇷", "brasil", "brazil", "são paulo", "sao paulo", "rio de janeiro"],
}


def detect_country(bio: Optional[str], estimated_city: Optional[str] = None) -> Optional[str]:
    """Detecta país desde bio/ciudad. Devuelve código ISO o None si no detectable.

    Fallback cuando NO tenemos `about.country` de Apify.
    """
    text = " ".join(filter(None, [bio, estimated_city])).lower()
    if not text:
        return None
    for iso, signals in COUNTRY_SIGNALS.items():
        for s in signals:
            if s in text:
                return iso
    return None


# Mapeo de nombres de país de Apify (about.country) → ISO codes
IG_COUNTRY_TO_ISO = {
    "mexico": "MX", "méxico": "MX",
    "united states": "US", "usa": "US",
    "argentina": "AR",
    "colombia": "CO",
    "spain": "ES", "españa": "ES",
    "peru": "PE", "perú": "PE",
    "chile": "CL",
    "brazil": "BR", "brasil": "BR",
    "canada": "CA", "canadá": "CA",
    "uruguay": "UY",
    "ecuador": "EC",
    "venezuela": "VE",
    "guatemala": "GT",
    "panama": "PA", "panamá": "PA",
    "costa rica": "CR",
    "dominican republic": "DO", "república dominicana": "DO",
    "puerto rico": "PR",
    "united kingdom": "GB",
    "france": "FR", "francia": "FR",
    "germany": "DE", "alemania": "DE",
    "italy": "IT", "italia": "IT",
}


# ============================================================
# Gender detection — heuristica por primer nombre
# ============================================================
FIRST_NAMES_FEMALE = {
    "ana", "andrea", "alejandra", "alexa", "alicia", "alina", "alondra", "anabel", "andrea",
    "angela", "angelica", "angie", "anna", "antonella", "antonia", "arantxa", "ariadna",
    "ariana", "ashley", "andi", "alanya",
    "barbara", "bárbara", "beatriz", "berenice", "bianca", "blanca",
    "camila", "camille", "carla", "carmen", "carolina", "catalina", "cecilia", "claudia",
    "clara", "cristina", "cristy", "cynthia", "constanza", "coral", "celeste",
    "dana", "daniela", "deborah", "diana", "dolores", "dulce", "danny",
    "elena", "elisa", "emma", "ester", "estefania", "estefanía", "eva", "evelyn",
    "fanny", "fatima", "fátima", "fernanda", "florencia", "frida",
    "gabriela", "gaby", "georgina", "giselle", "gloria", "grecia",
    "hannah", "helena",
    "ines", "inés", "irene", "isabel", "isabella", "isadora",
    "jacqueline", "jana", "jenifer", "jennifer", "jessica", "jimena", "julia", "julieta",
    "jocelyn", "joselyn",
    "karen", "karina", "karla", "kate", "kim", "katherine", "kathy",
    "laura", "leslie", "leticia", "lia", "liliana", "lilia", "lily", "linda", "lola", "lourdes",
    "lucia", "lucía", "lucy", "luna", "lupita",
    "macarena", "magdalena", "maite", "marcela", "maria", "maría", "mariana", "mariel",
    "marielle", "marisol", "marta", "martina", "mayte", "melissa", "michelle", "mia", "miranda",
    "monica", "mónica", "mariana", "marian", "monse", "monserrat",
    "naomi", "natalia", "nathalie", "nayeli", "nicole", "noelia",
    "olivia",
    "paola", "patricia", "paula", "paulina", "perla", "phanie", "pilar", "priscila",
    "raquel", "regina", "rebeca", "renata", "rocio", "rocío", "romina", "rosa", "rosana",
    "rossana", "roxana", "roxsmar", "ruth",
    "sandra", "sara", "sarah", "scarlett", "scarletth", "selene", "silvia", "sofia", "sofía",
    "sonia", "stefania", "stephanie", "susana", "susy",
    "tamara", "tania", "tatiana", "teresa", "telma",
    "valentina", "valeria", "vanessa", "victoria", "violeta", "virginia", "viviana",
    "ximena", "xiomara",
    "yael", "yamila", "yanet", "yenifer", "yesenia", "yolanda",
    "zoe",
}

FIRST_NAMES_MALE = {
    "abraham", "adrian", "agustin", "alan", "alberto", "alejandro", "alex", "alexander",
    "alfonso", "alfredo", "andres", "andrés", "angel", "ángel", "antonio", "ariel", "arturo",
    "benjamin", "benjamín", "bernardo", "bruno",
    "camilo", "carlos", "cesar", "césar", "claudio", "cristian", "cristóbal", "cristobal",
    "damian", "damián", "daniel", "dario", "darío", "david", "diego", "domingo",
    "eduardo", "elias", "elías", "emiliano", "emilio", "enrique", "ernesto", "esteban",
    "ezequiel",
    "fabian", "fabián", "fede", "federico", "felipe", "fernando", "francisco", "frank",
    "gabriel", "german", "germán", "gerardo", "gonzalo", "guillermo", "gustavo",
    "hector", "héctor", "hugo",
    "ignacio", "ivan", "iván",
    "jaime", "javier", "jesus", "jesús", "joaquin", "joaquín", "joel", "jordan", "jordi",
    "jorge", "jose", "josé", "juan", "julian", "julián", "julio",
    "kevin",
    "leonardo", "leopoldo", "lucas", "luis",
    "manuel", "marco", "marcos", "mariano", "mario", "martin", "martín", "mateo", "matias",
    "matías", "mauricio", "miguel",
    "nestor", "néstor", "nicolas", "nicolás",
    "octavio", "omar", "oscar", "óscar",
    "pablo", "patricio", "pedro", "pol",
    "rafa", "rafael", "ramon", "ramón", "raul", "raúl", "ricardo", "rigoberto", "roberto",
    "rodolfo", "rodrigo", "roman", "rubén", "ruben",
    "salvador", "samuel", "santiago", "saul", "saúl", "sebastian", "sebastián", "sergio",
    "simon", "simón",
    "tito", "tomas", "tomás",
    "ulises",
    "valentin", "valentín", "vicente", "victor", "víctor",
    "xavier",
    "yago",
}


def detect_gender(full_name: Optional[str], handle: Optional[str] = None) -> Optional[str]:
    """Detecta género por primer nombre. Devuelve 'female' / 'male' / None.

    Heurística por base de nombres en español/inglés. Imperfecto (~75% accuracy)
    pero suficiente para filtrar la mayoría de los hombres del scout.
    """
    sources = []
    if full_name:
        sources.append(full_name)
    if handle:
        # Convertir handle a tokens (separar por . y _)
        sources.append(handle.replace(".", " ").replace("_", " "))

    for source in sources:
        # Tokens en lowercase, solo letras
        tokens = re.findall(r"[a-záéíóúñ]+", source.lower())
        for token in tokens:
            if len(token) < 3:
                continue
            if token in FIRST_NAMES_FEMALE:
                return "female"
            if token in FIRST_NAMES_MALE:
                return "male"
    return None  # unknown


def country_from_about(about_country: Optional[str]) -> Optional[str]:
    """Convierte el string de `about.country` que devuelve Apify a código ISO.

    Esta es la fuente AUTORITATIVA. Si Apify devuelve país aquí, ignora la detección
    bio-based.
    """
    if not about_country:
        return None
    return IG_COUNTRY_TO_ISO.get(about_country.lower().strip())


def _bot_flag_penalty(avg_likes: Optional[float], avg_comments: Optional[float]) -> float:
    """Returns 1.0 if penalty should apply (suspicious), 0.0 otherwise."""
    if not avg_likes or not avg_comments or avg_comments == 0:
        return 0.0
    ratio = avg_likes / avg_comments
    threshold = config.FIT_SCORE_TARGETS["max_likes_to_comments_ratio"]
    if ratio > threshold:
        return 1.0
    return 0.0


def compute_fit_score(
    *,
    engagement_rate: Optional[float],
    bio: Optional[str] = None,
    hashtags: Optional[List[str]] = None,
    mentions: Optional[List[str]] = None,
    followers: int = 0,
    estimated_city: Optional[str] = None,
    avg_likes: Optional[float] = None,
    avg_comments: Optional[float] = None,
) -> Tuple[float, Dict[str, float]]:
    """Devuelve (score 0..100, breakdown). Breakdown es serializable a JSON."""
    weights = config.FIT_SCORE_WEIGHTS

    subscores = {
        "engagement_rate": _norm_er(engagement_rate, followers),
        "niche_relevance": _norm_niche(bio, hashtags, mentions),
        "tier_band": _norm_tier_band(followers),
        "location_mx": _norm_location_mx(estimated_city),
        "bot_flag_penalty": _bot_flag_penalty(avg_likes, avg_comments),
    }

    score = (
        subscores["engagement_rate"] * weights["engagement_rate"]
        + subscores["niche_relevance"] * weights["niche_relevance"]
        + subscores["tier_band"] * weights["tier_band"]
        + subscores["location_mx"] * weights["location_mx"]
        + subscores["bot_flag_penalty"] * weights["bot_flag_penalty"]  # weight es negativo
    )
    score = max(0.0, min(100.0, score))

    breakdown = {
        k: {"raw": round(v, 3), "weighted": round(v * weights[k], 2)}
        for k, v in subscores.items()
    }
    return round(score, 2), breakdown


# ============================================================
# EMV (Earned Media Value)
# ============================================================
def compute_post_value(tier: str, num_posts: int = 1) -> float:
    """Valor de cada pieza creativa segun tier."""
    per_post = config.POST_VALUE_BY_TIER_MXN.get(tier, config.POST_VALUE_BY_TIER_MXN["nano"])
    return per_post * num_posts


def compute_emv(
    *,
    tier: str,
    num_posts: int = 1,
    likes: int = 0,
    comments: int = 0,
    saves: int = 0,
    shares: int = 0,
    views: int = 0,
    attributed_followers: int = 0,
    multipliers: Optional[dict] = None,
) -> float:
    """EMV en MXN. multipliers default a config.EMV_MULTIPLIERS."""
    m = multipliers or config.EMV_MULTIPLIERS
    return (
        compute_post_value(tier, num_posts)
        + (likes or 0) * m["like_mxn"]
        + (comments or 0) * m["comment_mxn"]
        + (saves or 0) * m["save_mxn"]
        + (shares or 0) * m["share_mxn"]
        + (views or 0) * m["view_mxn"]
        + (attributed_followers or 0) * m["follower_mxn"]
    )


def compute_ratios(emv: float, *,
                   cash_fee: float = 0,
                   usage_rights_fee: float = 0,
                   agency_fee: float = 0,
                   shipping_cost: float = 0,
                   cogs_pieces: float = 0) -> Tuple[Optional[float], Optional[float]]:
    """Returns (cash_ratio, total_ratio).

    Cash Ratio  = EMV / (cash + usage + agency + shipping)
    Total Ratio = EMV / (lo anterior + COGS pieces)
    """
    cash_denom = (cash_fee or 0) + (usage_rights_fee or 0) + (agency_fee or 0) + (shipping_cost or 0)
    total_denom = cash_denom + (cogs_pieces or 0)

    cash_ratio = (emv / cash_denom) if cash_denom > 0 else None
    total_ratio = (emv / total_denom) if total_denom > 0 else None
    return cash_ratio, total_ratio


def compute_max_cash_investable(
    *,
    expected_emv: float,
    cogs_pieces: float = config.STANDARD_PR_PACK_COGS_MXN,
    shipping_cost: float = 0,
    target_ratio: float = config.EMV_TARGET_RATIO,
) -> float:
    """Cuanto cash MAX puedes pagar a una creadora manteniendo target_ratio en Total Ratio.

    Total Ratio >= target_ratio
    => EMV / (cash + shipping + cogs) >= target_ratio
    => cash <= EMV/target_ratio - shipping - cogs
    """
    cap = (expected_emv / target_ratio) - shipping_cost - cogs_pieces
    return max(0.0, round(cap, 2))


# ============================================================
# Filtro "candidata ideal" — para mostrar solo las relevantes
# ============================================================
# ============================================================
# Clasificación de tipo de cuenta — heurística por bio + nombre + handle
# ============================================================
ACCOUNT_TYPE_LABELS = {
    "individual": ":material/person: Individual",
    "studio":     ":material/storefront: Studio",
    "brand":      ":material/shopping_bag: Brand",
    "nonprofit":  ":material/volunteer_activism: Nonprofit",
    "collective": ":material/groups: Collective",
    "unknown":    ":material/help: Unknown",
}


def classify_account_type(
    bio: Optional[str],
    full_name: Optional[str] = None,
    handle: Optional[str] = None,
) -> str:
    """Clasifica una cuenta como individual / studio / brand / nonprofit / collective.

    Heuristica por keywords en bio + nombre + handle. NO siempre acierta —
    el sistema solo la usa como filtro y la muestra como badge para revision humana.
    """
    text = " ".join(filter(None, [bio, full_name, handle])).lower()

    # NONPROFIT — señales fuertes
    nonprofit_signals = [
        "501(c)(3)", "501c3", "nonprofit", "non-profit", "non profit",
        " ngo ", " ong ", "asociación civil", "asociacion civil",
        "fundación", "fundacion", "charity", "we've helped", "we help athletes",
        "donate", "donar",
    ]
    if any(s in text for s in nonprofit_signals):
        return "nonprofit"

    # STUDIO / GYM — señales fuertes
    studio_signals = [
        "clases ", "horarios", "agenda tu", "reserva tu",
        "instructores", "instructoras", "instructor:",
        "estudio de", "studio de", "reformer", "salón",
        "ven a entrenar", "ven a nuestra",
        # "studio" como palabra suelta (lowercase)
        " studio", "studio ", "indoor cycling", "cycling studio",
        "fitness studio", "yoga studio", "pilates studio",
        " estudio ", " estudio,", " estudio.",
        # Reserva online de clases
        "reserva tu lugar", "agenda tu clase", "book your class",
        # Gimnasios — palabras sueltas
        "gimnasio", " gym ", " gym.", " gym,",
        # Servicios múltiples (lista típica de gym)
        "musculación", "musculacion", "área crossfit", "area crossfit",
        "24/7", "membresía", "membresia",
        # Address/location indicators (gyms/studios always advertise location)
        "📍plaza", "📍c.c", "📍cc ", "📍centro comercial",
        "📍local ", "📍av.", "📍calle", "📍paseo",
        "ubicación:", "ubicacion:",
        # Spa / academia
        "academia de", "academia es", "spa ", " spa,",
    ]
    if any(s in text for s in studio_signals):
        return "studio"

    # COLLECTIVE / FEDERATION — comunidades, federaciones, organizaciones
    collective_strong = [
        "federación", "federacion", "federation",
        "selección nacional", "comunidad de",
        "afiliados a", "afiliados:",
        "asociación de", "asociacion de",
        "club deportivo", "equipo de",
    ]
    if any(s in text for s in collective_strong):
        return "collective"

    # BRAND — señales fuertes (negocio, voz de empresa, productos)
    brand_signals = [
        # E-commerce
        "envíos", "envios", "shipping", "use code", "promo code",
        "código de descuento", "descuento con", "compra en",
        "shop now", "tienda online", "available at",
        "in stock", "marca de", "brand of",
        # Voz de empresa (plural)
        "empresa ", "empresa l", "líder en", "lider en", "negocio",
        "venta de", "vendemos", "comercializamos", "ventas:",
        "distribuidor", "mayorista", "ecommerce",
        "diseñamos", "equipamos", "ofrecemos", "te recibimos",
        "nos dedicamos", "somos una", "somos un",
        # Productos (bio enumera SKUs/categorías)
        "proteína", "proteina", "suplementos", "creatina",
        "multivitam", "preworkout", "pre-workout",
        "maquinaria fitness", "equipo fitness",
    ]
    brand_count = sum(1 for s in brand_signals if s in text)
    if brand_count >= 1:
        return "brand"

    # FOUNDER/business persona (bio menciona "fundador de @X" + handle parece negocio)
    if "fundador de @" in text or "founder of @" in text:
        # Si hay múltiples menciones de cuentas business, probable brand persona
        if text.count("@") >= 2:
            return "brand"

    # COLLECTIVE — multiples menciones de cuentas o lenguaje plural
    if text.count("@") >= 4:
        return "collective"
    collective_signals = [" team ", " equipo ", "co-founders", "co founders",
                          "founders ", "duo de", "somos un grupo"]
    if any(s in text for s in collective_signals):
        return "collective"

    # Default: individual si hay texto, unknown si bio vacio
    if not bio or len(bio.strip()) < 10:
        return "unknown"
    return "individual"


def is_hard_junk(
    *,
    followers: Optional[int],
    is_private: bool = False,
    handle: Optional[str] = None,
    full_name: Optional[str] = None,
    posts_count_recent: Optional[int] = None,
) -> Tuple[bool, str]:
    """Hard junk = basura clara. Se elimina sin revision humana.

    Criterios mas laxos que evaluate_ideal_candidate. Solo cuentas que NUNCA
    deberian estar en el sistema (privadas, < 1K followers, brand obvios, inactivas).
    """
    c = config.IDEAL_CRITERIA

    # Floor de followers — política dura (no se muestra a Lucy).
    # Usa IDEAL_CRITERIA["followers_min"] como piso (actualmente 10K).
    floor = c.get("followers_min", 1_000)
    if followers is not None and followers < floor:
        return True, f"hard junk: < {floor:,} followers (floor)"

    if is_private and c["exclude_private"]:
        return True, "cuenta privada"

    if handle:
        h = handle.lower()
        for kw in c["skip_handle_keywords"]:
            if kw in h:
                return True, f"handle contiene '{kw}' (marca/tienda)"

    if full_name:
        fn = full_name.lower()
        for kw in c["skip_fullname_keywords"]:
            if kw in fn:
                return True, f"nombre contiene '{kw}' (marca/estudio)"

    if posts_count_recent is not None and posts_count_recent < 1:
        return True, "sin posts recientes (cuenta inactiva)"

    return False, "ok"


def evaluate_ideal_candidate(
    *,
    followers: Optional[int],
    following: Optional[int] = None,
    engagement_rate: Optional[float],
    is_private: bool = False,
    is_business: bool = False,
    bio: Optional[str] = None,
    full_name: Optional[str] = None,
    hashtags: Optional[List[str]] = None,
    mentions: Optional[List[str]] = None,
    posts_count_recent: Optional[int] = None,
    avg_likes: Optional[float] = None,
    avg_comments: Optional[float] = None,
    handle: Optional[str] = None,
    days_since_last_post: Optional[int] = None,
) -> Tuple[bool, str]:
    """Returns (is_ideal, reason). Si is_ideal=False, reason explica por que."""
    c = config.IDEAL_CRITERIA

    # Handle blacklist (marcas, tiendas, etc)
    if handle:
        h = handle.lower()
        for kw in c["skip_handle_keywords"]:
            if kw in h:
                return False, f"handle contiene '{kw}' (probable marca/tienda)"

    # Full name blacklist
    if full_name:
        fn = full_name.lower()
        for kw in c["skip_fullname_keywords"]:
            if kw in fn:
                return False, f"nombre contiene '{kw}' (probable marca/estudio)"

    if followers is None:
        return False, "sin datos de followers"
    if followers < c["followers_min"]:
        return False, f"followers {followers:,} < min {c['followers_min']:,}"
    if followers > c["followers_max"]:
        return False, f"followers {followers:,} > max {c['followers_max']:,}"

    if engagement_rate is None:
        return False, "sin ER calculado"

    # ER threshold por tier
    tier = tier_from_followers(followers)
    er_min_tier = c["er_min_by_tier"].get(tier, 0.025)
    if engagement_rate < er_min_tier:
        return False, f"ER {engagement_rate*100:.2f}% < min para tier {tier} ({er_min_tier*100:.1f}%)"
    if engagement_rate > c["er_max"]:
        return False, f"ER {engagement_rate*100:.2f}% > max {c['er_max']*100:.1f}% (bot suspect)"

    if is_private and c["exclude_private"]:
        return False, "cuenta privada"
    if is_business and c["exclude_business_account_unless_creator"]:
        if followers > 100_000:
            return False, "business account grande (probable marca)"

    # Niche match — relajado a 0.3 (la mayor parte de creadoras no llenan keywords completas)
    niche_score = _norm_niche(bio, hashtags, mentions)
    if niche_score < c["min_niche_match_score"]:
        return False, f"niche match bajo ({niche_score:.2f}, min {c['min_niche_match_score']})"

    if posts_count_recent is not None and posts_count_recent < c["min_posts_last_12"]:
        return False, f"solo {posts_count_recent} posts recientes (poco activo)"

    if avg_likes and avg_comments and avg_comments > 0:
        ratio = avg_likes / avg_comments
        if ratio > c["max_likes_to_comments_ratio"]:
            return False, f"likes/comments {ratio:.0f}:1 (sospechoso de bots)"

    # Anti fake-audience: si sigue a casi tanto como la siguen, es sospechoso
    if following and following > 0:
        ratio = followers / following
        if ratio < c["min_follower_following_ratio"]:
            return False, f"followers/following {ratio:.1f}:1 < min {c['min_follower_following_ratio']:.0f}:1 (audiencia inflada)"

    # Recency: tiene que estar publicando activamente
    if days_since_last_post is not None and days_since_last_post > c["max_days_since_last_post"]:
        return False, f"último post hace {days_since_last_post} días (max {c['max_days_since_last_post']})"

    return True, "ok"


# ============================================================
# Predicción de tipo de colaboración recomendado
# ============================================================
COLLAB_TYPE_LABELS = {
    "intercambio":        ":material/swap_horiz: Intercambio simple (producto x contenido)",
    "gifted":             ":material/redeem: PR pack (gifted)",
    "paid_light":         ":material/payments: Pago único Light ($1.5K–5K MXN)",
    "paid_mid":           ":material/attach_money: Pago único Mid ($5K–30K MXN)",
    "paid_hero":          ":material/star: Pago único Hero ($30K+ MXN)",
    "monthly_fee":        ":material/event_repeat: Fee mensual / Embajadora",
    "skip":               ":material/close: No recomendado",
    "no_collab":          ":material/block: No aplica (no es creadora MX individual)",
}


def predict_collab_type(
    *,
    followers: Optional[int],
    engagement_rate: Optional[float],
    tier: Optional[str],
    account_type: Optional[str] = "individual",
    country: Optional[str] = None,
    gender: Optional[str] = None,
    avg_likes: Optional[float] = 0,
    avg_comments: Optional[float] = 0,
    num_posts_in_collab: int = 1,
    multipliers: Optional[dict] = None,
) -> Dict:
    """Recomienda tipo de collab basado en métricas vs benchmarks FelyFit.

    Devuelve dict con type (clave), label friendly, rationale, expected_emv,
    max_cash_investable, recommended_cash.
    """
    # Guards
    if not followers or followers < 1000:
        return {
            "type": "no_collab",
            "label": COLLAB_TYPE_LABELS["no_collab"],
            "rationale": "Audiencia muy pequeña (<1K). No aporta alcance suficiente.",
            "expected_emv": 0, "max_cash_investable": 0, "recommended_cash": 0,
            "tier": tier, "warnings": [],
        }
    if account_type and account_type != "individual":
        return {
            "type": "no_collab",
            "label": COLLAB_TYPE_LABELS["no_collab"],
            "rationale": f"Tipo de cuenta '{account_type}' — no es creadora individual.",
            "expected_emv": 0, "max_cash_investable": 0, "recommended_cash": 0,
            "tier": tier, "warnings": [],
        }
    if country and country != "MX":
        return {
            "type": "no_collab",
            "label": COLLAB_TYPE_LABELS["no_collab"],
            "rationale": f"País: {country}. Fuera del foco geográfico de FelyFit (MX).",
            "expected_emv": 0, "max_cash_investable": 0, "recommended_cash": 0,
            "tier": tier, "warnings": [],
        }

    if not tier:
        tier = tier_from_followers(followers)

    er = engagement_rate or 0
    avg_likes = avg_likes or 0
    avg_comments = avg_comments or 0

    # Expected EMV — usa promedios orgánicos de la creadora
    expected_emv = estimate_expected_emv_from_history(
        tier=tier,
        avg_likes=avg_likes,
        avg_comments=avg_comments,
        num_posts_in_collab=num_posts_in_collab,
        multipliers=multipliers,
    )

    # Max cash investable manteniendo target 3:1
    max_cash = compute_max_cash_investable(
        expected_emv=expected_emv,
        cogs_pieces=config.STANDARD_PR_PACK_COGS_MXN,
        shipping_cost=150,
        target_ratio=config.EMV_TARGET_RATIO,
    )

    warnings = []
    if gender == "male":
        warnings.append("⚠️ Detectada como masculino — FelyFit es brand femenino")

    # Tier-based recommendation (sin código afiliada — FelyFit no comisiona en IG)
    if tier == "nano":  # 1K-10K — solo si se cuela alguna pequeña
        if er >= 0.05:
            t = "intercambio"
            cash = 0
            rationale = (f"Nano con ER muy alto ({er*100:.1f}%). **Intercambio simple**: "
                         "le mandas producto a cambio de contenido específico (1 post + stories). "
                         "Sin código de afiliación, sin pago.")
        elif er >= 0.035:
            t = "gifted"
            cash = 0
            rationale = (f"Nano saludable (ER {er*100:.1f}%). **PR pack gifted** "
                         "sin compromiso obligatorio. Cost = COGS pack ($469).")
        else:
            t = "skip"
            cash = 0
            rationale = f"Nano con ER bajo ({er*100:.1f}%). No vale invertir."

    elif tier == "micro":  # 10K-50K
        if er >= 0.04 and max_cash >= 1500:
            t = "paid_light"
            cash = min(max(1500, int(max_cash * 0.8)), 5000)
            rationale = (f"Micro saludable ({followers:,}f · ER {er*100:.1f}%). "
                         f"**Pago único Light** ${cash:,} MXN + PR pack. "
                         f"Mantiene ratio 3:1. Max teórico: ${max_cash:,.0f}.")
        elif er >= 0.025:
            t = "gifted"
            cash = 0
            rationale = (f"Micro con ER ok ({er*100:.1f}%). **PR pack gifted** "
                         "como starter — si rinde, escalas a paid en próxima collab.")
        else:
            t = "skip"
            cash = 0
            rationale = f"Micro con ER bajo ({er*100:.1f}%). Skip."

    elif tier == "mid":  # 50K-150K
        if er >= 0.025 and max_cash >= 3000:
            t = "paid_mid"
            cash = min(max(3000, int(max_cash * 0.75)), 18000)
            rationale = (f"Mid con buen alcance ({followers:,}f · ER {er*100:.1f}%). "
                         f"**Pago único Mid** ${cash:,} MXN + PR pack. "
                         f"Max teórico: ${max_cash:,.0f}.")
        elif er >= 0.018:
            t = "paid_light"
            cash = min(max(1500, int(max_cash * 0.7)), 7000)
            rationale = (f"Mid pero ER límite ({er*100:.1f}%). **Pago Light** "
                         f"${cash:,} MXN para probar antes de escalar.")
        else:
            t = "gifted"
            cash = 0
            rationale = (f"Mid con ER pobre ({er*100:.1f}%). **PR gifted** "
                         "sin pago — si performa bien, reevaluamos.")

    elif tier == "macro":  # 150K-500K
        if er >= 0.015 and max_cash >= 8000:
            # Considera fee mensual si la creadora ya es regular del nicho
            if er >= 0.025 and followers >= 200_000:
                t = "monthly_fee"
                cash = min(max(15000, int(max_cash * 0.6)), 50000)
                rationale = (f"Macro premium ({followers:,}f · ER {er*100:.1f}%). "
                             f"**Fee mensual / Embajadora** ${cash:,} MXN/mes — "
                             "compromiso de contenido recurrente. Mejor que pago único "
                             "para construir asociación con la marca.")
            else:
                t = "paid_mid"
                cash = min(max(8000, int(max_cash * 0.7)), 45000)
                rationale = (f"Macro con alcance fuerte ({followers:,}f · ER {er*100:.1f}%). "
                             f"**Pago único Mid** ${cash:,} MXN. Max: ${max_cash:,.0f}.")
        elif er >= 0.01:
            t = "paid_light"
            cash = min(max(3000, int(max_cash * 0.6)), 12000)
            rationale = f"Macro pero ER bajo. **Pago Light** ${cash:,} conservador."
        else:
            t = "skip"
            cash = 0
            rationale = f"Macro con ER muy bajo ({er*100:.1f}%). ROI dudoso."

    else:  # mega 500K+
        if er >= 0.01 and max_cash >= 20000:
            t = "paid_hero"
            cash = min(max(20000, int(max_cash * 0.65)), 150000)
            rationale = (f"Mega creator ({followers:,}f). **Pago Hero** ${cash:,} MXN. "
                         f"Negociar contenido extenso (reel + stories + carousel) + "
                         f"exclusividad temporal. Considera evolucionar a fee mensual "
                         f"si la primera collab funciona.")
        elif er >= 0.007:
            t = "paid_mid"
            cash = min(max(8000, int(max_cash * 0.55)), 50000)
            rationale = f"Mega con ER mediocre. **Pago Mid** ${cash:,}."
        else:
            t = "skip"
            cash = 0
            rationale = f"Mega con ER <0.7% — audiencia probablemente comprada."

    return {
        "type": t,
        "label": COLLAB_TYPE_LABELS[t],
        "rationale": rationale,
        "expected_emv": round(expected_emv, 2),
        "max_cash_investable": round(max_cash, 2),
        "recommended_cash": cash,
        "tier": tier,
        "warnings": warnings,
    }


def estimate_expected_emv_from_history(
    *,
    tier: str,
    avg_likes: float,
    avg_comments: float,
    avg_views: float = 0,
    num_posts_in_collab: int = 1,
    multipliers: Optional[dict] = None,
) -> float:
    """Estima EMV de UNA collab futura usando el promedio organico de la creadora.
    Conservador: no asume saves/shares/follows.
    """
    return compute_emv(
        tier=tier,
        num_posts=num_posts_in_collab,
        likes=int(avg_likes * num_posts_in_collab),
        comments=int(avg_comments * num_posts_in_collab),
        views=int(avg_views * num_posts_in_collab),
        multipliers=multipliers,
    )


if __name__ == "__main__":
    # Smoke test
    score, breakdown = compute_fit_score(
        engagement_rate=0.042,
        bio="Yoga teacher in CDMX. Wellness, mindfulness, movimiento.",
        hashtags=["yogamx", "wellnessmx"],
        followers=45_000,
        estimated_city="CDMX",
        avg_likes=1800,
        avg_comments=60,
    )
    print(f"Fit Score: {score}")
    print(f"Breakdown: {json.dumps(breakdown, indent=2)}")

    emv = compute_emv(
        tier="micro",
        num_posts=1,
        likes=4000, comments=80, saves=200, shares=30,
        attributed_followers=150,
    )
    cash_ratio, total_ratio = compute_ratios(
        emv, cash_fee=4000, shipping_cost=180, cogs_pieces=470,
    )
    print(f"\nEMV: ${emv:,.2f} MXN")
    print(f"Cash Ratio:  {cash_ratio:.2f}x")
    print(f"Total Ratio: {total_ratio:.2f}x")

    max_cash = compute_max_cash_investable(
        expected_emv=18_000, shipping_cost=180,
    )
    print(f"\nMax cash investable (EMV $18K esperado, target 3:1): ${max_cash:,.2f} MXN")
