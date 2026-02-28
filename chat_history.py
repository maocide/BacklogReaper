import json
import copy
import os
import traceback
import tiktoken

from ai_tools import aiCall
import agent_tools

class ChatHistory:
    def __init__(self, character_name="Reaper"):
        self.messages = []
        self.character_name = character_name
        self.max_tokens = 24000
        self.target_tokens = 18000

    def _load_character(self, character):
        """
        Loads the character's system prompt into the history.
        Updates the first message if it's a system prompt, or inserts it.
        """
        self.character_name = character.name
        system_prompt = character.get_system_prompt()
        system_message = {"role": "system", "content": system_prompt}

        if not self.messages:
            self.messages.append(system_message)
        elif self.messages[0].get("role") == "system":
            self.messages[0] = system_message
        else:
            self.messages.insert(0, system_message)

    def add_message(self, role, content, **kwargs):
        msg = {"role": role, "content": content}
        # Filter None values to keep it clean, though OpenAI handles some
        if content is None:
             msg["content"] = None

        msg.update(kwargs)
        self.messages.append(msg)

    def add_user_message(self, content):
        self.add_message("user", content)
        return self.clean_history() # Gets token count for summarization back

    def get_history(self):
        return self.messages

    def reset_history(self):
        self.messages = self.messages[:1]

    def get_chat_length(self):
        """
        Returns the length of the chat history without system prompt.
        :return:
        """
        if not self.messages:
            return 0
        else:
            return len(self.messages)-1

    def clean_history(self):
        """
        Manages context window by summarizing old history based on tokens.
        """
        history = self.messages
        if len(history) <= 2: return 0, 0

        working_history = copy.deepcopy(history)
        system_prompt = working_history[0]
        conversation = working_history[1:]  # Everything else
        summary_output_tokens = 0
        summary_input_tokens = 0

        try:
            encoding = tiktoken.get_encoding("cl100k_base")
        except Exception as e:
            print(f"Error loading tiktoken encoding: {e}")
            return 0, 0

        # Count tokens for all messages
        total_tokens = 0
        for msg in working_history:
            total_tokens += len(encoding.encode(json.dumps(msg), allowed_special="all"))

        if total_tokens <= self.max_tokens:
            return 0, 0

        # Need to truncate. Work backwards from the end to find the cutoff point
        # that fits within target_tokens.
        
        # System prompt is always included, subtract its tokens from target
        sys_tokens = len(encoding.encode(json.dumps(system_prompt), allowed_special="all"))
        budget = self.target_tokens - sys_tokens
        
        cutoff_index = len(conversation)
        accumulated_tokens = 0
        
        for i in range(len(conversation) - 1, -1, -1):
            msg = conversation[i]
            msg_tokens = len(encoding.encode(json.dumps(msg), allowed_special="all"))
            
            if accumulated_tokens + msg_tokens > budget:
                # We've reached the limit
                cutoff_index = i + 1
                break
            
            accumulated_tokens += msg_tokens
            cutoff_index = i
            
        # Ensure we don't cut everything if a single message is huge
        if cutoff_index >= len(conversation):
            cutoff_index = len(conversation) - 1

        # Initial rough slice
        recent_context = conversation[cutoff_index:]
        old_context = conversation[:cutoff_index]

        final_history = [system_prompt]



        # HEALING THE CUT
        while old_context:
            first_recent = recent_context[0]

            if first_recent.get('role') == 'tool':
                if old_context:
                    recent_context.insert(0, old_context.pop())
                continue

            last_old = old_context[-1]
            if last_old.get('role') == 'assistant' and 'tool_calls' in last_old:
                if old_context:
                    recent_context.insert(0, old_context.pop())
                continue

            break

        # Summarization
        if len(old_context) > 0:
            print("Summarizing history...")

            prev_summary = ""
            msgs_to_summarize = []

            for msg in old_context:
                content = msg.get('content', '')
                if msg.get('role') == 'system' and "[PREVIOUS CONVERSATION SUMMARY:" in str(content):
                    prev_summary = content
                else:
                    msgs_to_summarize.append(msg)

            if not msgs_to_summarize:
                final_history.extend(recent_context)
                self.messages = final_history
                return

            summary_instruction_template = agent_tools.get_summary_instruction()
            summary_request = summary_instruction_template.format(
                prev_summary=prev_summary,
                json_msgs=json.dumps(msgs_to_summarize)
            )

            try:
                print(f"Tokens: {total_tokens} --> TRIGGERED SUMMARIZATION")
                new_summary = aiCall(summary_request, "You are a Summarizer.")

                final_history.append({
                    "role": "system",
                    "content": f"[PREVIOUS CONVERSATION SUMMARY: {new_summary}]"
                })

                summary_output_tokens = len(encoding.encode(new_summary, allowed_special="all"))
                summary_input_tokens = len(encoding.encode(summary_request, allowed_special="all"))

            except Exception as e:
                print(f"Summarization failed: {e}")
                final_history.extend(old_context)
        else:
            final_history.extend(old_context)

        final_history.extend(recent_context)
        self.messages = final_history

        return summary_input_tokens, summary_output_tokens

    def save(self):
        # Ensure the data directory exists
        os.makedirs("data/chats", exist_ok=True)

        file_path = f"data/chats/{self.character_name.lower()}_history.json"

        data = {
            "character": self.character_name,
            "messages": [msg for msg in self.messages]
        }

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

    def load(self, character):
        self._load_character(character)  # Ensures we have name
        file_path = f"data/chats/{self.character_name.lower()}_history.json"

        try:
            json_loaded = json.load(open(file_path))
            self.messages = json_loaded["messages"]
            self._load_character(character) # Overwrites system prompt with current char
        except Exception as e:
            #traceback.print_exc()
            print(f"Failed to load data from {file_path}: {e}")

    # List-like access compatibility
    def append(self, message):
        self.messages.append(message)

    def pop(self, index=-1):
        return self.messages.pop(index)

    def __getitem__(self, index):
         return self.messages[index]

    def __len__(self):
        return len(self.messages)
