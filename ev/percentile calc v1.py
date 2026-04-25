import math
import time
from typing import Any, Dict, List, Optional
import numpy as np

# -----------------------------
# 1. Condition & Size Normalization
# -----------------------------

# Based on official Grailed UI categories
CONDITION_RANK = {
    "new/never worn": 3,
    "gently used": 2,
    "used": 1,
    "very worn": 0,
}

def normalize_condition(raw: str) -> str:
    if not raw: return "used"
    clean = raw.lower().strip()
    if "new" in clean: return "new/never worn"
    if "gently" in clean: return "gently used"
    if "very" in clean: return "very worn"
    return "used"

def parse_size(size: Any) -> Optional[float]:
    """Parses strings like 'US 9.5', '43', or 'M / 10' into 10.0"""
    if size is None: return None
    s = str(size).lower().replace(",", ".")
    tokens = s.replace("/", " ").replace("-", " ").split()
    nums = []
    for tok in tokens:
        try: nums.append(float(tok))
        except ValueError: pass
    return nums[-1] if nums else None

# -----------------------------
# 2. Individual Weighting Components
# -----------------------------

def get_condition_weight(target: str, comp: str, alpha: float = 1.2) -> float:
    t_rank = CONDITION_RANK.get(normalize_condition(target), 1)
    c_rank = CONDITION_RANK.get(normalize_condition(comp), 1)
    return math.exp(-alpha * abs(t_rank - c_rank))

def get_size_weight(target: Any, comp: Any, beta: float = 0.6) -> float:
    t_size = parse_size(target)
    c_size = parse_size(comp)
    if t_size is None or c_size is None: return 0.70
    return math.exp(-beta * abs(t_size - c_size))

def get_recency_weight(sold_unix: int, current_unix: int, gamma: float = 0.005) -> float:
    """Decays weight based on days since sale (approx 0.6x weight at 100 days)"""
    days_ago = max((current_unix - sold_unix) / 86400, 0)
    return math.exp(-gamma * days_ago)

def get_seller_score(seller: Dict) -> float:
    """Weights high-trust professional sellers more as they represent true market peak."""
    revs = seller.get("reviews_count", 0) or 0
    txns = seller.get("transactions_count", 0) or 0
    badges = seller.get("badges", {}) or {}
    
    # Log scaling: 10 vs 100 matters more than 1000 vs 1090
    trust_factor = (math.log1p(revs) / 6.0) + (math.log1p(txns) / 7.0)
    badge_bonus = 0.2 if badges.get("trusted_seller") or badges.get("verified") else 0.0
    
    return 0.8 + (min(trust_factor, 1.0) * 0.2) + badge_bonus

# -----------------------------
# 3. Statistical Core
# -----------------------------

def weighted_percentile(values: List[float], weights: List[float], p: float) -> float:
    """Calculates the weighted p-th percentile."""
    v, w = np.array(values), np.array(weights)
    idx = np.argsort(v)
    v, w = v[idx], w[idx]
    cum_w = np.cumsum(w)
    cutoff = (p / 100.0) * cum_w[-1]
    return float(v[np.searchsorted(cum_w, cutoff)])

def get_effective_n(weights: List[float]) -> float:
    """Kish's Effective Sample Size: measures data quality/density."""
    w = np.array(weights)
    if np.sum(w) == 0: return 0
    return float((np.sum(w)**2) / np.sum(w**2))

# -----------------------------
# 4. The Appraisal Engine
# -----------------------------

def value_listing(row: Dict, scraped_at: int) -> Dict:
    live = row["live_listing"]
    comps = row.get("sold_comparables", [])
    
    # Calculate Live All-In Cost
    live_price = live["price"]["listing_price_usd"]
    live_ship = live["price"]["shipping_price_usd"]
    total_cost = live_price + live_ship

    prices, weights = [], []

    for comp in comps:
        # 1. Hard Filter: Designer must match
        if comp.get("designer", "").lower() != live.get("designer", "").lower():
            continue
        
        # 2. Extract All-In Sold Price
        sold_total = comp["price"]["sold_price_usd"] + comp["price"]["shipping_price_usd"]
        
        # 3. Calculate Aggregate Weight
        w = (
            get_condition_weight(live["condition_raw"], comp["condition_raw"]) *
            get_size_weight(live["size"], comp["size"]) *
            get_recency_weight(comp["sold_at_unix"], scraped_at) *
            get_seller_score(comp["seller"])
        )
        
        if w > 0.01: # Filter out irrelevant noise
            prices.append(sold_total)
            weights.append(w)

    if not prices:
        return {"id": live["id"], "status": "no_data"}

    # Calculate Distribution
    p10 = weighted_percentile(prices, weights, 10)
    p50 = weighted_percentile(prices, weights, 50)
    p90 = weighted_percentile(prices, weights, 90)
    eff_n = get_effective_n(weights)

    # Simple Confidence Logic
    confidence = "low"
    if eff_n > 8: confidence = "medium"
    if eff_n > 15: confidence = "high"

    return {
        "id": live["id"],
        "name": live["name"],
        "cost": total_cost,
        "dist": {
            "q10": round(p10, 2),
            "q50": round(p50, 2),
            "q90": round(p90, 2)
        },
        "metrics": {
            "edge_usd": round(p50 - total_cost, 2),
            "percent_under": round(((p50 - total_cost) / p50) * 100, 1) if p50 > 0 else 0,
            "effective_n": round(eff_n, 1),
            "confidence": confidence
        }
    }

# -----------------------------
# 5. Main Entry Point
# -----------------------------

def process_scrape(data: Dict) -> List[Dict]:
    scraped_at = data["metadata"]["scraped_at_unix"]
    results = []
    for row in data["results"]:
        results.append(value_listing(row, scraped_at))
    return results
