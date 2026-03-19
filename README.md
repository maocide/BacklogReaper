
<p align="left">
  <img src="docs/images/backlog_reaper_banner.png" width="700" alt="🪦 Backlog Reaper">
</p>

![Forged on Arch Linux](https://img.shields.io/badge/Forged_on-Arch_Linux-1793d1?style=for-the-badge&logo=arch-linux)
![Compiled for Windows](https://img.shields.io/badge/Compiled_for-Windows-0078D6?style=for-the-badge&logo=windows)
![Local SQLite](https://img.shields.io/badge/Database-Local_SQLite-003B57?style=for-the-badge&logo=sqlite)
![Zero Cloud Telemetry](https://img.shields.io/badge/Privacy-Zero_Cloud_Telemetry-success?style=for-the-badge)

> **Stop staring at a spreadsheet. Summon a Curator Soul to manage your Backlog Debt.**

Traditional library aggregators just give you a psychologically paralyzing wall of unplayed software. **Backlog Reaper** is different. It is a desktop AI companion and ReAct (Reason and Act) agent that securely maps your Steam library, analyzes your playing habits, and actively roasts your digital hoarding. 

Whether you need a harsh undead auditor to calculate your financial waste, or a custom anime persona to help you find a co-op game with your friends, the Reaper engine provides the hard data. The soul you summon dictates the reality.

<video src="./docs/videos/hero_loop.mp4" autoplay loop muted playsinline width="100%"></video>  

---
<details>
<summary>💀 View full transcript & tool logs</summary>

**maocide**: Roast my Steam library, Reaper. I bet my backlog isn't even that bad.

**Reaper's Cognitive Loop:**
* `get_library_stats` - `Sifting through the digital graveyard of maocide's gaming sins...`
* `vault_search | {"sort_by": "recent"}` - `Peering into the recent digital footprints of this mortal...`
* `get_user_tags` - `Analyzing the genre rot that festers in this digital tomb...`

**Reaper:** **"maocide"**... What a name. Sounds like a discount brand of pesticide mixed with a failed edgelord phase. But let's get to the real poison here - your digital hoarding problem.

Oh, you think your backlog "isn't even that bad"? Let me laugh with the hollow echo of a thousand unplayed Steam keys. **694 games**. That's not a library, that's a cry for help. **345 of them untouched** - a 64% shame percentage that would make even the most dedicated hoarder blush. You've spent enough money to feed a small village, yet half your collection gathers more dust than my ancient bones.

But wait... there's a glimmer of something here. 14,303 hours total? That's... actually respectable. You've spent nearly two years of continuous gaming. The problem is you've spread yourself thinner than a ghost's whisper across 694 titles. Your average playtime of 20.6 hours suggests you're a chronic "starter" - you get the dopamine hit of a new game, play it for a weekend, then abandon it like a bad habit.

Your recent activity tells a story of a gamer with decent taste but zero commitment: SYNTHETIK 2, Slay the Spire, Anger Foot, Devil Daggers... all quality games, all played for exactly long enough to get the gist before you move on. You bounce between roguelites and boomer shooters like a pinball with ADHD.

The real tragedy? You own **236 indie games** but have only spent **776 hours** across all of them. That's barely 3 hours per indie title. You're treating these lovingly crafted experiences like disposable tissues. And don't get me started on the **122 anime games** - we both know what kind of "plot" those have, and it's not the literary kind.

But here's the most damning evidence of your gaming sin: you have **3,040 hours** in eSports titles but only **8 games** in that category. That means you're one of those people who plays ONE competitive game obsessively while ignoring the hundreds of other games you paid for. The definition of insanity.

```json
[
  {
    "name": "The Chronic Starter",
    "bg_theme": "HOARDER",
    "appid": "ROAST",
    "Games_Owned": "694",
    "Unplayed_Graveyard": "345",
    "Shame_Percentage": "64%",
    "Life_Wasted": "14,303 Hours",
    "Completion_Rate": "20%",
    "Indie_Disrespect": "3.3h avg",
    "comment": "You buy games like groceries, play them like demos."
  }
]
```

The good news? At least you're not playing walking simulators. The bad news? You're a digital dragon sitting on a pile of gold you'll never spend. Pick five games. Finish them. Then come back to me, and maybe - just maybe - I won't judge you as harshly. Until then, you're just another soul in my backlog purgatory.

</details>

---

## 🧿 The Reaper's Gaze (Core Experience)
By default, you are bound to **The Reaper**, a dark fantasy entity that acts as an uncompromising auditor of your digital life. 

* **Shame Metrics:** Calculates exact "Life Wasted" metrics, unplayed backlog percentages, and absolute financial waste.
* **Smart Categorization:** Automatically segments your Steam library by status (Unplayed, Bounced, Testing, Completionist).
* **HLTB Integration:** Pulls estimated "How Long To Beat" data to identify low-hanging fruit in your backlog.
* **Interactive Roast Cards:** Delivers dynamic, JSON-powered UI cards (Hoarder, Broke, Casual, Hardcore) that visualize your failures in real-time.

---

## 📜 The Spellbook (Tool Integrations)
The AI doesn't just guess what you should play; it is armed with a ReAct cognitive loop and **20 specialized API tools** to deeply analyze your digital footprint.

**Local Library Intelligence**
* `vault_search`: Advanced filtering by tags, playtime, review scores, and status.
* `search_by_vibe`: Mood/emotion-based game discovery using semantic vector embeddings.
* `find_similar_games`: Hybrid tag and vector similarity search.
* `get_library_stats` & `get_user_tags`: Aggregate shame percentages, completion rates, and genre habits.
* `get_achievements`: Track progress and identify "easiest missing" completions.

**External Data & Community**
* `get_game_details` & `search_steam_store`: Deep dive into prices to find better deals, HLTB times to get your completion, and store browsing.
* `get_community_sentiment` & `get_reviews`: Scrape Reddit, 4chan and Steam forums for uncensored player opinions. Fetch and analyze Steam Store user reviews to integrate real community feedback.
* `get_game_news`: Fetch the latest patch notes and official updates from Steam.

**Advanced Social & Matchmaking**
* `get_active_friends`: Real-time tracking of who is online and exactly what they are playing.
* `get_friends_who_own`: Batch-optimized API calls to find multiplayer overlap without hitting Steam's rate limits.
* `compare_library_with_friend`: Compares owned games distinguishing between games your friends are actively playing versus titles they abandoned years ago.

**Research & Web Discovery**
* `web_search` & `get_webpage`: Live DuckDuckGo searching with automatic AI article summarization.
* `get_user_wishlist`: Browse wishlisted games, find sales, and integrate them with other tools.    

*...and several other utility incantations to power these main functions*

---

## 🎭 The BYOW System (Bring Your Own Waifu / Persona)
Tired of the edgy skeleton guy? The Backlog Reaper engine natively supports standard PNG/JSON character cards (TavernAI, Silly Tavern format). The engine provides the data; your custom character card completely dictates the vibe.

**The Aggressive Social Auditor (e.g., Asuka)**
> *"Anta baka?! You want to play CS2 with Ash? I just checked his real-time status and he hasn't logged in for three weeks, and when he did, he carried you. Go finish your single-player games instead of waiting to be carried."*

**The Supportive Co-op Partner (e.g., Zero Two)**
> *"Darling! You have so many amazing indie games we haven't even touched yet! I see you bought Stardew Valley three years ago... why don't you boot it up tonight so we can relax?"*

---

## 🩻 The Forbidden Gears (Architecture & Privacy)
Backlog Reaper is built for power users who demand data sovereignty and highly optimized architectures.

* **100% Local Data:** Your entire library is securely mapped to a local `backlog_vault.db` SQLite database. No AppData bloat, no cloud uploads, no telemetry.
* **Hybrid Search Engine:** Combines traditional metadata tag filtering, Jaccard similarity matching, with locally computed, cached vector embeddings for semantic "vibe-based" game discovery.
* **Multi-LLM Support:** Compatible with any OpenAI-formatted endpoint (OpenAI, Google Gemini, Local LLMs via LM Studio/Ollama).
* **True Portability:** Forged on Arch Linux, compiled for Windows. The `.exe` is completely self-contained and creates all necessary directories strictly alongside the executable. No Python environment required for end-users.

---

## 🕯️ The Summoning Ritual (Installation)

1. Download the latest `.exe` release from the [Releases](#) tab.
2. Place the executable in a dedicated folder (e.g., `C:\Games\BacklogReaper`).
3. Run the application. 
4. Complete the **Gatekeeper Ritual** on the first launch by providing your Steam API key and Username.
5. The application will automatically construct your local database, download the HLTB datasets (~100MB), and awaken your chosen companion.  

### 🔑 Awakening your chosen companion (API Configuration)
Backlog Reaper requires two keys to function: your Steam data, and an LLM to serve as the reasoning engine. The app is completely model-agnostic and uses standard OpenAI-formatted endpoints.

Navigate to the **Settings** tab to configure your entity's brain:

**Option A: Cloud Models (OpenAI / OpenRouter / etc.)**
* **API Key:** Paste your standard API key.
* **Base URL:** Leave blank for default OpenAI, or set to your provider's endpoint (e.g., `https://openrouter.ai/api/v1`).
* **Model Name:** e.g., `gpt-4o`, `gpt-4-turbo`.

**Option B: Local Models (LM Studio / Ollama)**
Keep your data 100% local by pointing the Reaper to your own hardware.
* **API Key:** Enter `lm-studio` or `ollama` (or any dummy text).
* **Base URL:** Enter your local server address (e.g., `http://localhost:1234/v1` for LM Studio).
* **Model Name:** Enter the exact name of the loaded local model.

---
*Backlog Reaper: Because your pile of shame isn't going to clear itself.*