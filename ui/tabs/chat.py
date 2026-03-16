import random
import json
import threading
import traceback
import uuid
import asyncio
import queue
import flet as ft
import agent
import startup
import vault
import settings
from character_manager import CharacterManager, Character
import paths
import game_intelligence
from vibe_engine import VibeEngine
import styles
from chat_history import ChatHistory

import ui.utils
from ui.widgets.chat_bubble import ReaperChatBubble
from ui.widgets.game_card import GameCard
from ui.widgets.styled_inputs import GrimoireTextField, GrimoireProgressBar, GlowingChatInput, GrimoireButton


class ReaperChatView(ft.Container):
    def __init__(self):
        super().__init__()
        self.confirm_dialog = None
        self.expand = True
        self.padding = ft.Padding(0, 5, 5, 10)

        # Initialize ChatHistory and Agent
        self.chat_history = ChatHistory()
        self.character = None
        self.agent = agent.Agent()

        self.br_chat_list = ft.Ref[ft.ListView]()
        self.br_input = ft.Ref[ft.TextField]()
        self.br_status = ft.Ref[ft.Text]()
        self.br_token_count = ft.Ref[ft.Text]()
        self.br_btn_send = ft.Ref[ft.IconButton]()
        self.br_btn_stop = ft.Ref[ft.IconButton]()
        self.br_empty_state = ft.Ref[ft.Container]()
        self.br_empty_state_name = ft.Ref[ft.Text]()

        # Threading
        self.current_run_id = None
        self.current_stop_event = None
        self.current_streaming_bubble = None  # Track the active streaming bubble control
        self.stream_queue = queue.Queue()

        self.user_portrait_url = None

        self.current_scroll_offset = 0
        self.max_scroll_extent = 0
        self.stick_to_bottom = True
        self.last_scroll_pixels = None
        self.last_auto_scroll_time = 0
        self.max_chat_bubbles = 50  # Limit visible bubbles to prevent UI lag/leaks

        self.stream_active = False

        # State for streaming
        self.session_input_tokens = 0
        self.session_output_tokens = 0

        self.stream_state = {
            "status_text": None,
            "agent_markdown": None,
            "reasoning_view": None,
            "reasoning_buffer": "",
            "previous_was_tool": False,
            "first_text": True,
            "reasoning_container_ref": None,
            "needs_update": False
        }

        self.prompt_chips_row = ft.Row(
            alignment=ft.MainAxisAlignment.CENTER,
            wrap=True
        )

        self.content = ft.Column([
            ft.Row([
                ft.Text("Reaper Chat", theme_style=ft.TextThemeStyle.HEADLINE_MEDIUM, expand=True, font_family=styles.FONT_HEADING),
                ft.IconButton(
                    icon=ft.Icons.DELETE_OUTLINE,
                    tooltip="Wipe Ledger",
                    on_click=self.prompt_clear_chat
                ),
                ft.IconButton(icon=ft.Icons.COPY, tooltip="Copy Chat History", on_click=self.copy_chat_history),
            ]),
            ft.Container(
                expand=True,
                padding=0,
                content=ft.Stack(
                    controls=[
                        # Chat List (Transparent overlay)
                        ft.SelectionArea(
                            content=ft.ListView(
                                ref=self.br_chat_list,
                                expand=True,
                                spacing=10,
                                auto_scroll=False,
                                reverse=True, # Newest items at bottom (index 0)
                            ),
                            # Ensure SelectionArea fills the Stack to allow proper scrolling constraints
                            expand=True
                        ),
                        # Empty state controls and bg
                        self._build_empty_state(),
                    ],
                    expand=True,
                )
            ),
            ft.Row([
                ft.Text(ref=self.br_status, value="Ready", color=styles.COLOR_TEXT_SECONDARY, size=12, expand=True),
                ft.Row([
                    ft.Icon(ft.Icons.MEMORY, size=18, color=styles.COLOR_SYSTEM_LOG),
                    ft.Text(ref=self.br_token_count, value="In: 0 Out: 0", color=styles.COLOR_SYSTEM_LOG, size=12, font_family=styles.STYLE_MONOSPACE)
                ], spacing=4, alignment=ft.MainAxisAlignment.END)
            ]),
            ft.Row([
                GlowingChatInput(
                    ref=self.br_input,
                    hint_text="Consult the Reaper...",
                    expand=True,
                    multiline=True,
                    shift_enter=True,
                    on_submit=self.send_message,
                    #label_style=ft.TextStyle(italic=True, color=styles.COLOR_ACCENT_DIM)
                ),
                ft.IconButton(ref=self.br_btn_send, icon=ft.Icons.SEND, tooltip="Consult", icon_color=styles.COLOR_TEXT_GOLD, on_click=self.send_message),
                ft.IconButton(ref=self.br_btn_stop, icon=ft.Icons.STOP_CIRCLE_OUTLINED, icon_color=styles.COLOR_TEXT_GOLD, on_click=self.stop, visible=False),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        ])

    def did_mount(self):
        # Initialize Character
        self._initialize_character()

        # Reload chat history
        self._reload_chat_from_history()

    def will_unmount(self):
        # Stop any active stream if unmounting
        if self.current_stop_event:
            self.current_stop_event.set()
        self.stream_active = False

    def _initialize_character(self):
        current_settings = settings.load_settings()
        char_name = current_settings.get("CHARACTER", "Reaper")
        self.character = CharacterManager.load_character(char_name)
        if not self.character:
             self.character = Character.default()
        self.chat_history.load(self.character)

        # Update hint text
        if self.br_input.current:
            if self.character.name == "Reaper":
                self.br_input.current.hint_text = "Consult the Reaper..."
            else:
                self.br_input.current.hint_text = f"Consult {self.character.name}..."
            self.br_input.current.update()

    def _prefetch_avatar(self):
        try:

            # Fetch to update or set
            url = game_intelligence.get_steam_avatar(settings.STEAM_USER)

            # If we got a valid URL that is different from what we have
            if url and url != self.user_portrait_url or not self.user_portrait_url:
                self.user_portrait_url = url
                settings.STEAM_PROFILE_PIC = url # Cache it globally

                # Update ui and bubbles
                self._update_avatar_in_chat()

        except Exception as e:
            print(f"Error fetching avatar: {e}")

    def _update_avatar_in_chat(self):
        # Retroactively update any user bubbles already on the screen
        if self.br_chat_list.current and self.br_chat_list.current.page:
            for ctrl in self.br_chat_list.current.controls:
                # Check if this control is a user chat bubble
                if getattr(ctrl, "is_user", False) and hasattr(ctrl, "avatar_content"):
                    ctrl.set_avatar(self.user_portrait_url)
                    # Safely update just the avatar container, not the whole bubble
                    self.page.run_task(ui.utils.smart_update, ctrl.avatar_content)

    def _reload_chat_from_history(self):
        self.br_chat_list.current.controls.clear()
        if self.chat_history.get_chat_length():
            self.hide_background()

            # We need to build the list in reverse order (newest first)
            # Or build normally and then reverse the controls list.
            # Let's build normally for logic simplicity, then reverse.
            controls_to_add = []

            last_role = ""
            state = {"is_user": True, "avatar_path": None, "content": ""}

            for i, message in enumerate(self.chat_history.messages):
                role = message.get('role', "")
                is_dialogue = role in ("assistant", "user")
                new_content = message.get('content', "")

                if (state["content"] and last_role and last_role != role) and is_dialogue:
                    controls_to_add.append(
                        self.parse_and_render_message(text=state["content"],
                                                      is_user=state["is_user"],
                                                      avatar_path=state["avatar_path"])
                    )
                    state["content"] = ""

                if message.get('content', "") and is_dialogue:
                    if message.get('role') == 'assistant' and new_content:
                        state["is_user"] = False
                        state["avatar_path"] = CharacterManager.get_character_image(self.character.name)
                    elif message.get('role') == 'user' and new_content:
                        state["is_user"] = True
                        state["avatar_path"] = self.get_user_portrait_url()

                    state["content"] += new_content

                if i == len(self.chat_history.messages) - 1 and state["content"]:
                    controls_to_add.append(
                        self.parse_and_render_message(text=state["content"],
                                                      is_user=state["is_user"],
                                                      avatar_path=state["avatar_path"])
                    )

                if is_dialogue:
                    last_role = role

            # Reverse the list so newest is at index 0 (bottom of screen)
            controls_to_add.reverse()
            self.br_chat_list.current.controls.extend(controls_to_add)

            if self.chat_history.messages and self.chat_history.messages[-1].get('role') == 'assistant':
                self._append_message_actions() # Will insert at index 0 (newest)

        # No need to scroll, reverse list stays at bottom (0) by default
        # self.scroll_chat_to_bottom(500,0,True)

    def _refresh_prompt_chips(self):
        # Define prompt sets (Text, Icon)
        prompt_sets = [
            [
                # Showcases: Stats aggregation + Roasting
                ("Judge my library", ft.Icons.GAVEL),
                # Showcases: Vector Vibe Search
                ("Find a cozy game", ft.Icons.NIGHTLIGHT_ROUND),
                # Showcases: Wishlist Tool + Pricing API
                ("Any sales on my wishlist?", ft.Icons.ATTACH_MONEY),
            ],
            [
                # Showcases: Stats aggregation + Roasting
                ("What's my most shameful purchase?", ft.Icons.LOCAL_FIRE_DEPARTMENT),
                # Showcases: Vector Vibe Search
                ("Games for a rainy day", ft.Icons.WATER_DROP),
                # Showcases: Vault Search
                ("Pick a good game I barely played", ft.Icons.CASINO),
            ],
            [
                # Showcases: Vault Search / General reasoning
                ("What should I play next?", ft.Icons.VIDEOGAME_ASSET),
                # Showcases: Steam Achievements API + Recent Games
                ("Easiest achievements on my last game?", ft.Icons.EMOJI_EVENTS),
                # Showcases: Steam Friends API + Recent Games
                ("Are my friends playing my last game?", ft.Icons.PEOPLE),
            ]
        ]

        # Pick a random set for this session
        selected_prompts = random.choice(prompt_sets)

        # Helper to create the styled Flet chips
        def create_prompt_chip(text, icon):
            async def chip_clicked(e):
                # Fills the input field with the chip's text
                self.br_input.current.value = text
                self.br_input.current.update()

                # Automatically focus the input field
                # await self.br_input.current.focus()

                await self.send_message(e)

                # If you want it to auto-send instantly without them hitting Enter, you can call:
                # self.send_message(None) # (or whatever your send function is named)

            return GrimoireButton(
                content=text,
                icon=icon,
                icon_color=styles.COLOR_TEXT_SECONDARY,  # Muted icon
                color=styles.COLOR_TEXT_SECONDARY,
                style=ft.ButtonStyle(
                    color=styles.COLOR_TEXT_SECONDARY,
                    bgcolor=ft.Colors.with_opacity(0.10, styles.COLOR_TEXT_PRIMARY),
                    # Very faint background
                    shape=ft.RoundedRectangleBorder(radius=8),
                    # side=ft.BorderSide(1, styles.COLOR_BORDER_BRONZE),  Softer look
                    padding=ft.padding.symmetric(horizontal=16, vertical=12),
                ),
                on_click=chip_clicked
            )

        # --- THE BULLETPROOF FLET FIX ---
        # 1. Clear the existing controls in the exact Row object mounted in the UI
        self.prompt_chips_row.controls.clear()

        # 2. Append the new buttons directly into the existing list
        for text, icon in selected_prompts:
            self.prompt_chips_row.controls.append(create_prompt_chip(text, icon))

        # 3. Safely update
        try:
            self.prompt_chips_row.update()
        except Exception:
            pass  # Ignores the error on initial boot

    def _build_empty_state(self):
        current_char = ""
        try:
            current_settings = settings.load_settings()
            current_char = current_settings.get("CHARACTER", "Reaper")
            if current_char == "Reaper":
                current_char = "the Reaper"
        except Exception as e:
            print(f"Error loading settings: {e}")

        self._refresh_prompt_chips()

        return ft.Container(
            ref=self.br_empty_state,  # We need a ref to hide it later
            alignment=ft.Alignment.CENTER,
            content=ft.Column(
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=10,
                controls=[
                    ft.Image(
                        src=str(paths.get_asset_path("assets", "summoning_circle.png")),
                        width=450, height=450,
                        fit=ft.BoxFit.CONTAIN,
                        opacity=0.12,
                        color_blend_mode=ft.BlendMode.MODULATE
                    ),
                    ft.Text("The Ledger is Open", font_family=styles.FONT_HEADING, size=22, opacity=0.7),
                    ft.Text(f"Summon {current_char}...", font_family=styles.FONT_MONO, size=12, italic=True,
                            color=styles.COLOR_TEXT_SECONDARY, ref=self.br_empty_state_name),

                    # Chips
                    ft.Container(height=15),
                    self.prompt_chips_row
                ]
            )
        )

    def copy_chat_history(self, e):
        if not self.chat_history.messages: return

        full_log = ""
        clipboard_nl = ui.utils.get_clipboard_newline()
        for msg in self.chat_history.messages:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")
            full_log += f"**{role}**: {content}{clipboard_nl}"

        self.page.run_task(ft.Clipboard().set, full_log)

        self.page.show_dialog(ft.SnackBar(ft.Text("Chat history copied to clipboard!")))
        self.page.update()

    """
    DEPRECATED
    was used to stick to bottom before reversed list
    """
    def handle_scroll(self, e: ft.OnScrollEvent):
        if self.last_scroll_pixels is None:
            self.last_scroll_pixels = e.pixels
            return

        # Calculate delta to detect direction
        delta = e.pixels - self.last_scroll_pixels
        self.last_scroll_pixels = e.pixels

        self.current_scroll_offset = e.pixels
        self.max_scroll_extent = e.max_scroll_extent

        # Logic for "Stick to Bottom"
        # Using directional logic for better UX:
        # - Easy to leave (scroll up)
        # - Easy to return (scroll down near bottom)
        distance_from_bottom = e.max_scroll_extent - e.pixels

        if delta < -10:  # User is scrolling UP intentionally -> Detach
            self.stick_to_bottom = False
        elif delta > 0 and distance_from_bottom <= 500: # User is scrolling DOWN and is CLOSE to bottom (generous for bursts) -> Re-attach
            self.stick_to_bottom = True
        elif distance_from_bottom <= 20: # Just resting at bottom -> Maintain
            self.stick_to_bottom = True

    def get_user_portrait_url(self):
        # Return cached URL if available, otherwise return None (default avatar will be used)
        # We do NOT block here.
        return self.user_portrait_url

    def parse_and_render_message(self, text, is_user, reasoning_text=None, avatar_path=None, reasoning_expanded=False):
        controls = []

        # If it's a user message or no JSON, just render markdown
        if "```json" not in text or is_user:
            controls.append(ft.Markdown(text, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB))
        else:
            segments = text.split("```json")

            if segments[0].strip():
                controls.append(ft.Markdown(segments[0].strip(), extension_set=ft.MarkdownExtensionSet.GITHUB_WEB))

            for segment in segments[1:]:
                if "```" in segment:
                    json_part, post_text = segment.split("```", 1)
                    try:
                        games_list = json.loads(json_part)
                        if isinstance(games_list, list):
                            card_row = ft.Row(wrap=True, spacing=10, run_spacing=10)
                            for game in games_list:
                                card_row.controls.append(GameCard(game))
                            controls.append(ft.Container(content=card_row, padding=5))
                        else:
                            controls.append(ft.Markdown(f"```json{json_part}```"))
                    except json.JSONDecodeError:
                        controls.append(ft.Markdown(f"```json{json_part}```"))

                    if post_text.strip():
                        controls.append(ft.Markdown(post_text.strip(), extension_set=ft.MarkdownExtensionSet.GITHUB_WEB))
                else:
                    controls.append(ft.Markdown(f"```json{segment}", extension_set=ft.MarkdownExtensionSet.GITHUB_WEB))

        bubble_content = ft.Column(controls, tight=True, spacing=5)

        user_avatar_name = settings.STEAM_USER if settings.STEAM_USER else "USER"
        current_char_name = "Reaper"
        try:
            current_settings = settings.load_settings()
            current_char = current_settings.get("CHARACTER", "Ember")
            current_char_name = CharacterManager.load_character(current_char).name
        except:
            print("Error getting character name")

        avatar_name = user_avatar_name if is_user else current_char_name

        reasoning_control = None
        if reasoning_text and not is_user:
            reasoning_control = ft.Markdown(value=reasoning_text, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB, visible=True, selectable=True)

        return ReaperChatBubble(
            avatar_name=avatar_name,
            content_control=bubble_content,
            is_user=is_user,
            reasoning_control=reasoning_control,
            reasoning_title="Dark Machinations...",
            avatar_src=avatar_path,
            reasoning_expanded=reasoning_expanded,
            markdown_text=text,
        )

    async def add_action_display(self, description = "Using tool"):
        if self.br_chat_list.current:
            action_display = ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.TERMINAL, size=14, color=styles.COLOR_SYSTEM_LOG),
                    ft.Text(f"> {description}", size=12, font_family=styles.STYLE_MONOSPACE, color=styles.COLOR_SYSTEM_LOG)
                ], spacing=5, alignment=ft.MainAxisAlignment.CENTER),
                padding=ft.Padding.symmetric(vertical=5),
            )

            # Reverse list order: [Streaming Bubble (0), Action (1), ...]
            # We want Action to appear visually ABOVE the streaming bubble.
            insert_index = 0
            if self.current_streaming_bubble:
                try:
                    idx = self.br_chat_list.current.controls.index(self.current_streaming_bubble)
                    insert_index = idx + 1
                except ValueError:
                    pass

                self.br_chat_list.current.controls.insert(insert_index, action_display)
            else:
                self.br_chat_list.current.controls.append(action_display)
            try:
                await ui.utils.smart_update(self.br_chat_list.current)
                # No scroll needed
            except RuntimeError:
                pass

    def run_backlog_reaping_thread(self, user_message, run_id, stop_event):
        try:
            if stop_event.is_set(): return

            # Signal initialization immediately for responsiveness
            self.stream_queue.put({"type": "init", "run_id": run_id})

            # Note: Update logic moved to main thread before spawning this thread

            # CONSUME THE STREAM
            stream = self.agent.chat_stream(user_message, self.chat_history)

            for event_type, content in stream:
                if stop_event.is_set(): break
                self.stream_queue.put({"type": event_type, "content": content, "run_id": run_id})

            # Final Cleanup
            if not stop_event.is_set():
                self.stream_queue.put({"type": "finish", "run_id": run_id})
            else: # Stop button, cancel event
                self.stream_queue.put({"type": "cancel", "run_id": run_id})

        except Exception as e:
            traceback.print_exc()
            self.stream_queue.put({"type": "error", "content": str(e), "run_id": run_id})
        finally:
            self.stream_queue.put({"type": "cleanup", "run_id": run_id})

    async def _render_loop(self):
        """
        Dedicated background task to update UI from stream queue and state.
        Decouples message processing speed from UI rendering speed (RPC calls).
        """
        while self.stream_active or not self.stream_queue.empty():
            # Process all available items in the queue
            while not self.stream_queue.empty():
                try:
                    message = self.stream_queue.get_nowait()
                    await self._process_stream_message(message)
                except queue.Empty:
                    break

            # If updates are pending, apply them to the UI
            if self.stream_state.get("needs_update", False):
                state = self.stream_state

                # Update Reasoning
                if state["reasoning_view"] and state["reasoning_view"].page and state["reasoning_view"].visible:
                     await ui.utils.smart_update(state["reasoning_view"])
                if state["reasoning_container_ref"] and state["reasoning_container_ref"].current and state["reasoning_container_ref"].current.page and state["reasoning_container_ref"].current.visible:
                     await ui.utils.smart_update(state["reasoning_container_ref"].current)

                # Update Status Text (for visibility changes or text updates)
                if state["status_text"] and state["status_text"].page:
                     await ui.utils.smart_update(state["status_text"])

                # Update Markdown
                if state["agent_markdown"] and state["agent_markdown"].page:
                    await ui.utils.smart_update(state["agent_markdown"])

                # No manual scroll needed in reverse mode
                self.stream_state["needs_update"] = False

            # If stream is inactive and queue is empty, exit loop
            if not self.stream_active and self.stream_queue.empty():
                break

            await asyncio.sleep(0.05)

    async def _process_stream_message(self, message):
        """
        Internal handler to process stream messages and update state/UI.
        Replaces _on_message_async.
        """
        msg_run_id = message.get("run_id")

        # Ignore messages from old/zombie threads
        if msg_run_id != self.current_run_id:
            return

        msg_type = message.get("type")
        content = message.get("content")
        state = self.stream_state

        if msg_type == "init":
            # Clean up any existing streaming bubble to prevent duplicates
            if self.current_streaming_bubble:
                try:
                    if self.br_chat_list.current and self.current_streaming_bubble in self.br_chat_list.current.controls:
                        self.br_chat_list.current.controls.remove(self.current_streaming_bubble)
                except Exception:
                    pass
                self.current_streaming_bubble = None

            state["status_text"] = ft.Text("Awakening...", italic=True, size=12, color=ft.Colors.GREY_500)
            state["agent_markdown"] = ft.Markdown("", selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB)
            state["reasoning_view"] = ft.Markdown("", extension_set=ft.MarkdownExtensionSet.GITHUB_WEB, visible=False, selectable=True)
            state["reasoning_buffer"] = ""

            # Get Real Name and Avatar
            current_settings = settings.load_settings()
            current_char = current_settings.get("CHARACTER", "Reaper")
            real_char_name = CharacterManager.get_character_real_name(current_char)
            avatar_path = CharacterManager.get_character_image(current_char)

            bubble_content = ft.Column([state["status_text"], state["agent_markdown"]], tight=True, spacing=5)

            reasoning_ref = ft.Ref()
            state["reasoning_container_ref"] = reasoning_ref

            full_message_block = ReaperChatBubble(
                avatar_name=real_char_name,
                content_control=bubble_content,
                is_user=False,
                reasoning_control=state["reasoning_view"],
                reasoning_title="Consulting the Void...",
                reasoning_ref=reasoning_ref,
                reasoning_visible=False,
                avatar_src=avatar_path,
                reasoning_expanded=False
            )

            # Store reference to the streaming bubble for later removal
            self.current_streaming_bubble = full_message_block

            if self.br_chat_list.current:
                self.br_chat_list.current.controls.insert(0, full_message_block)
                await ui.utils.smart_update(self.br_chat_list.current)
                # No scroll needed

        elif msg_type == "reasoning":
            state["reasoning_buffer"] += content
            if state["reasoning_view"]:
                state["reasoning_view"].value = state["reasoning_buffer"]
                state["reasoning_view"].visible = True

            if "reasoning_container_ref" in state and state["reasoning_container_ref"].current:
                state["reasoning_container_ref"].current.visible = True

            state["needs_update"] = True

        elif msg_type == "status":
            # No status in Bubble, just tool actions, status in status bar
            # if state["status_text"]:
            #     state["status_text"].value = content
            #     try:
            #         await ui.utils.smart_update(state["status_text"])
            #     except RuntimeError:
            #         pass

            if self.br_status.current:
                self.br_status.current.value = content
                self.br_status.current.color = styles.COLOR_TEXT_SECONDARY
                if self.br_status.current.page:
                    await ui.utils.smart_update(self.br_status.current)

        elif msg_type == "action":
            # Add action to chat history
            await self.add_action_display(content)

            # Update status text in bubble
            state["status_text"].value = content
            try:
                await ui.utils.smart_update(state["status_text"])
            except RuntimeError:
                pass

            state["previous_was_tool"] = True

        elif msg_type == "tokens":
            try:
                self.session_input_tokens += int(content.get("in", 0))
                self.session_output_tokens += int(content.get("out", 0))
                if self.br_token_count.current:
                    self.br_token_count.current.value = f"In: {self.session_input_tokens} Out: {self.session_output_tokens}"
                    if self.br_token_count.current.page:
                        await ui.utils.smart_update(self.br_token_count.current)
            except Exception as e:
                print(f"Error parsing tokens: {e}")

        elif msg_type == "text":
            # Update state synchronously first
            if state["status_text"] and state["status_text"].visible:
                state["status_text"].visible = False

            if state["previous_was_tool"] and not state["first_text"]:
                state["agent_markdown"].value += ui.utils.get_markdown_newline() # 2 leading white spaces to force windows to wrap line

            state["agent_markdown"].value += content

            state["previous_was_tool"] = False
            state["first_text"] = False

            state["needs_update"] = True

        elif msg_type == "finish":
            self.stream_active = False # Signal loop to exit (after queue empty)

            if not self.current_streaming_bubble:
                return

            # Force final flush of streaming controls to ensure completeness before replacement
            if state["agent_markdown"] and state["agent_markdown"].page:
                await ui.utils.smart_update(state["agent_markdown"])

            if state["reasoning_view"] and state["reasoning_view"].page:
                await ui.utils.smart_update(state["reasoning_view"])

            final_text = state["agent_markdown"].value
            final_reasoning = state["reasoning_buffer"]

            bubble_to_remove = self.current_streaming_bubble
            self.current_streaming_bubble = None

            if self.br_chat_list.current:
                current_settings = settings.load_settings()
                current_char = current_settings.get("CHARACTER", "Reaper")
                avatar_path = CharacterManager.get_character_image(current_char)

                was_reasoning_expanded = getattr(bubble_to_remove, "reasoning_expanded", False)

                try:
                    if bubble_to_remove in self.br_chat_list.current.controls:
                        self.br_chat_list.current.controls.remove(bubble_to_remove)
                except ValueError:
                    pass

                final_msg_control = self.parse_and_render_message(
                    final_text,
                    is_user=False,
                    reasoning_text=final_reasoning,
                    avatar_path=avatar_path,
                    reasoning_expanded=was_reasoning_expanded
                )
                self.br_chat_list.current.controls.insert(0, final_msg_control)

                self._append_message_actions() # Inserts at 0

                await ui.utils.smart_update(self.br_chat_list.current)
                # No scroll needed


            await self.update_buttons(False)

            if self.br_status.current:
                self.br_status.current.value = "Ready"
                self.br_status.current.color = styles.COLOR_TEXT_SECONDARY
                await ui.utils.smart_update(self.br_status.current)

            # Finished we now save chat status
            self.chat_history.save()

        elif msg_type == "error":
            self.stream_active = False

            # Clean chat UI and chat history
            self.br_input.current.value = await self.remove_last_ai_response(including_user=True)

            self.page.show_dialog(ft.SnackBar(ft.Text("Error: " + content)))

            if self.br_status.current:
                self.br_status.current.value = f"Error: {content}"
                self.br_status.current.color = styles.COLOR_ERROR

            await ui.utils.smart_update(self.page)

        elif msg_type == "cancel":
            self.stream_active = False

            # Clean chat UI and chat history
            self.br_input.current.value = await self.remove_last_ai_response(including_user=True)

            if self.br_status.current:
                self.br_status.current.value = "Cancelled"
                self.br_status.current.color = styles.COLOR_TEXT_SECONDARY

            await ui.utils.smart_update(self.page)

        elif msg_type == "cleanup":
            # Just ensure buttons are reset, stream_active should be False by now via other events
            await self.update_buttons(False)

    async def _scroll_task(self, duration, delay_ms):
        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000)
        if self.br_chat_list.current:
            try:
                # Flet > 0.80: scroll_to is awaitable
                res = self.br_chat_list.current.scroll_to(offset=-1, duration=duration)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                pass

    def scroll_chat_to_bottom(self, duration=700, delay_ms=0, forced=False):
        pass
        # Deprecated: Reverse ListView handles this natively.
        # Keeping method stub to prevent crashes if called by legacy code.

    def start_chat_thread(self, user_message):
        # Stop previous thread cleanly
        if self.current_stop_event:
            self.current_stop_event.set()

        # Create new ID and Event
        new_run_id = str(uuid.uuid4())
        self.current_run_id = new_run_id

        new_stop_event = threading.Event()
        self.current_stop_event = new_stop_event

        # Ensure queue is clean, filter by run_id handles it.

        # Reset state
        self.stream_state = {
            "status_text": None,
            "agent_markdown": None,
            "reasoning_view": None,
            "reasoning_buffer": "",
            "previous_was_tool": False,
            "first_text": True,
            "reasoning_container_ref": None,
            "needs_update": False
        }
        self.current_streaming_bubble = None

        # Start background render loop
        self.stream_active = True

        # RESET SCROLL STATE (Kept for compatibility, though reverse list handles sticking natively)
        self.last_scroll_pixels = None
        self.stick_to_bottom = True

        if hasattr(self.page, 'run_thread'):
            self.page.run_task(self._render_loop)
        else:
            threading.Thread(target=self._render_loop, daemon=True).start()

        # Start thread
        if hasattr(self.page, 'run_thread'):
             self.page.run_thread(self.run_backlog_reaping_thread, user_message, new_run_id, new_stop_event)
        else:
             threading.Thread(target=self.run_backlog_reaping_thread, args=(user_message, new_run_id, new_stop_event), daemon=True).start()

    def _append_message_actions(self):
        """Builds and appends the action buttons below the latest AI response."""
        if not self.br_chat_list.current:
            return

        actions_row = ft.Row(
            controls=[
                # Delete/Undo Button
                ft.IconButton(
                    icon=ft.Icons.UNDO,
                    tooltip="Delete & Edit Last Prompt",
                    icon_color=styles.COLOR_TEXT_SECONDARY,
                    on_click=self.delete_last_click,
                    icon_size=20,
                ),
                # Regenerate Button
                ft.IconButton(
                    icon=ft.Icons.REFRESH,
                    tooltip="Regenerate Response",
                    icon_color=styles.COLOR_TEXT_SECONDARY,
                    on_click=self.regenerate_click,
                    icon_size=20,
                )
            ],
            alignment=ft.MainAxisAlignment.END,
            data="message_action_buttons"
        )
        # In reverse list, Index 0 is the BOTTOM (newest).
        self.br_chat_list.current.controls.insert(0, actions_row)

    async def remove_message_actions(self, perform_update=True):
        if self.br_chat_list.current and self.br_chat_list.current.controls:
            # In reverse list, newest item is at index 0
            first_ctrl = self.br_chat_list.current.controls[0]

            # Check for new ID or old ID
            ctrl_data = getattr(first_ctrl, "data", "")
            if ctrl_data == "message_action_buttons" or ctrl_data == "regenerate_button":
                self.br_chat_list.current.controls.pop(0)
                if perform_update:
                    await ui.utils.smart_update(self.br_chat_list.current)
                return

            # Legacy check (fallback)
            if isinstance(first_ctrl, ft.Row) and first_ctrl.controls and isinstance(first_ctrl.controls[0], ft.IconButton):
                 if first_ctrl.controls[0].icon == ft.Icons.REFRESH:
                    self.br_chat_list.current.controls.pop(0)
                    if perform_update:
                        await ui.utils.smart_update(self.br_chat_list.current)

    async def delete_last_click(self, e):
        # Remove the action buttons row
        await self.remove_message_actions(perform_update=False)

        # Pop AI and User messages, and grab the user's text
        user_text = await self.remove_last_ai_response(including_user=True)

        # Put text back in the input box
        if user_text and self.br_input.current:
            self.br_input.current.value = user_text
            await ui.utils.smart_update(self.br_input.current)

        # Append actions again
        if self.chat_history.messages and self.chat_history.messages[-1].get('role') == 'assistant':
            self._append_message_actions()

        # Scroll and save
        self.scroll_chat_to_bottom(forced=True, duration=0, delay_ms=50)
        self.chat_history.save()
        await self.update_buttons(False) # Ensure we are in "Ready" state

        # Force chat clear and shows empty state
        if self.chat_history.get_chat_length() == 0:
            self.execute_clear_chat(e=None)

    async def regenerate_click(self, e):
        await self.remove_message_actions(perform_update=False)

        await self.remove_last_ai_response(including_user=False)

        if self.br_chat_list.current:
            self.current_scroll_offset = 0
            self.max_scroll_extent = 0
            self.scroll_chat_to_bottom(forced=True, duration=0, delay_ms=50)

        await self.update_buttons(True)

        if self.chat_history.messages:
             last_msg = self.chat_history.messages[-1]
             if last_msg["role"] == "user":
                 user_message = last_msg["content"]
                 self.chat_history.pop()
                 self.start_chat_thread(user_message)

    async def remove_last_ai_response(self, including_user=False):
        # History update (remains same, works on backend list)
        while self.chat_history.messages and not self.chat_history.messages[-1]["role"] == "user":
            self.chat_history.pop()

        user_text = ""
        if including_user:
            if self.chat_history.messages and self.chat_history.messages[-1]["role"] == "user":
                user_text = self.chat_history.messages[-1]["content"]
                self.chat_history.pop()

        # UI update (Reverse list: Newest at Index 0)
        while self.br_chat_list.current.controls:
            first_ctrl = self.br_chat_list.current.controls[0]

            is_user_message = False
            if isinstance(first_ctrl, ReaperChatBubble) and getattr(first_ctrl, "is_user", False):
                is_user_message = True
            elif getattr(first_ctrl, "data", None) == "user_message":
                is_user_message = True

            if is_user_message:
                if including_user: # Force to pop user message too
                    self.br_chat_list.current.controls.pop(0)
                    return user_text
                break

            self.br_chat_list.current.controls.pop(0)
        return None

    async def prune_chat_ui(self):
        """
        Removes oldest chat bubbles if the list exceeds the maximum limit.
        """
        if not self.br_chat_list.current:
            return

        controls = self.br_chat_list.current.controls
        if len(controls) > self.max_chat_bubbles:
            excess = len(controls) - self.max_chat_bubbles
            for _ in range(excess):
                controls.pop() # Remove from END (oldest) in reverse list

    def hide_background(self):
        # Hide Background
        if self.br_empty_state.current.visible:
            self.br_empty_state.current.visible = False
            self.br_empty_state.current.update()

    def refresh_state(self):
        """Called by flet main page/controller when the user navigates back to this tab."""

        # Check if the character actually changed in settings
        current_settings = settings.load_settings()
        new_char_name = current_settings.get("CHARACTER", "Reaper")

        # Fetch avatar
        threading.Thread(target=self._prefetch_avatar, daemon=True).start()

        # If the character changed, we must reload the chat
        if not self.character or self.character.name != new_char_name:
            self.chat_history.reset_history()  # Removes all messages
            self._initialize_character()  # Loads the new Character and JSON

            # Update the Summoning Circle text
            if self.br_empty_state.current:
                char_display = new_char_name if new_char_name != "Reaper" else "the Reaper"
                self.br_empty_state_name.current.value = f"Summon {char_display}..."
                self.br_empty_state.current.update()
                self.br_empty_state_name.current.update()

            self._reload_chat_from_history()  # Rebuilds UI from new JSON

            # If the new history is empty, ensure the circle is visible
            if not self.chat_history.get_chat_length() and self.br_empty_state.current:
                self.br_empty_state.current.visible = True
            else:
                self.hide_background()

            self.update()
        else:
            self.scroll_chat_to_bottom(forced=True, duration=500, delay_ms=0)

    def _sync_data_sources_blocking(self):
        # This function runs in a separate thread
        try:
            for _ in vault.update(settings.STEAM_USER):
                pass
            vibes = VibeEngine.get_instance()
            vibes.ingest_library()
        except Exception as e:
            print(f"Sync error: {e}")

    async def stop(self, e):
        if self.current_stop_event:
            self.current_stop_event.set()

    async def update_buttons(self, is_running):
        if is_running:
            self.br_input.current.disabled = True
            self.br_btn_send.current.disabled = True
            self.br_btn_send.current.visible = False
            self.br_btn_stop.current.visible = True
        else:
            self.br_input.current.disabled = False
            self.br_btn_send.current.disabled = False
            self.br_btn_send.current.visible = True
            self.br_btn_stop.current.visible = False

        if self.br_input.current:
            await ui.utils.smart_update(self.br_input.current)
        if self.br_btn_send.current:
            await ui.utils.smart_update(self.br_btn_send.current)
        if self.br_btn_stop.current:
            await ui.utils.smart_update(self.br_btn_stop.current)


    async def send_message(self, e, message=None):
        if message:
            user_message = message
        else:
            user_message = self.br_input.current.value

        if not user_message:
            return

        ok_llm_keys, msg_llm_keys = startup.check_llm_keys()
        if not ok_llm_keys:
            self.page.show_dialog(ft.SnackBar(ft.Text(f"Please configure your LLM settings in the Settings tab: {msg_llm_keys}")))
            self.page.update()
            return

        # Hide Background
        self.hide_background()

        self.br_input.current.value = ""
        await self.update_buttons(True) # Show/hide buttons

        user_portrait_url = self.get_user_portrait_url()

        await self.remove_message_actions(perform_update=False)

        if self.br_chat_list.current:
            # Prune before adding new message to keep list size stable
            await self.prune_chat_ui()

            # Insert at Index 0 (Bottom)
            self.br_chat_list.current.controls.insert(0, self.parse_and_render_message(user_message, is_user=True, avatar_path=user_portrait_url))
            await ui.utils.smart_update(self.br_chat_list.current)
            # No scroll needed

        # Check for Sync Needed
        if vault.get_games_count() and vault.get_elapsed_since_update() > 1200: # 20 Mins
            # Inject System Status Bubble
            sync_bubble = ft.Container(
                content=ft.Row(
                    controls=[
                        GrimoireProgressBar(
                            width=300,
                            height=12
                        ),
                        ft.Text("Channeling into game library...", color=styles.COLOR_SYSTEM_LOG, size=12, font_family=styles.STYLE_MONOSPACE)
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=10
                ),
                padding=10,
                alignment=ft.Alignment.CENTER
            )

            # Add to chat (temporarily)
            if self.br_chat_list.current:
                 self.br_chat_list.current.controls.insert(0, sync_bubble)
                 await ui.utils.smart_update(self.br_chat_list.current)
                 # No scroll needed

            # Run blocking update in thread, await it here
            await asyncio.to_thread(self._sync_data_sources_blocking)

            # Remove the bubble
            if self.br_chat_list.current:
                if sync_bubble in self.br_chat_list.current.controls:
                    self.br_chat_list.current.controls.remove(sync_bubble)
                    await ui.utils.smart_update(self.br_chat_list.current)


        self.start_chat_thread(user_message)

    def prompt_clear_chat(self, e):
        """Opens the confirmation dialog."""

        # Define the dialog
        self.confirm_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Burn the Ledger?", font_family=styles.FONT_HEADING, color=styles.COLOR_ERROR),
            content=ft.Text("Are you sure you want to wipe chat history? This action cannot be undone.",
                            color=styles.COLOR_TEXT_PRIMARY),
            bgcolor=styles.COLOR_SURFACE,
            shape=ft.RoundedRectangleBorder(radius=8),
            actions=[
                ft.TextButton(
                    "Cancel",
                    style=ft.ButtonStyle(color=styles.COLOR_TEXT_SECONDARY),
                    on_click=self.close_dialog
                ),
                ft.FilledButton(
                    "Wipe It",
                    style=ft.ButtonStyle(
                        bgcolor=styles.COLOR_ERROR,
                        color=ft.Colors.WHITE,
                        shape=ft.RoundedRectangleBorder(radius=5)
                    ),
                    on_click=self.execute_clear_chat
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        # Show the dialog (Using Flet 0.22+ syntax)
        self.page.show_dialog(self.confirm_dialog)

    def close_dialog(self, e):
        """Closes the dialog without doing anything."""
        if self.confirm_dialog:
            self.confirm_dialog.open = False
            self.page.update()

    def execute_clear_chat(self, e):
        """Performs the actual history deletion and chat ui clear."""

        # Clear the backend data
        self.chat_history.reset_history()
        self.chat_history.save()

        # Clear the Flet UI column
        if self.br_chat_list.current:
            self.br_chat_list.current.controls.clear()

        # Force chips redraw
        self._refresh_prompt_chips()

        # Bring back the Summoning Circle
        if self.br_empty_state.current:
            self.br_empty_state.current.visible = True

        # Close dialog
        if self.confirm_dialog:
            self.confirm_dialog.open = False

        self.update()