import styles
from PIL import Image, ImageDraw, ImageFont
from ui.utils import get_roast_asset
import paths


def generate_roast_image(game_data):
    """
    Generates a high-resolution image of the Roast Card using Pillow.
    Returns a PIL Image object.
    """
    # Configuration
    CARD_WIDTH = 600
    CARD_HEIGHT = 850
    PADDING = 40

    # Colors (Mapped from styles.py)
    COLOR_SURFACE = styles.COLOR_SURFACE
    COLOR_TEXT_PRIMARY = styles.COLOR_TEXT_PRIMARY
    COLOR_TEXT_SECONDARY = styles.COLOR_TEXT_SECONDARY
    COLOR_TEXT_GOLD = styles.COLOR_TEXT_GOLD
    COLOR_BORDER_BRONZE = styles.COLOR_BORDER_BRONZE

    # Fonts
    # Attempt to load Cinzel for headers
    font_path_heading = str(paths.get_asset_path("assets", "fonts", "Cinzel-VariableFont_wght.ttf"))
    try:
        font_heading = ImageFont.truetype(font_path_heading, 52)
    except IOError:
        font_heading = ImageFont.load_default()
        print("Warning: Cinzel font not found, using default.")

    # Attempt to load DejaVuSans for body
    font_path_body = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    font_path_bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    # Use Mono Oblique for comments (matches UI style better and file exists)
    font_path_italic = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Oblique.ttf"

    try:
        font_body = ImageFont.truetype(font_path_body, 28)
        font_body_bold = ImageFont.truetype(font_path_bold, 28)
        font_comment = ImageFont.truetype(font_path_italic, 24)
    except IOError:
        # Fallback to Cinzel if DejaVu is missing (unlikely in this env)
        font_body = font_heading
        font_body_bold = font_heading
        font_comment = font_heading
        print("Warning: DejaVu fonts not found, falling back.")

    # Base Image (Background)
    bg_theme = game_data.get("bg_theme", "DEFAULT")
    bg_path = get_roast_asset(bg_theme)

    # Create solid background first (matches UI card bgcolor)
    final_bg = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), COLOR_SURFACE)

    try:
        asset_img = Image.open(bg_path).convert("RGBA")

        # Resize/Crop to fill
        target_ratio = CARD_WIDTH / CARD_HEIGHT
        img_ratio = asset_img.width / asset_img.height

        if img_ratio > target_ratio:
            # Image is wider, crop width
            new_height = CARD_HEIGHT
            new_width = int(new_height * img_ratio)
            asset_img = asset_img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            left = (new_width - CARD_WIDTH) // 2
            asset_img = asset_img.crop((left, 0, left + CARD_WIDTH, CARD_HEIGHT))
        else:
            # Image is taller, crop height
            new_width = CARD_WIDTH
            new_height = int(new_width / img_ratio)
            asset_img = asset_img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            top = (new_height - CARD_HEIGHT) // 2
            asset_img = asset_img.crop((0, top, CARD_WIDTH, top + CARD_HEIGHT))

        # Composite asset onto solid background (handles transparency)
        final_bg.alpha_composite(asset_img)
        base_img = final_bg

    except IOError:
        # Fallback solid color
        base_img = final_bg

    # Gradient Overlay
    # Create a gradient from transparent to dark
    overlay = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    draw_overlay = ImageDraw.Draw(overlay)

    # Simple vertical gradient
    for y in range(CARD_HEIGHT):
        progress = y / CARD_HEIGHT
        if progress < 0.4:
            alpha = int(255 * 0.65)
        elif progress < 0.7:
            alpha = int(255 * 0.75)
        else:
            # Ramp up to 0.95
            t = (progress - 0.7) / 0.3
            alpha = int(255 * (0.75 + (0.20 * t)))

        draw_overlay.line([(0, y), (CARD_WIDTH, y)], fill=(17, 17, 17, alpha))

    base_img = Image.alpha_composite(base_img, overlay)

    # Draw Content
    draw = ImageDraw.Draw(base_img)

    # Header (Title)
    title_text = game_data.get("name", "Unknown Title")

    # Wrap title if too long
    # Simple wrap logic for title
    title_words = title_text.split()
    title_lines = []
    current_title_line = []

    for word in title_words:
        test_line = ' '.join(current_title_line + [word])
        w = draw.textlength(test_line, font=font_heading)
        if w < (CARD_WIDTH - 2 * PADDING):
            current_title_line.append(word)
        else:
            title_lines.append(' '.join(current_title_line))
            current_title_line = [word]
    title_lines.append(' '.join(current_title_line))

    y_cursor = PADDING
    for line in title_lines:
        draw.text((PADDING, y_cursor), line, font=font_heading, fill=COLOR_TEXT_PRIMARY)
        y_cursor += 60

    # Divider
    y_cursor += 10
    draw.line([(PADDING, y_cursor), (CARD_WIDTH - PADDING, y_cursor)], fill=COLOR_BORDER_BRONZE, width=2)
    y_cursor += 30

    # Info Rows
    labels = {
        "hltb_story": "Story",
        "hours_played": "Playtime"
    }
    ignore = ["appid", "name", "bg_theme", "comment"]

    for title, content in game_data.items():
        if title in ignore:
            continue

        # Format Label
        default_title = labels.get(title.lower())
        label_text = default_title if default_title else title.replace("_", " ").title()
        content_text = str(content)

        # Color logic for status
        val_color = COLOR_TEXT_PRIMARY
        if title.lower() == "status":
            val_color = COLOR_TEXT_GOLD

        # Draw Label
        draw.text((PADDING, y_cursor), f"{label_text}: ", font=font_body_bold, fill=COLOR_TEXT_SECONDARY)

        # Draw Value (offset x for first line)
        label_width = draw.textlength(f"{label_text}: ", font=font_body_bold)

        # Wrap value if it's too long
        value_words = content_text.split()
        value_lines = []
        current_value_line = []

        first_line_available_width = CARD_WIDTH - PADDING - (PADDING + label_width)
        subsequent_line_available_width = CARD_WIDTH - 2 * PADDING

        for word in value_words:
            test_line = ' '.join(current_value_line + [word])
            # Check width based on whether it's the first line or not
            w = draw.textlength(test_line, font=font_body)
            available_w = first_line_available_width if not value_lines else subsequent_line_available_width

            if w < available_w:
                current_value_line.append(word)
            else:
                if current_value_line:
                    value_lines.append(' '.join(current_value_line))
                current_value_line = [word]

        if current_value_line:
            value_lines.append(' '.join(current_value_line))

        # Handle empty content
        if not value_lines:
            value_lines = [""]

        # Draw first line
        draw.text((PADDING + label_width, y_cursor), value_lines[0], font=font_body, fill=val_color)
        y_cursor += 40

        # Draw subsequent lines starting from PADDING
        for line in value_lines[1:]:
            draw.text((PADDING, y_cursor), line, font=font_body, fill=val_color)
            y_cursor += 40

    # Spacer
    y_cursor += 20

    # Comment
    comment = game_data.get("comment")
    if comment:
        # Quote marks
        draw.text((PADDING - 10, y_cursor), '"', font=font_comment, fill=COLOR_BORDER_BRONZE)

        words = str(comment).split()
        lines = []
        current_line = []

        for word in words:
            test_line = ' '.join(current_line + [word])
            w = draw.textlength(test_line, font=font_comment)
            if w < (CARD_WIDTH - 2 * PADDING):
                current_line.append(word)
            else:
                lines.append(' '.join(current_line))
                current_line = [word]
        lines.append(' '.join(current_line))

        for line in lines:
            draw.text((PADDING, y_cursor), line, font=font_comment, fill=COLOR_BORDER_BRONZE)
            y_cursor += 35

        draw.text((draw.textlength(lines[-1], font=font_comment) + PADDING + 5, y_cursor - 35), '"', font=font_comment,
                  fill=COLOR_BORDER_BRONZE)

    # Branding / Footer
    # draw.text((PADDING, CARD_HEIGHT - 40), "Backlog Reaper", font=font_body, fill=(50, 50, 50))

    # Apply Rounded Corners (Masking)
    # Create a mask image (L mode)
    mask = Image.new("L", (CARD_WIDTH, CARD_HEIGHT), 0)
    draw_mask = ImageDraw.Draw(mask)

    # Draw white rounded rectangle on black mask
    corner_radius = 50  # Matching roughly the 25.0 Flet radius scaled up
    draw_mask.rounded_rectangle([(0, 0), (CARD_WIDTH, CARD_HEIGHT)], radius=corner_radius, fill=255)

    # Apply mask to alpha channel of base image
    base_img.putalpha(mask)

    return base_img
