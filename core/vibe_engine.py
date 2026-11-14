import json
import os
import threading
import time
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
import requests
from sentence_transformers import SentenceTransformer

import core.paths as paths
import core.text_utils as text_utils
import core.vault as vault

STEAM_POPULAR_TAGS_URL = "https://store.steampowered.com/tagdata/populartags/english"
STEAM_TAGS_CACHE_TTL = 7 * 24 * 3600  # 7 days

# Curated gaming jargon/alias table keyed by text_utils.normalize_tag_key(query).
# Prevents literal word overlap (e.g. 'survivor-like' -> 'Survival Horror') while
# mapping community shorthand cleanly to canonical Steam/Vault tags.
TAG_ALIASES: Dict[str, List[str]] = {
    "survivor like": ["Bullet Heaven", "Arena Shooter", "Action Roguelike", "Bullet Hell"],
    "survivors like": ["Bullet Heaven", "Arena Shooter", "Action Roguelike", "Bullet Hell"],
    "vampire survivors like": ["Bullet Heaven", "Arena Shooter", "Action Roguelike", "Bullet Hell"],
    "bullet heaven": ["Bullet Heaven", "Bullet Hell", "Arena Shooter", "Action Roguelike"],
    "deckbuilder": ["Deckbuilding", "Roguelike Deckbuilder", "Card Battler", "Card Game"],
    "deck builder": ["Deckbuilding", "Roguelike Deckbuilder", "Card Battler", "Card Game"],
    "boomer shooter": ["Boomer Shooter", "Retro", "Old School", "Arena Shooter"],
    "soulslike": ["Souls-like", "Dark Fantasy", "Difficult", "Action RPG"],
    "souls like": ["Souls-like", "Dark Fantasy", "Difficult", "Action RPG"],
    "roguelike": ["Roguelike", "Action Roguelike", "Rogue-like", "Traditional Roguelike", "Roguelite"],
    "roguelite": ["Roguelite", "Rogue-lite", "Action Roguelike", "Roguelike"],
    "metroidvania": ["Metroidvania", "Roguevania", "2D Platformer", "Exploration"],
    "immersive sim": ["Immersive Sim", "First-Person", "Stealth", "Choices Matter"],
    "colony sim": ["Colony Sim", "Base-Building", "Management", "Resource Management", "City Builder"],
    "cozy": ["Cozy", "Relaxing", "Wholesome", "Cute", "Casual"],
    "extraction shooter": ["Extraction Shooter", "Looter Shooter", "Tactical", "PvPvE"],
    "crpg": ["CRPG", "Party-Based RPG", "Turn-Based Combat", "Isometric"],
    "jrpg": ["JRPG", "Turn-Based", "Story Rich", "Anime"],
    "shmup": ["Shoot 'Em Up", "Bullet Hell", "Arcade", "Top-Down Shooter"],
    "character action": ["Character Action Game", "Spectacle fighter", "Hack and Slash"],
    "spectacle fighter": ["Spectacle fighter", "Character Action Game", "Hack and Slash"],
    "point and click": ["Point & Click", "Adventure", "Puzzle"],
    "walking sim": ["Walking Simulator", "Atmospheric", "Story Rich", "Exploration"],
    "walking simulator": ["Walking Simulator", "Atmospheric", "Story Rich", "Exploration"],
    "time loop": ["Time Manipulation", "Time Attack", "Loop"],
    "auto battler": ["Auto Battler", "Autobattler", "Strategy", "Tactical"],
    "autobattler": ["Auto Battler", "Autobattler", "Strategy", "Tactical"],
    "twin stick": ["Twin Stick Shooter", "Top-Down Shooter", "Arena Shooter"],
    "hero shooter": ["Hero Shooter", "Class-Based", "Team-Based", "FPS"],
}


class VibeEngine:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(VibeEngine, cls).__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self, cache_file=None):
        if self._initialized:
            return

        base_dir = paths.get_base_dir()
        if cache_file is None:
            cache_file = str(base_dir / "vibe_cache.json")

        self.model_name = 'all-MiniLM-L6-v2'
        self.cache_file = cache_file
        self.tag_cache_file = str(base_dir / "tag_embeddings_cache.json")
        self.steam_tags_cache_file = str(base_dir / "steam_tags_cache.json")
        self.model = None  # Lazy load (don't load until needed)
        self.cache = {}
        self.tag_cache: Dict[str, List[float]] = {}
        self._steam_tags_cache: Optional[List[dict]] = None
        self._title_cache_sig: Optional[Tuple[Tuple[int, str], ...]] = None
        self._title_vecs: Optional[np.ndarray] = None
        self.load_cache()
        self._load_tag_cache()
        self._initialized = True

    @classmethod
    def get_instance(cls):
        """Static access method."""
        if cls._instance is None:
            cls() # Call constructor to create instance
        return cls._instance

    def _load_model(self):
        """Loads the AI model only when we actually search."""
        if self.model is None:
            with self._lock: # Ensure only one thread loads the model
                if self.model is None: # Double-check inside lock
                    print("--- LOADING VIBE MODEL (80MB) ---")
                    try:
                        self.model = SentenceTransformer(self.model_name)
                    except Exception as e:
                        print(f"Error loading Vibe Model: {e}")
                        # Fallback or re-raise depending on strictness.
                        # For now, let's assume it works or fails hard.
                        raise e

    def load_cache(self):
        paths.ensure_dirs()
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r') as f:
                    self.cache = json.load(f)
            except (json.JSONDecodeError, IOError):
                print("Warning: Vibe cache corrupted or unreadable. Starting fresh.")
                self.cache = {}

    def save_cache(self):
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(self.cache, f)
        except IOError as e:
            print(f"Error saving vibe cache: {e}")

    def ingest_library(self):
        """
        Goes through the Vault. If a game isn't vectorized, process it.
        """
        self._load_model()

        # Now we pull the description directly from the Vault DB!
        try:
            games = vault.get_all_games()
        except Exception:
            print("Vault inaccessible for ingestion.")
            return

        dirty = False

        print(f"--- ANALYZING VIBES FOR {len(games)} GAMES ---")

        for game in games:
            appid = str(game['appid'])
            if appid in self.cache: continue

            # Construct the 'Meaning' Text
            # Optimization: Check for None types before join/access
            name = game.get('name', 'Unknown Game')
            tags = game.get('tags', '')
            description = game.get('description', '') or ""

            # Clean up tags (ensure it's a string)
            tags_str = ", ".join(tags) if isinstance(tags, list) else (tags or "")

            # Kill empty games
            if not tags_str and not description:
                continue

            # The weighted string, by repeating we give more weight to the tags, and shorten description that might be marketing
            text_blob = f"Game: {name}. Vibe, Genre, and Keywords: {tags_str}. {tags_str}. Summary: {description[:600]}"

            try:
                vector = self.model.encode(text_blob).tolist()
                self.cache[appid] = vector
                dirty = True
                print(f"Vectorized: {name}")
            except Exception as e:
                print(f"Failed to vectorize {name}: {e}")

        if dirty:
            self.save_cache()
            print("--- VIBE CACHE UPDATED ---")

    def _load_tag_cache(self):
        paths.ensure_dirs()
        if os.path.exists(self.tag_cache_file):
            try:
                with open(self.tag_cache_file, 'r') as f:
                    data = json.load(f)
                    self.tag_cache = data if isinstance(data, dict) else {}
            except (json.JSONDecodeError, IOError):
                self.tag_cache = {}

    def _save_tag_cache(self):
        try:
            with open(self.tag_cache_file, 'w') as f:
                json.dump(self.tag_cache, f)
        except IOError as e:
            print(f"Error saving tag embeddings cache: {e}")

    def _get_tag_vectors(self, tags_list: List[str]) -> Optional[np.ndarray]:
        """Return an L2-normalized float32 matrix (N, D) for `tags_list`, caching misses."""
        if not tags_list:
            return None

        missing = [t for t in tags_list if t not in self.tag_cache]
        if missing:
            self._load_model()
            if not self.model:
                return None
            encoded = self.model.encode(missing, normalize_embeddings=True)
            for tag_str, vec in zip(missing, encoded):
                self.tag_cache[tag_str] = vec.tolist()
            self._save_tag_cache()

        mat = np.asarray([self.tag_cache[t] for t in tags_list], dtype=np.float32)
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return mat / norms

    def _project_onto_vocab(
        self,
        queries: List[str],
        vocab_names: List[str],
        threshold: float = 0.65,
        max_per_tag: int = 4,
        exact_neighbor_threshold: float = 0.70,
    ) -> Dict[str, List[Tuple[str, float]]]:
        """
        Project arbitrary tag queries onto a finite canonical tag vocabulary using:
        1. Exact / hyphen-collapsed match against known tags
        2. Curated jargon alias mapping (`TAG_ALIASES`)
        3. Cosine similarity projection over cached MiniLM embeddings
        """
        if not queries or not vocab_names:
            return {q: [] for q in queries}

        norm_map: Dict[str, List[str]] = {}
        collapsed_map: Dict[str, List[str]] = {}
        for name in vocab_names:
            nkey = text_utils.normalize_tag_key(name)
            ckey = text_utils.collapse_tag_key(name)
            norm_map.setdefault(nkey, []).append(name)
            collapsed_map.setdefault(ckey, []).append(name)

        vocab_vecs = self._get_tag_vectors(vocab_names)
        if vocab_vecs is None:
            return {q: [] for q in queries}

        self._load_model()
        query_vecs = self.model.encode([q.strip() for q in queries], normalize_embeddings=True)

        projected: Dict[str, List[Tuple[str, float]]] = {}
        for q, q_vec in zip(queries, query_vecs):
            q_clean = (q or "").strip()
            if not q_clean:
                continue

            q_norm = text_utils.normalize_tag_key(q_clean)
            q_collapsed = text_utils.collapse_tag_key(q_clean)

            candidates: Dict[str, float] = {}

            # 1. Exact / collapsed match (e.g. 'rogue-like' -> ['Roguelike', 'Rogue-like'])
            exact_hits: List[str] = []
            for hit in norm_map.get(q_norm, []):
                if hit not in exact_hits:
                    exact_hits.append(hit)
            for hit in collapsed_map.get(q_collapsed, []):
                if hit not in exact_hits:
                    exact_hits.append(hit)
            for hit in exact_hits:
                candidates[hit] = 1.0

            # 2. Curated alias lookup matched back into known vocabulary (preserve alias preference order)
            alias_list = TAG_ALIASES.get(q_norm, [])
            for alias_idx, alias_target in enumerate(alias_list):
                alias_score = round(0.98 - (alias_idx * 0.01), 3)
                for hit in norm_map.get(text_utils.normalize_tag_key(alias_target), []):
                    candidates.setdefault(hit, alias_score)
                for hit in collapsed_map.get(text_utils.collapse_tag_key(alias_target), []):
                    candidates.setdefault(hit, alias_score)

            # 3. Cosine projection over finite tag vocabulary
            # Tighter neighbor cutoff when exact tag already exists prevents broad parent drift
            # (e.g. 'Boomer Shooter' -> generic 'Shooter' at 0.66).
            sims = np.dot(vocab_vecs, q_vec)
            semantic_cutoff = exact_neighbor_threshold if exact_hits else threshold
            top_indices = np.argsort(sims)[::-1]
            for idx in top_indices:
                score = float(sims[idx])
                if score < semantic_cutoff:
                    break
                tag_name = vocab_names[idx]
                candidates.setdefault(tag_name, round(score, 3))
                if len(candidates) >= max_per_tag + 2:
                    break

            ranked = sorted(candidates.items(), key=lambda x: (-x[1], x[0]))[:max_per_tag]
            projected[q_clean] = ranked

        return projected

    def resolve_vault_tags(
        self,
        tag_queries: List[str],
        distinct_tags: Optional[List[str]] = None,
        threshold: float = 0.65,
        max_per_tag: int = 4,
    ) -> Tuple[List[Set[str]], Dict[str, List[str]]]:
        """
        Expand each requested tag query independently into a canonical vault tag group.
        Returns `(tag_groups_lowercased, expanded_display_map)`.
        """
        if not tag_queries:
            return [], {}

        vocab = distinct_tags if distinct_tags is not None else vault.get_distinct_tags()
        if not vocab:
            groups = [{t.strip().lower()} for t in tag_queries if (t or "").strip()]
            return groups, {}

        projected = self._project_onto_vocab(
            tag_queries,
            vocab,
            threshold=threshold,
            max_per_tag=max_per_tag,
        )

        groups: List[Set[str]] = []
        expanded_display: Dict[str, List[str]] = {}
        for orig_q in tag_queries:
            q_clean = (orig_q or "").strip()
            if not q_clean:
                continue
            matches = projected.get(q_clean, [])
            names = [name for name, _ in matches]
            expanded_display[q_clean] = names
            if names:
                groups.append({name.lower() for name in names})
            else:
                # Preserve impossible filter token so search yields 0 results rather than dropping constraint
                groups.append({q_clean.lower()})

        return groups, expanded_display

    def get_steam_popular_tags(self, force_refresh: bool = False) -> List[dict]:
        """Fetch and cache Valve's official ~429 Steam tag IDs (`tagdata/populartags/english`)."""
        if self._steam_tags_cache is not None and not force_refresh:
            return self._steam_tags_cache

        stale_tags: List[dict] = []
        if os.path.exists(self.steam_tags_cache_file) and not force_refresh:
            try:
                with open(self.steam_tags_cache_file, 'r') as f:
                    payload = json.load(f)
                stale_tags = payload.get("tags", [])
                fetched_at = payload.get("fetched_at", 0)
                if stale_tags and (time.time() - fetched_at) < STEAM_TAGS_CACHE_TTL:
                    self._steam_tags_cache = stale_tags
                    return stale_tags
            except (json.JSONDecodeError, IOError):
                pass

        try:
            resp = requests.get(STEAM_POPULAR_TAGS_URL, timeout=10)
            if resp.status_code == 200:
                raw_tags = resp.json()
                cleaned = [
                    {"tagid": int(t["tagid"]), "name": str(t["name"])}
                    for t in raw_tags
                    if isinstance(t, dict) and "tagid" in t and "name" in t
                ]
                if cleaned:
                    with open(self.steam_tags_cache_file, 'w') as f:
                        json.dump({"fetched_at": time.time(), "tags": cleaned}, f)
                    self._steam_tags_cache = cleaned
                    return cleaned
        except Exception as e:
            print(f"Warning: Failed to refresh Steam popular tags: {e}")

        self._steam_tags_cache = stale_tags
        return stale_tags

    def resolve_steam_tag_ids(
        self,
        tag_queries: List[str],
        threshold: float = 0.65,
        max_per_tag: int = 2,
    ) -> List[dict]:
        """Resolve arbitrary tag queries into official Steam store tag IDs."""
        if not tag_queries:
            return []

        steam_tags = self.get_steam_popular_tags()
        if not steam_tags:
            return []

        name_to_id = {t["name"]: t["tagid"] for t in steam_tags}
        projected = self._project_onto_vocab(
            tag_queries,
            list(name_to_id.keys()),
            threshold=threshold,
            max_per_tag=max_per_tag,
            exact_neighbor_threshold=0.75,
        )

        resolved: List[dict] = []
        seen_ids: Set[int] = set()
        for q in tag_queries:
            q_clean = (q or "").strip()
            for name, score in projected.get(q_clean, []):
                tid = name_to_id.get(name)
                if tid is not None and tid not in seen_ids:
                    seen_ids.add(tid)
                    resolved.append({"query": q_clean, "tagid": tid, "name": name, "score": score})
        return resolved

    def search_titles(
        self,
        query: str,
        games: List[dict],
        threshold: float = 0.72,
        top_k: int = 5,
    ) -> List[dict]:
        """
        Tier-3 semantic title fallback using normalized title embeddings + sequel-digit guard.
        Only matches titles with similarity >= `threshold` to reject unrelated hallucinations.
        """
        q_norm = text_utils.normalize_title(query, convert_roman=True)
        if not q_norm or not games:
            return []

        self._load_model()
        if not self.model:
            return []

        sig = tuple((int(g.get("appid", 0)), str(g.get("name", ""))) for g in games)
        if self._title_cache_sig != sig or self._title_vecs is None:
            norm_titles = [text_utils.normalize_title(g.get("name", ""), convert_roman=True) or "unknown" for g in games]
            self._title_vecs = np.asarray(
                self.model.encode(norm_titles, normalize_embeddings=True),
                dtype=np.float32,
            )
            self._title_cache_sig = sig

        q_vec = self.model.encode(q_norm, normalize_embeddings=True)
        sims = np.dot(self._title_vecs, q_vec)
        q_nums = text_utils.extract_sequel_numbers(query)

        scored: List[Tuple[float, dict]] = []
        for idx, sim in enumerate(sims):
            raw_score = float(sim)
            game = games[idx]
            c_nums = text_utils.extract_sequel_numbers(game.get("name", ""))
            adj_score = raw_score
            if q_nums and not q_nums.issubset(c_nums):
                adj_score *= 0.75
            elif not q_nums and c_nums:
                adj_score *= 0.90

            if adj_score >= threshold:
                item = game.copy()
                item["title_similarity"] = round(adj_score, 3)
                scored.append((adj_score, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:top_k]]

    def search(
        self,
        user_query,
        top_k=5,
        status: Optional[List[str]] = None,
        hltb_max: Optional[int] = None,
        include_unknown_hltb: bool = False,
    ):
        """
        Finds owned games matching an abstract mood, theme, or vibe description,
        with optional backlog `status` and `hltb_max` filters.
        """
        self._load_model()
        if not self.model:
            return []

        try:
            query_vector = self.model.encode(user_query)
            q_norm = np.linalg.norm(query_vector)
            if q_norm == 0:
                return []

            results = []
            for appid, vector in self.cache.items():
                try:
                    v_norm = np.linalg.norm(vector)
                    if v_norm == 0:
                        continue
                    score = np.dot(query_vector, vector) / (q_norm * v_norm)
                    results.append((appid, float(score)))
                except Exception:
                    continue

            results.sort(key=lambda x: x[1], reverse=True)

            req_status = {s.lower() for s in status} if status else None
            if hltb_max == 0:
                hltb_max = None

            # Batch-fetch vault once when filtering so we don't open hundreds of SQLite handles
            games_by_id = None
            if req_status or hltb_max is not None:
                games_by_id = {str(g["appid"]): g for g in vault.get_all_games()}

            final_picks = []
            for appid, score in results:
                game = games_by_id.get(str(appid)) if games_by_id is not None else vault.get_game_by_appid(int(appid))
                if not game:
                    continue

                game = game.copy()
                game_status = vault.calculate_status(game)
                if req_status and game_status.lower() not in req_status:
                    continue

                if hltb_max is not None:
                    main_mins = game.get("hltb_main") or 0
                    if main_mins == 0:
                        if not include_unknown_hltb:
                            continue
                    elif main_mins > hltb_max * 60:
                        continue

                game["status"] = game_status
                game["vibe_match"] = f"{int(score * 100)}%"
                final_picks.append(game)
                if len(final_picks) >= top_k:
                    break

            return final_picks

        except Exception as e:
            print(f"Vibe Search Error: {e}")
            return []

    def get_batch_scores(self, query_text, appids):
        """
        Returns a dictionary {appid: score} for a specific list of games vs the query.
        Used for Hybrid sorting.
        """
        self._load_model()
        if not self.model: return {}

        query_vector = self.model.encode(query_text)
        scores = {}

        for appid in appids:
            str_id = str(appid)
            if str_id in self.cache:
                vector = self.cache[str_id]
                # Fast Cosine Similarity
                score = np.dot(query_vector, vector) / (np.linalg.norm(query_vector) * np.linalg.norm(vector))
                scores[appid] = float(score)
            else:
                scores[appid] = 0.0

        return scores