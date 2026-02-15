# Error Handling & Robustness Proposal

## 1. Architecture Overview

The proposed error handling strategy focuses on intercepting failures at the source (API calls in the background thread) and gracefully propagating them to the UI thread for user feedback and state recovery.

### Diagram
```
[Background Thread (Agent)]        [Main Thread (UI)]
       |                                   |
   Try / Except                            |
       |                                   |
   LLM API Call  ----(Fail)---->  Yield "error" Event
       |                                   |
       v                                   v
   (Success)                      _on_message_async
                                           |
                                   1. Show SnackBar (Toast)
                                   2. Remove "Thinking" Bubble
                                   3. Restore User Input
                                   4. Enable "Send" Button
```

## 2. Implementation Details

### A. Backend (`agent.py`)
Wrap the streaming generation loop in a robust `try-except` block to catch specific connectivity and API errors.

**Proposed Logic:**
```python
try:
    stream = client.chat.completions.create(...)
    for chunk in stream:
        # ... process chunk ...
except openai.APIConnectionError:
    yield "error", "Connection to AI server failed. Check your network or settings."
except openai.APIStatusError as e:
    yield "error", f"AI Server returned error {e.status_code}: {e.message}"
except Exception as e:
    yield "error", f"Unexpected error: {str(e)}"
```

### B. Frontend (`ui/tabs/chat.py`)
Enhance `_on_message_async` to handle the `error` event type with state recovery.

**Proposed Logic:**
1.  **Notification:** Use `page.snack_bar` to display the error message non-intrusively.
2.  **State Rollback:**
    *   If a "Thinking..." bubble exists, remove it.
    *   **CRITICAL:** Restore the user's last message to the input field (`self.br_input.value = last_user_message`).
    *   Enable the input field and send button immediately.

## 3. Missing Features & Recommendations

Based on the analysis, the following features are missing and recommended for a "complete" robust experience:

1.  **Connection Status Indicator:**
    *   A small icon (green/red dot) in the header indicating if the LLM provider is reachable.
    *   *Implementation:* A background task that pings `settings.OPENAI_BASE_URL` every 60s.

2.  **Retry Mechanism:**
    *   Instead of just rolling back text, the failed user bubble could have a "Retry" button directly on it.
    *   *Current Proposal:* The "Text Rollback" approach is simpler and effective for now.

3.  **Persistent History:**
    *   Currently, history seems to be in-memory (`self.br_chat_history`). If the app crashes or restarts, context is lost.
    *   *Recommendation:* Save chat history to a JSON/SQLite file on every turn.

4.  **Offline Mode:**
    *   Gracefully disable the "Send" button if the network is detected as down (requires os-level checks).

## 4. Next Steps
If approved, I will implement the Backend `try-except` blocks and the Frontend state rollback logic (Toast + Input Restore).
