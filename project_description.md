Topic: Backlog Reaper
Identity & Purpose:
- An interactive ReAct agent application featuring a "Reaper" persona that roasts the user's backlog.
- Primary function is to provide game data to the agent. Download a game library into curated datasets using a local SQLite database ('The Vault') and multiple APIs. All these data are provided to the agent with functions, so it can discuss backlog and gaming habits with the user.
- Voice/personality is injected via 'action_description' tool calls and displayed as "Dark Whispers" (internal monologue) in the UI.

Core Technology & Architecture:
- GUI: Built with Flet (Python) v0.80+. Refactored to OOP pattern (Character/ChatHistory classes) (Feb 19, 2026).
- Rendering Engine: Implements a custom "Game Loop" rendering thread (50ms heartbeat) to manage UI state and prevent Flet async race conditions (Feb 19, 2026).
- Backend: Modular system; agent connects to LLM APIs (DeepSeek/Ollama) and to tools provided via back end modules.
- Data Layer: SQLite ('backlog_vault.db') for metadata, game library; JSON-based save/load system for individual character chat history (Feb 20, 2026).
- Parallelization: Uses `concurrent.futures` for efficient, non-blocking scraping and API calls.

Key Features:
- Tools: Robust suite of Python functions including preseeded HLTB (Kaggle dataset), CheapShark API, Web Search (DuckDuckGo), Steam API/Scrapers, and Community Sentiment analysis.
- The Vault: Persists user data and game metadata to reduce API dependency and enable offline analysis.
- Internet Vision: Multi-threaded scraping (Steam, 4chan, Reddit) for sentiment analysis and news retrieval.
- Vibe Search: Semantic search engine allowing users to find games by mood using vector embeddings (SentenceTransformers) and Jaccard similarity.
- Chat Background: Magic circle ("THE LEDGER IS OPEN") with "GIT GUD" runes.
- Dynamic Roast Card/Game Cards: Generates a card sharable as image summarizing user failures; Also presents games with cards enriched by game art; utilizes stylized backgrounds and fonts to make a flet stack.
- Analytics Dashboard: Visualizes "Backlog Debt" via horizontal charts and progress bars (Feb 21, 2026).
- Friend Comparison: Tool allowing the Reaper to check which friends own a specific game.
- Session Management: JSON-based save/load per character; supports clearing chat history w/ confirmation.

UI/UX Design:
- Aesthetic: "Grimoire/RPG" theme featuring a dark grey base (#050505) with Gold/Orange accents (#D4A237) and sticky headers.
- Avatar: Reaper reading a scroll; frames removed for a looming effect.
- Components: "Mana-blue" gradient progress bars with bronze borders; stylized chat bubbles; smart autoscroll with "Just-in-Time" data sync indicators.
- Status Colors: Game statuses (Completionist, Abandoned, Testing) mapped to Diablo-style rarity colors (Grey to Legendary).
- Event Handling: Fixed UI chokes via dedicated rendering thread (Feb 19, 2026).

Timeline & Milestones:
- 2025-06: Core functionality establishing Steam data fetching.
- 2025-12-29: Implementation of 'The Vault'.
- 2026-01-22: Launch of Analytics Dashboard and Vibe Search.
- 2026-02-17: Fixed scroll event performance bug; implemented Diablo-style status colors.
- 2026-02-18: Added "Summoning Circle" background elements.
- 2026-02-19: Major Refactor (OOP) + Implementation of Game-Loop Rendering Thread to fix UI text scrambling.
- 2026-02-21: Implementation of JSON Save/Load system, Horizontal Charts, and Mana-Gradient visuals.
- 2026-02-23: Standardization of Tool Returns (Lists, Absolute Timestamps, Error Dicts) and implementation of "Unwrap" optimization for token efficiency.
