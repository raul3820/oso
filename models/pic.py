from PIL import Image, ImageDraw, ImageFont
import os
import io
import logfire

def get_image_bytes(text_content, background_name="background.jpg", image_format="JPEG"):
    """
    Adds text to an image, centering, resizing, and wrapping text to fit,
    and returns the image as bytes in a specified format.
    Supports special characters and emojis.

    Args:
        image_name (str): Name of the background image file. Defaults to "background.jpg".
        text_content (str): The text string to overlay. Defaults to "Your Text Here".
        image_format (str): The format to save the image as bytes (e.g., "PNG", "JPEG"). Defaults to "JPEG".

    Returns:
        bytes: The image data as bytes in the specified format, or None if an error occurs.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    image_path = os.path.join(os.path.dirname(script_dir), 'temp', background_name)

    # 1. Load Background Image or Create Default
    if os.path.exists(image_path):
        try:
            background_image = Image.open(image_path).convert("RGB") # Ensure RGB for consistent color handling
        except Exception as e:
            logfire.exception(f"Error opening image {image_path}: {e}. Using default black background.")
            background_image = Image.new("RGB", (600, 400), "black")
    else:
        logfire.warning(f"Background image not found at {image_path}. Using default black background.")
        background_image = Image.new("RGB", (600, 400), "black")

    image_width, image_height = background_image.size
    draw = ImageDraw.Draw(background_image)

    # 2. Font Selection - Use TrueType font that supports Unicode characters
    # For a slim Docker container, we need to install or include a font
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    fallback_font_path = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
    
    # Try to use a system font or fall back to a simpler solution
    try:
        if os.path.exists(font_path):
            font = ImageFont.truetype(font_path, size=20)  # Initial size, will be adjusted
        elif os.path.exists(fallback_font_path):
            font = ImageFont.truetype(fallback_font_path, size=20)
        else:
            # If no suitable font found, use a basic font
            font = ImageFont.load_default()
            logfire.warning(
                "Warning: Using default font. Special characters may not display correctly.", 
                "Install fonts in your Docker container with: apt-get update && apt-get install -y fonts-dejavu"
                )
    except Exception as e:
        logfire.exception(f"Error loading font: {e}. Using default font.")
        font = ImageFont.load_default()

    # 3. Text Wrapping Function
    def wrap_text(text, font, max_width):
        lines = []
        if not text:
            return lines
        words = text.split()
        current_line = ""
        for word in words:
            test_line = current_line + " " + word if current_line else word
            # Use getbbox for more accurate text measurement with Unicode
            bbox = draw.textbbox((0, 0), test_line, font=font)
            line_width = bbox[2] - bbox[0]

            if line_width <= max_width:
                current_line = test_line
            else:
                lines.append(current_line)
                current_line = word
        lines.append(current_line) # Add the last line
        return lines

    # 4. Text Resizing and Positioning
    MAX_FONT_SIZE = 100 # Start with a reasonable max size, can adjust
    MIN_FONT_SIZE = 10  # Minimum font size to stop resizing

    font_size = MAX_FONT_SIZE
    text_lines = []
    
    # Determine appropriate font size
    while font_size >= MIN_FONT_SIZE:
        try:
            if isinstance(font, ImageFont.FreeTypeFont):
                current_font = ImageFont.truetype(font.path, size=font_size)
            else:
                # If using default font, we can't resize effectively
                # Just use the default and break
                current_font = font
                break
                
            text_lines = wrap_text(text_content, current_font, image_width * 0.9) # 90% width for padding
            
            # Calculate total text height
            text_height_total = 0
            for line in text_lines:
                bbox = draw.textbbox((0, 0), line, font=current_font)
                text_height_line = bbox[3] - bbox[1]
                text_height_total += text_height_line + 4  # Add a small padding between lines

            if text_height_total <= image_height * 0.9: # 90% height for padding
                break # Font size is good, it fits!
            
            font_size -= 2 # Decrease font size and try again
        except Exception as e:
            logfire.exception(f"Error when adjusting font size: {e}. Using default size.")
            current_font = font
            text_lines = wrap_text(text_content, current_font, image_width * 0.9)
            break
    
    # Calculate vertical starting position for centered text block
    # First, get the total height of all wrapped text
    text_height_total = 0
    for line in text_lines:
        bbox = draw.textbbox((0, 0), line, font=current_font)
        line_height = bbox[3] - bbox[1]
        text_height_total += line_height + 4  # Same padding as above
    
    y_text_start = (image_height - text_height_total) // 2

    # Draw each line of text centered horizontally
    current_y = y_text_start
    for line in text_lines:
        # Get accurate dimensions for positioning
        bbox = draw.textbbox((0, 0), line, font=current_font)
        line_width = bbox[2] - bbox[0]
        line_height = bbox[3] - bbox[1]
        
        x_text_position = (image_width - line_width) // 2 # Horizontal center
        draw.text((x_text_position, current_y), line, font=current_font, fill="white") # White text for contrast
        current_y += line_height + 4  # Add consistent line spacing

    # 5. Save the Output Image to Bytes and Return
    try:
        image_bytes = io.BytesIO()
        background_image.save(image_bytes, format=image_format)
        return image_bytes.getvalue()
    except Exception as e:
        logfire.exception(f"Error saving image to bytes: {e}")
        return None

# Example of how to use and you would then save this byte object with asyncpg
if __name__ == '__main__':
    # Assuming you have a background.jpg in the temp folder relative to the script's directory
    image_bytes = get_image_bytes(text_content="Hello, asyncpg! 😊")
    if image_bytes:
        logfire.info(f"Image bytes generated successfully. Length: {len(image_bytes)} bytes.")
        # In a real application, you would use asyncpg to save image_bytes to your database.
        # Example (Conceptual - requires asyncpg setup):
        # async with connection.transaction():
        #     await connection.execute("INSERT INTO your_table (images) VALUES ($1)", [image_bytes])
    else:
        logfire.exception("Failed to generate image bytes.")