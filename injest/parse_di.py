from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DrawingInstructions:
    """Parsed output of one HostPortrayalEmit call."""
    viewing_group: Optional[int] = None
    drawing_priority: Optional[int] = None
    display_plane: str = 'UnderRadar'
    scale_min: Optional[int] = None
    scale_max: Optional[int] = None
    # Area
    color_fill: Optional[str] = None           # ColorFill token
    color_fill_alpha: Optional[float] = None   # ColorFill transparency (0.0–1.0)
    area_pattern: Optional[str] = None         # AreaFillReference pattern symbol
    # Line / boundary
    line_style: Optional[str] = None           # LineStyle name (e.g. '_simple_')
    line_width: Optional[float] = None         # line width mm
    line_color: Optional[str] = None           # line colour token
    dash_offset: Optional[float] = None        # Dash offset
    dash_length: Optional[float] = None        # Dash length
    # Point symbol
    symbol_ref: Optional[str] = None           # PointInstruction symbol ref
    symbol_rotation: Optional[float] = None    # rotation degrees
    symbol_rotation_type: Optional[str] = None # e.g. 'TrueNorth', 'PortrayalCRS'
    # Interaction
    hover: bool = False
    alert: Optional[str] = None                # AlertReference type
    # Text labels
    texts: list = field(default_factory=list)


def _decode_def(s: str) -> str:
    """Decode S-101 DEFString escape sequences."""
    return s.replace('&s', ';').replace('&c', ':').replace('&m', ',').replace('&a', '&')


def parse_drawing_instructions(di_string: str) -> DrawingInstructions:
    """
    Parse the semicolon-delimited Drawing Instructions string produced
    by the S-101 Portrayal Catalogue Lua rules via HostPortrayalEmit.

    Full-name tokens emitted by the IHO S-101 PC Lua rules:
      ViewingGroup:<int>[,<int>]       Primary viewing group
      DrawingPriority:<int>            Display priority
      DisplayPlane:UnderRadar|OverRadar
      ScaleMinimum:<int>
      ScaleMaximum:<int>
      ColorFill:<token>[,<alpha>]      Solid area fill, optional float alpha
      AreaFillReference:<symref>       Pattern fill
      Dash:<offset>,<length>           Dash parameters (before LineStyle)
      LineStyle:<style>,,<width>,<col> 4-part: style, "", width, colour
      PointInstruction:<symref>        Point symbol
      Rotation:<type>,<degrees>        Symbol rotation
      FontColor:<token>                Text context: colour
      FontSize:<float>                 Text context: size
      LocalOffset:<x>,<y>              Text context: anchor offset
      TextAlignHorizontal:<val>        Text context: hjust
      TextAlignVertical:<val>          Text context: vjust
      TextInstruction:<encoded>        Flush text context → text entry
      AlertReference:<type>            Alert type
      Hover:true|false
    """
    di = DrawingInstructions()
    if not di_string:
        return di

    # Stateful text context, reset after each TextInstruction
    _tc: dict = {
        'colour': 'CHBLK',
        'size': 10.0,
        'offset_x': 0.0,
        'offset_y': 0.0,
        'hjust': 'Center',
        'vjust': 'Center',
    }

    for token in di_string.split(';'):
        token = token.strip()
        if not token or ':' not in token:
            continue

        key, _, val = token.partition(':')
        key = key.strip()
        val = val.strip()

        if key == 'ViewingGroup':
            # May be comma-separated; take the first (primary) group
            try:
                di.viewing_group = int(val.split(',')[0])
            except ValueError:
                pass

        elif key == 'DrawingPriority':
            try:
                di.drawing_priority = int(val)
            except ValueError:
                pass

        elif key == 'DisplayPlane':
            di.display_plane = val

        elif key == 'ScaleMinimum':
            try:
                di.scale_min = int(val)
            except ValueError:
                pass

        elif key == 'ScaleMaximum':
            try:
                di.scale_max = int(val)
            except ValueError:
                pass

        elif key == 'ColorFill':
            parts = val.split(',')
            di.color_fill = parts[0]
            if len(parts) > 1:
                try:
                    di.color_fill_alpha = float(parts[1])
                except ValueError:
                    pass

        elif key == 'AreaFillReference':
            di.area_pattern = val

        elif key == 'Dash':
            parts = val.split(',')
            try:
                di.dash_offset = float(parts[0])
                di.dash_length = float(parts[1]) if len(parts) > 1 else None
            except ValueError:
                pass

        elif key == 'LineStyle':
            # Format: <style>,,<width>,<colour>  (4 fields; index 1 is empty)
            parts = val.split(',')
            if len(parts) >= 4:
                di.line_style = parts[0]
                try:
                    di.line_width = float(parts[-2])
                except ValueError:
                    pass
                di.line_color = parts[-1]
            elif len(parts) == 3:
                # Fallback: style,width,colour
                di.line_style = parts[0]
                try:
                    di.line_width = float(parts[1])
                except ValueError:
                    pass
                di.line_color = parts[2]

        elif key == 'PointInstruction':
            di.symbol_ref = val

        elif key == 'Rotation':
            parts = val.split(',')
            if len(parts) >= 2:
                di.symbol_rotation_type = parts[0]
                try:
                    di.symbol_rotation = float(parts[1])
                except ValueError:
                    pass

        elif key == 'FontColor':
            _tc['colour'] = val

        elif key == 'FontSize':
            try:
                _tc['size'] = float(val)
            except ValueError:
                pass

        elif key == 'LocalOffset':
            parts = val.split(',')
            try:
                _tc['offset_x'] = float(parts[0])
                _tc['offset_y'] = float(parts[1]) if len(parts) > 1 else 0.0
            except ValueError:
                pass

        elif key == 'TextAlignHorizontal':
            _tc['hjust'] = val

        elif key == 'TextAlignVertical':
            _tc['vjust'] = val

        elif key == 'TextInstruction':
            decoded = _decode_def(val)
            if decoded:
                di.texts.append({
                    'text':     decoded,
                    'offset_x': _tc['offset_x'],
                    'offset_y': _tc['offset_y'],
                    'colour':   _tc['colour'],
                    'size':     _tc['size'],
                    'hjust':    _tc['hjust'],
                    'vjust':    _tc['vjust'],
                })
            # Reset offset/alignment (colour and size persist until next FontColor/FontSize)
            _tc['offset_x'] = 0.0
            _tc['offset_y'] = 0.0
            _tc['hjust'] = 'Center'
            _tc['vjust'] = 'Center'

        elif key == 'AlertReference':
            if val:
                di.alert = val

        elif key == 'Hover':
            di.hover = val.lower() == 'true'

        # All other tokens silently ignored

    return di
