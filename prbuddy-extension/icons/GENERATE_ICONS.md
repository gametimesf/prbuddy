# Generate Extension Icons

The extension needs PNG icons at 16x16, 48x48, and 128x128 pixels.

## Using the SVG

The `icon.svg` file in this directory contains the PR Buddy logo. Convert it to PNG at different sizes:

### Using ImageMagick

```bash
# Install ImageMagick if needed: brew install imagemagick

convert -background none icon.svg -resize 16x16 icon16.png
convert -background none icon.svg -resize 48x48 icon48.png
convert -background none icon.svg -resize 128x128 icon128.png
```

### Using Inkscape

```bash
inkscape icon.svg -w 16 -h 16 -o icon16.png
inkscape icon.svg -w 48 -h 48 -o icon48.png
inkscape icon.svg -w 128 -h 128 -o icon128.png
```

### Online Tools

1. Go to https://svgtopng.com/
2. Upload `icon.svg`
3. Download at 16px, 48px, and 128px sizes

## Temporary Placeholder

For testing without icons, you can temporarily remove the icon references from `manifest.json`:

```json
{
  "action": {
    "default_popup": "src/popup/popup.html",
    "default_title": "PR Buddy"
  }
}
```

Chrome will use a default puzzle piece icon.
