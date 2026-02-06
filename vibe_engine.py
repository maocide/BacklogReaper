import numpy as np
from sentence_transformers import SentenceTransformer
import os
import json
import vault


class VibeEngine:
    def __init__(self, cache_file="vibe_cache.json"):
        self.model_name = 'all-MiniLM-L6-v2'
        self.cache_file = cache_file
        self.model = None  # Lazy load (don't load until needed)
        self.cache = {}
        self.load_cache()

    def _load_model(self):
        """Loads the AI model only when we actually search."""
        if self.model is None:
            print("--- LOADING VIBE MODEL (80MB) ---")
            self.model = SentenceTransformer(self.model_name)

    def load_cache(self):
        if os.path.exists(self.cache_file):
            with open(self.cache_file, 'r') as f:
                self.cache = json.load(f)

    def save_cache(self):
        with open(self.cache_file, 'w') as f:
            json.dump(self.cache, f)

    def ingest_library(self):
        """
        Goes through the Vault. If a game isn't vectorized, process it.
        """
        self._load_model()

        # Now we pull the description directly from the Vault DB!
        games = vault.get_all_games()
        dirty = False

        print(f"--- ANALYZING VIBES FOR {len(games)} GAMES ---")

        for game in games:
            appid = str(game['appid'])
            if appid in self.cache: continue

            # Construct the 'Meaning' Text
            # Combine title, tags, and description for the best "Vibe"
            text_blob = f"{game['name']}. {', '.join(game.get('tags', []))}. {game.get('description', '')}"

            vector = self.model.encode(text_blob).tolist()
            self.cache[appid] = vector
            dirty = True

            print(f"Vectorized: {game['name']}")

        if dirty:
            self.save_cache()
            print("--- VIBE CACHE UPDATED ---")

    def search(self, user_query, top_k=5):
        """
        The Magic. Finds games that match the 'feeling' of the query.
        """
        self._load_model()

        # 1. Turn user query into numbers (e.g., "Sad dystopian cyberpunk")
        query_vector = self.model.encode(user_query)

        results = []

        # 2. Compare against every game in the vault
        for appid, vector in self.cache.items():
            # Cosine Similarity (Dot product for normalized vectors)
            score = np.dot(query_vector, vector) / (np.linalg.norm(query_vector) * np.linalg.norm(vector))
            results.append((appid, score))

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