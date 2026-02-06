import numpy as np
from sentence_transformers import SentenceTransformer
import os
import json
import vault
import threading

class VibeEngine:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(VibeEngine, cls).__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self, cache_file="vibe_cache.json"):
        if self._initialized:
            return

        self.model_name = 'all-MiniLM-L6-v2'
        self.cache_file = cache_file
        self.model = None  # Lazy load (don't load until needed)
        self.cache = {}
        self.load_cache()
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
            # Ensure tags is a string, sometimes it might be None or list depending on Vault evolution
            if isinstance(tags, list):
                tags_str = ", ".join(tags)
            elif isinstance(tags, str):
                tags_str = tags
            else:
                tags_str = ""

            description = game.get('description', '') or ""

            # Combine: Title + Tags + Description
            text_blob = f"{name}. {tags_str}. {description}"

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

    def search(self, user_query, top_k=5):
        """
        The Magic. Finds games that match the 'feeling' of the query.
        """
        self._load_model()
        if not self.model: return []

        try:
            # 1. Turn user query into numbers (e.g., "Sad dystopian cyberpunk")
            query_vector = self.model.encode(user_query)

            results = []

            # 2. Compare against every game in the vault
            for appid, vector in self.cache.items():
                try:
                    # Cosine Similarity (Dot product for normalized vectors)
                    # Note: SentenceTransformer outputs normalized vectors usually, but explicit norm is safer
                    score = np.dot(query_vector, vector) / (np.linalg.norm(query_vector) * np.linalg.norm(vector))
                    results.append((appid, score))
                except Exception:
                    continue

            # 3. Sort by best match
            results.sort(key=lambda x: x[1], reverse=True)

            # 4. Fetch actual game data for the top K
            final_picks = []
            for appid, score in results[:top_k]:
                game = vault.get_game_by_appid(int(appid))
                if game:
                    # Add the 'vibe_score' so the Agent knows how confident we are
                    game['vibe_match'] = f"{int(score * 100)}%"
                    final_picks.append(game)

            return final_picks

        except Exception as e:
            print(f"Vibe Search Error: {e}")
            return []
