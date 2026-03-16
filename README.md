# 🪦 Backlog Reaper

![Forged on Arch Linux](https://img.shields.io/badge/Forged_on-Arch_Linux-1793d1?style=for-the-badge&logo=arch-linux)
![Compiled for Windows](https://img.shields.io/badge/Compiled_for-Windows-0078D6?style=for-the-badge&logo=windows)
![Local SQLite](https://img.shields.io/badge/Database-Local_SQLite-003B57?style=for-the-badge&logo=sqlite)
![Zero Cloud Telemetry](https://img.shields.io/badge/Privacy-Zero_Cloud_Telemetry-success?style=for-the-badge)

> **Stop staring at a spreadsheet. Summon a Curator Soul to manage your Backlog Debt.**

Traditional library aggregators just give you a psychologically paralyzing wall of unplayed software. **Backlog Reaper** is different. It is a desktop AI companion and ReAct (Reason and Act) agent that securely maps your Steam library, analyzes your playing habits, and actively roasts your digital hoarding. 

Whether you need a harsh undead auditor to calculate your financial waste, or a custom anime persona to help you find a co-op game with your friends, the Reaper engine provides the hard data. The soul you summon dictates the reality.

---

## 🧿 The Reaper's Gaze (Core Experience)
By default, you are bound to **The Reaper**, a dark fantasy entity that acts as an uncompromising auditor of your digital life. 

* **Shame Metrics:** Calculates exact "Life Wasted" metrics, unplayed backlog percentages, and absolute financial waste.
* **Smart Categorization:** Automatically segments your Steam library by status (Unplayed, Bounced, Testing, Completionist).
* **HLTB Integration:** Pulls estimated "How Long To Beat" data to identify low-hanging fruit in your backlog.
* **Interactive Roast Cards:** Delivers dynamic, JSON-powered UI cards (Hoarder, Broke, Casual, Hardcore) that visualize your failures in real-time.

---

## 📜 The Spellbook (Tool Integrations)
The AI doesn't just guess what you should play; it is armed with a ReAct cognitive loop and **20 specialized API tools** to deeply analyze your digital footprint:

* **Local Library Tools:** `vault_search`, `get_library_stats`, `find_similar_games`, `get_achievements`.
* **External Data Tools:** `get_game_details`, `get_community_sentiment` (Scrapes Reddit/4Chan/Steam forums for uncensored opinions), `get_game_news`.
* **Advanced Social & Matchmaking:**   
  * `get_active_friends`: Real-time tracking of who is online and what they are currently playing.
  * `get_friends_who_own`: Batch-optimized API calls to find multiplayer overlap without hitting rate limits.
  * `compare_library_with_friend`: Bypasses Steam privacy filters to distinguish between games your friends are actively playing vs. games they abandoned years ago.

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
* **Hybrid Search Engine:** Combines traditional metadata tag filtering with locally computed, cached vector embeddings for semantic "vibe-based" game discovery.
* **Multi-LLM Support:** Compatible with any OpenAI-formatted endpoint (OpenAI, Google Gemini, Local LLMs via LM Studio/Ollama).
* **True Portability:** Forged on Arch Linux, compiled for Windows. The `.exe` is completely self-contained and creates all necessary directories strictly alongside the executable. No Python environment required for end-users.

---

## 🕯️ The Summoning Ritual (Installation)

1. Download the latest `.exe` release from the [Releases](#) tab.
2. Place the executable in a dedicated folder (e.g., `C:\Games\BacklogReaper`).
3. Run the application. 
4. Complete the **Gatekeeper Ritual** on the first launch by providing your Steam API key and Username.
5. The application will automatically construct your local database, download the HLTB datasets (~100MB), and awaken your chosen companion.

---
*Backlog Reaper: Because your pile of shame isn't going to clear itself.*