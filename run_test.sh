#!/bin/bash
echo "appid|name|playtime_forever|rtime_last_played|approval|average_forever|median_forever|ccu" > pipedGames.txt
echo "730|Counter-Strike: Global Offensive|1000|1678886400|0.9|500|400|500000" >> pipedGames.txt
STEAM_API_KEY="15AC32FF266A554A48B3047DA41EBBDF" OPENAI_API_KEY="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" OPENAI_BASE_URL="https://openrouter.ai/api/v1" OPENAI_MODEL="deepseek/deepseek-r1-0528:free" STEAM_USER="maocide" python BacklogReaper.py
