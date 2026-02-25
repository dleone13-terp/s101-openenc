# Usage

## Sprite Generation

```bash
python -m sprites.build_sprites
```

This will create all of the sprites in colored svg format in the sprites/out/{Theme}_src directory and the png sprite map with sprite json in the sprites/out/{Theme} directory. This includes both regular and @2x versions.

## Style Generation

```bash
python -m style.build_style
```

This will create the three styles in style/out/{Theme}.json
