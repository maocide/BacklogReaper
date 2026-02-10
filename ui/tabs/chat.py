import time
import json
import threading
import traceback
import flet as ft

import agent
import vault
import settings
import character_manager
import game_intelligence
from vibe_engine import VibeEngine
import styles

from ui.widgets.chat_bubble import ReaperChatBubble
from ui.widgets.game_card import GameCard
from ui.widgets.styled_inputs import GrimoireTextField

class ReaperChatView(ft.Column):
    def __init__(self):
        super().__init__()
        self.expand = True

        self.br_chat_history = []
        self.br_chat_list = ft.Ref[ft.ListView]()
        self.br_input = ft.Ref[ft.TextField]()
        self.br_status = ft.Ref[ft.Text]()
        self.br_btn_send = ft.Ref[ft.IconButton]()

        self.stop_event_br = threading.Event()
        self.user_portrait_url = None

        # State for streaming
        self.stream_state = {
            "status_text": None,
            "agent_markdown": None,
            "reasoning_view": None,
            "reasoning_buffer": "",
            "previous_was_tool": False,
            "first_text": True,
            "reasoning_container_ref": None
        }

        self.controls = [
            ft.Row([
                ft.Text("Reaper Chat", theme_style=ft.TextThemeStyle.HEADLINE_MEDIUM, expand=True, font_family="Cinzel"),
                ft.IconButton(icon=ft.Icons.COPY, tooltip="Copy Chat History", on_click=self.copy_chat_history)
            ]),
            ft.Container(
                content=ft.ListView(
                    ref=self.br_chat_list,
                    expand=True,
                    spacing=10,
                    padding=10,
                    auto_scroll=True,
                ),
                expand=True,
            ),
            ft.Text(ref=self.br_status, value="Ready", color=styles.COLOR_TEXT_SECONDARY, size=12),
            ft.Row([
                GrimoireTextField(
                    ref=self.br_input,
                    hint_text="Ask the Reaper...",
                    expand=True,
                    multiline=True,
                    shift_enter=True,
                    on_submit=self.send_message,
                    label_style=ft.TextStyle(italic=True, color=styles.COLOR_ACCENT_DIM)
                ),
                ft.IconButton(ref=self.br_btn_send, icon=ft.Icons.SEND, icon_color=styles.COLOR_TEXT_GOLD, on_click=self.send_message)
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        ]

    def did_mount(self):
        # We subscribe when the view is mounted
        # Note: In flet_gui.py, subscription happened inside start_chat_thread.
        # But here we want to listen always? Or only when chat is active?
        # The original code subscribed in start_chat_thread and unsubscribed in finish/cleanup.
        # If I subscribe here, I'll receive messages.
        # But run_backlog_reaping_thread sends to all.
        # So yes, I should subscribe here.
        self.page.pubsub.subscribe(self.on_message)

    def will_unmount(self):
        self.page.pubsub.unsubscribe(self.on_message)

    def update_data_sources(self):
        vault.update(settings.STEAM_USER)
        vibes = VibeEngine.get_instance()
        vibes.ingest_library()

    def copy_chat_history(self, e):
        if not self.br_chat_history: return

        full_log = ""
        for msg in self.br_chat_history:
            role = msg.get("role", "unknown").upper()
            content = msg.get("content", "")
            full_log += f"**{role}**: {content}\n\n"

        self.page.run_task(ft.Clipboard().set, full_log)

        self.page.snack_bar = ft.SnackBar(ft.Text("Chat history copied to clipboard!"))
        self.page.snack_bar.open = True
        self.page.update()

    def get_user_portrait_url(self):
        if self.user_portrait_url:
            return self.user_portrait_url
        else:
            self.user_portrait_url = game_intelligence.get_steam_avatar(settings.STEAM_USER)
        return self.user_portrait_url

    def parse_and_render_message(self, text, is_user, reasoning_text=None, avatar_path=None):
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
        current_char = "Reaper"
        try:
            current_settings = settings.load_settings()
            current_char = current_settings.get("CHARACTER", "Reaper")
        except:
            print("Error loading settings for character.")

        avatar_name = user_avatar_name if is_user else current_char

        reasoning_control = None
        if reasoning_text and not is_user:
            reasoning_control = ft.Markdown(value=reasoning_text, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB, visible=True, selectable=True)

        return ReaperChatBubble(
            avatar_name=avatar_name,
            content_control=bubble_content,
            is_user=is_user,
            reasoning_control=reasoning_control,
            reasoning_title="Dark Machinations...",
            avatar_src=avatar_path
        )

    def run_backlog_reaping_thread(self, user_message):
        try:
            if self.stop_event_br.is_set(): return

            # Update db if not done for 20 mins
            if vault.get_games_count() and vault.get_elapsed_since_update() > 1200:
                self.update_data_sources()

            # Signal initialization
            self.page.pubsub.send_all({"type": "init"})

            # CONSUME THE STREAM
            stream = agent.agent_chat_loop_stream(user_message, self.br_chat_history)

            for event_type, content in stream:
                if self.stop_event_br.is_set(): break
                time.sleep(0.02) # Small yield
                self.page.pubsub.send_all({"type": event_type, "content": content})

            # Final Cleanup
            if not self.stop_event_br.is_set():
                self.page.pubsub.send_all({"type": "finish"})

        except Exception as e:
            traceback.print_exc()
            self.page.pubsub.send_all({"type": "error", "content": str(e)})
        finally:
            self.page.pubsub.send_all({"type": "cleanup"})

    def start_chat_thread(self, user_message):
        # Reset state
        self.stream_state = {
            "status_text": None,
            "agent_markdown": None,
            "reasoning_view": None,
            "reasoning_buffer": "",
            "previous_was_tool": False,
            "first_text": True,
            "reasoning_container_ref": None
        }

        # Start thread
        if hasattr(self.page, 'run_thread'):
             self.page.run_thread(self.run_backlog_reaping_thread, user_message)
        else:
             threading.Thread(target=self.run_backlog_reaping_thread, args=(user_message,), daemon=True).start()

    def on_message(self, message):
        msg_type = message.get("type")
        content = message.get("content")
        state = self.stream_state

        if msg_type == "init":
            state["status_text"] = ft.Text("Initializing...", italic=True, size=12, color=ft.Colors.GREY_500)
            state["agent_markdown"] = ft.Markdown("", selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB)
            state["reasoning_view"] = ft.Markdown("", extension_set=ft.MarkdownExtensionSet.GITHUB_WEB, visible=False, selectable=True)
            state["reasoning_buffer"] = ""

            # Get Real Name and Avatar
            current_settings = settings.load_settings()
            current_char = current_settings.get("CHARACTER", "Reaper")
            real_char_name = character_manager.get_character_real_name(current_char)
            avatar_path = character_manager.get_character_image(current_char)

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
                avatar_src=avatar_path
            )

            if self.br_chat_list.current:
                self.br_chat_list.current.controls.append(full_message_block)
                self.br_chat_list.current.update()

        elif msg_type == "reasoning":
            state["reasoning_buffer"] += content
            if state["reasoning_view"]:
                state["reasoning_view"].value = state["reasoning_buffer"]
                state["reasoning_view"].visible = True
                if state["reasoning_view"].page:
                    state["reasoning_view"].update()
                if "reasoning_container_ref" in state and state["reasoning_container_ref"].current:
                    state["reasoning_container_ref"].current.visible = True
                    if state["reasoning_container_ref"].current.page:
                        state["reasoning_container_ref"].current.update()

        elif msg_type == "status":
            if state["status_text"]:
                state["status_text"].value = content
                try:
                    state["status_text"].update()
                except RuntimeError:
                    pass

            if self.br_status.current:
                self.br_status.current.value = content
                if self.br_status.current.page:
                    self.br_status.current.update()

        elif msg_type == "action":
            if self.br_chat_list.current:
                action_display = ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.TERMINAL, size=14, color=styles.COLOR_SYSTEM_LOG),
                        ft.Text(f"> {content}", size=12, font_family=styles.STYLE_MONOSPACE, color=styles.COLOR_SYSTEM_LOG)
                    ], spacing=5, alignment=ft.MainAxisAlignment.CENTER),
                    padding=ft.Padding.symmetric(vertical=5),
                )

                position = len(self.br_chat_list.current.controls) - 1
                self.br_chat_list.current.controls.insert(position, action_display)

            try:
                self.br_chat_list.current.update()
            except RuntimeError:
                pass

            state["previous_was_tool"] = True

        elif msg_type == "text":
            if state["status_text"] and state["status_text"].visible:
                state["status_text"].visible = False
                if state["status_text"].page:
                    state["status_text"].update()

            if state["previous_was_tool"] and not state["first_text"]:
                state["agent_markdown"].value += "\n\n"

            state["agent_markdown"].value += content
            if state["agent_markdown"].page:
                state["agent_markdown"].update()

            state["previous_was_tool"] = False
            state["first_text"] = False

        elif msg_type == "finish":
            final_text = state["agent_markdown"].value
            final_reasoning = state["reasoning_buffer"]

            if self.br_chat_list.current:
                current_settings = settings.load_settings()
                current_char = current_settings.get("CHARACTER", "Reaper")
                avatar_path = character_manager.get_character_image(current_char)

                self.br_chat_list.current.controls.pop()
                self.br_chat_list.current.controls.append(self.parse_and_render_message(final_text, is_user=False, reasoning_text=final_reasoning, avatar_path=avatar_path))

                # Add Regenerate Button
                regen_btn = ft.Row(
                    controls=[
                        ft.IconButton(
                            icon=ft.Icons.REFRESH,
                            tooltip="Regenerate Response",
                            icon_color=ft.Colors.GREY_500,
                            on_click=self.regenerate_click,
                            icon_size=20,
                        )
                    ],
                    alignment=ft.MainAxisAlignment.END
                )
                self.br_chat_list.current.controls.append(regen_btn)

                self.br_chat_list.current.update()

            if self.br_status.current:
                self.br_status.current.value = "Ready"
                self.br_status.current.color = styles.COLOR_TEXT_SECONDARY
                self.br_status.current.update()

        elif msg_type == "error":
            if self.br_chat_list.current:
                self.br_chat_list.current.controls.append(ft.Text(f"Error: {content}", color=styles.COLOR_ERROR))
                self.br_chat_list.current.update()
            if self.br_status.current:
                self.br_status.current.value = f"Error: {content}"
                self.br_status.current.color = styles.COLOR_ERROR
                self.br_status.current.update()

        elif msg_type == "cleanup":
            if self.br_btn_send.current:
                self.br_btn_send.current.disabled = False
                self.br_btn_send.current.update()
            if self.br_input.current:
                self.br_input.current.disabled = False
                self.br_input.current.update()

    def remove_regen_button(self):
        if self.br_chat_list.current and self.br_chat_list.current.controls:
            last_ctrl = self.br_chat_list.current.controls[-1]
            if isinstance(last_ctrl, ft.Row) and last_ctrl.controls and isinstance(last_ctrl.controls[0], ft.IconButton):
                 if last_ctrl.controls[0].icon == ft.Icons.REFRESH:
                    self.br_chat_list.current.controls.pop()
                    self.br_chat_list.current.update()

    def regenerate_click(self, e):
        self.remove_regen_button()

        # Prune History
        while self.br_chat_history and self.br_chat_history[-1]["role"] not in ("user", "system"):
            self.br_chat_history.pop()

        # Prune UI
        if self.br_chat_list.current:
            while self.br_chat_list.current.controls:
                last_ctrl = self.br_chat_list.current.controls[-1]
                # Check if it's a User Message (tagged via data property of ReaperChatBubble)
                # ReaperChatBubble uses self.data
                if getattr(last_ctrl, "data", None) == "user_message":
                    break
                self.br_chat_list.current.controls.pop()

            self.br_chat_list.current.update()

        # Disable Inputs
        self.br_input.current.disabled = True
        self.br_btn_send.current.disabled = True
        self.br_input.current.update()
        self.br_btn_send.current.update()

        # Restart Thread
        if self.br_chat_history:
             last_msg = self.br_chat_history[-1]
             if last_msg["role"] == "user":
                 user_message = last_msg["content"]
                 self.br_chat_history.pop()

                 self.stop_event_br.clear()
                 self.start_chat_thread(user_message)

    def send_message(self, e):
        user_message = self.br_input.current.value
        if not user_message:
            return

        user_portrait_url = self.get_user_portrait_url()

        self.remove_regen_button()

        if self.br_chat_list.current:
            self.br_chat_list.current.controls.append(self.parse_and_render_message(user_message, is_user=True, avatar_path=user_portrait_url))
            self.br_chat_list.current.update()

        self.br_input.current.value = ""
        self.br_input.current.disabled = True
        self.br_btn_send.current.disabled = True

        self.br_input.current.update()
        self.br_btn_send.current.update()

        self.stop_event_br.clear()

        self.start_chat_thread(user_message)
