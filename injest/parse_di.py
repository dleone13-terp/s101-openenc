from dataclasses import dataclass, field
from typing import Optional

@dataclass
class DrawingInstructions:
    """Parsed output of one HostPortrayalEmit call."""
    vg: Optional[int] = None          # ViewingGroup
    dp: Optional[int] = None          # DrawingPriority
    ac: Optional[str] = None          # AreaColour token
    ap: Optional[str] = None          # AreaPattern symbol ref
    lc: Optional[str] = None          # LineColour token
    ls: Optional[str] = None          # LineStyle ref
    lw: Optional[float] = None        # LineWidth mm
    sy: Optional[str] = None          # Symbol reference
    sy_rot: Optional[float] = None    # Symbol rotation degrees
    sy_rot_type: Optional[str] = None
    texts: list = field(default_factory=list)  # list of TextInstruction dicts


def parse_drawing_instructions(di_string: str) -> DrawingInstructions:
    """
    Parse the semicolon-delimited Drawing Instructions string produced
    by the S-101 Portrayal Catalogue Lua rules via HostPortrayalEmit.

    Instruction codes used by S-101 PC:
      VG:<int>                  ViewingGroup
      DP:<int>                  DrawingPriority
      AC:<token>                AreaColour fill token
      AP:<symref>               AreaPattern symbol
      LC:<token>                LineColour token
      LS:<style>,<width>,<token> LineStyle (style name, width mm, colour token)
      SY:<symref>[,<rot>]       Symbol reference, optional rotation degrees
      TX:<text>,<ox>,<oy>,<hjust>,<colour>,<size>  Text
      CS:<proc>                 Conditional symbology procedure (ignore for ingest)
    """
    di = DrawingInstructions()
    if not di_string:
        return di

    for token in di_string.split(';'):
        token = token.strip()
        if not token or ':' not in token:
            continue

        code, _, value = token.partition(':')
        code = code.strip().upper()
        value = value.strip()

        if code == 'VG':
            di.vg = int(value)
        elif code == 'DP':
            di.dp = int(value)
        elif code == 'AC':
            di.ac = value
        elif code == 'AP':
            di.ap = value
        elif code == 'LC':
            di.lc = value
        elif code == 'LS':
            # LS:SOLD,1.0,CHBLK  or  LS:DASH,0.7,CHMGF
            parts = value.split(',')
            di.ls = parts[0] if len(parts) > 0 else None
            di.lw = float(parts[1]) if len(parts) > 1 else None
            di.lc = parts[2] if len(parts) > 2 else di.lc
        elif code == 'SY':
            parts = value.split(',')
            di.sy = parts[0]
            if len(parts) > 1:
                try:
                    di.sy_rot = float(parts[1])
                    di.sy_rot_type = 'TrueNorth'
                except ValueError:
                    di.sy_rot_type = parts[1]
        elif code == 'TX':
            parts = value.split(',', 5)
            di.texts.append({
                'text':   parts[0] if len(parts) > 0 else '',
                'offset_x': float(parts[1]) if len(parts) > 1 else 0.0,
                'offset_y': float(parts[2]) if len(parts) > 2 else 0.0,
                'hjust':  parts[3] if len(parts) > 3 else '1',
                'colour': parts[4] if len(parts) > 4 else 'CHBLK',
                'size':   int(parts[5]) if len(parts) > 5 else 10,
            })
        # CS: conditional symbology - resolved by the Lua rules themselves; ignore here

    return di