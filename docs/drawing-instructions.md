# S-101 Drawing Instructions Reference

Complete reference of every drawing instruction type emitted by the S-101 Portrayal Catalogue Lua rules.

## Overview

Drawing instructions (DIs) are the output of the S-101 portrayal pipeline. For each chart feature, a Lua rule script builds up a string of drawing instructions that tell the renderer how to display it. The instructions flow through the pipeline as:

```
Lua rule script
  → featurePortrayal:AddInstructions('...')  (accumulates instruction fragments)
  → table.concat(DrawingInstructions, ';')   (joins all fragments)
  → HostPortrayalEmit(featureRef, diString)  (sends to host)
```

### Encoding Format

Instructions use a semicolon-delimited string format with colon-separated key-value pairs:

```
ViewingGroup:27010;DrawingPriority:24;DisplayPlane:OverRadar;PointInstruction:BOYCAR01
```

- **Semicolons** (`;`) separate instructions
- **Colons** (`:`) separate instruction name from parameters
- **Commas** (`,`) separate multiple parameters within an instruction
- Special characters in text values are escaped using **DEF encoding** (see [DEF String Encoding](#def-string-encoding))

A single feature may emit multiple `AddInstructions` calls. These are concatenated with semicolons before being passed to `HostPortrayalEmit`.

---

## Instruction Reference

### Display Control

#### ViewingGroup
Controls which viewing group(s) the instruction belongs to. Determines visibility based on mariner display settings.

```
ViewingGroup:<group_id>[,<additional_group_id>...]
```

- `<group_id>` — integer viewing group number (e.g., 13030, 21010, 27070)
- Multiple groups can be comma-separated

```lua
featurePortrayal:AddInstructions('ViewingGroup:27010')
featurePortrayal:AddInstructions('ViewingGroup:13030;DrawingPriority:3;DisplayPlane:UnderRadar')
featurePortrayal:AddInstructions('ViewingGroup:27070,90020;DrawingPriority:24;PointInstruction:INFORM01')
```

#### DrawingPriority
Sets the z-order for rendering. Higher values draw on top of lower values.

```
DrawingPriority:<int>
```

```lua
featurePortrayal:AddInstructions('DrawingPriority:15')
featurePortrayal:AddInstructions('DrawingPriority:24')
```

Typical range: 0–24.

#### DisplayPlane
Controls whether the feature renders above or below the radar overlay.

```
DisplayPlane:<OverRadar|UnderRadar>
```

```lua
featurePortrayal:AddInstructions('DisplayPlane:OverRadar')
featurePortrayal:AddInstructions('DisplayPlane:UnderRadar')
```

Most features use `UnderRadar`. Aids to navigation and lights typically use `OverRadar` when the radar overlay is active.

#### ScaleMinimum
Feature is hidden when the display scale denominator exceeds this value (i.e., when zoomed out beyond this scale).

```
ScaleMinimum:<int>
```

```lua
featurePortrayal:AddInstructions('ScaleMinimum:' .. scaleMinimum)
```

Added automatically by `main.lua` from the feature's `scaleMinimum` attribute when `IgnoreScaleMinimum` is false.

#### ScaleMaximum
Feature is hidden when the display scale denominator is less than this value (i.e., when zoomed in past this scale).

```
ScaleMaximum:<int>
```

```lua
featurePortrayal:AddInstructions('ScaleMaximum:' .. scaleMaximum)
```

Added automatically by `main.lua` from the feature's `scaleMaximum` attribute.

---

### Point / Symbol

#### PointInstruction
Renders a symbol at a point location. References a symbol name from the portrayal catalogue's `Symbols/` directory.

```
PointInstruction:<symbol_name>
```

```lua
featurePortrayal:AddInstructions('PointInstruction:QUESMRK1')  -- Unknown/default
featurePortrayal:AddInstructions('PointInstruction:BOYCAR01')  -- Cardinal buoy
featurePortrayal:AddInstructions('PointInstruction:LIGHTS82')  -- Light
featurePortrayal:AddInstructions('PointInstruction:INFORM01')  -- Information symbol
featurePortrayal:AddInstructions('PointInstruction:CHDATD01')  -- Date-dependent symbol
```

330+ unique symbol names are referenced across the rule files.

---

### Line

#### LineInstruction
Renders a styled line using a named line style from `LineStyles/*.xml`. Also used with the special `_simple_` keyword for inline-defined simple line styles.

```
LineInstruction:<style_name>
```

```lua
featurePortrayal:AddInstructions('LineInstruction:QUESMRK1')    -- Question mark line
featurePortrayal:AddInstructions('LineInstruction:LOWACC21')    -- Low accuracy boundary
featurePortrayal:AddInstructions('LineInstruction:RECTRC12')    -- Recommended track
featurePortrayal:AddInstructions('LineInstruction:_simple_')    -- Uses preceding LineStyle/Dash
```

When `_simple_` is used, the line appearance is defined by a preceding `LineStyle` (and optionally `Dash`) instruction. When a named style is used, it references an XML definition in `LineStyles/`.

59 named line style XMLs exist in `portrayal/PortrayalCatalog/LineStyles/`.

#### LineInstructionUnsuppressed
Same as `LineInstruction` but cannot be suppressed by mariner display settings.

```
LineInstructionUnsuppressed:<style_name>
```

```lua
featurePortrayal:AddInstructions('LineInstructionUnsuppressed:CHRVID02')
featurePortrayal:AddInstructions('LineInstructionUnsuppressed:CHRVDEL2')
featurePortrayal:AddInstructions('LineInstructionUnsuppressed:_simple_')
```

Used primarily for chart revision indicators and other mandatory display elements.

#### LineStyle
Defines an inline simple line style. Used with `LineInstruction:_simple_`.

```
LineStyle:_simple_,[<dash_length>,]<width>,<colour_token>
```

- `_simple_` — marker indicating inline definition
- `<dash_length>` — total dash+gap length (only present for dashed/dotted lines)
- `<width>` — line width in mm (S-52 units; width 2 ≈ 0.64mm)
- `<colour_token>` — IHO colour token name

```lua
-- solid line:
featurePortrayal:AddInstructions('LineStyle:_simple_,,0.64,CSTLN')
-- dashed line (with Dash):
featurePortrayal:AddInstructions('Dash:0,3.6;LineStyle:_simple_,5.4,0.32,CHMGD')
-- dotted line (with Dash):
featurePortrayal:AddInstructions('Dash:0,0.6;LineStyle:_simple_,1.8,0.32,CHMGD')
```

Generated by the `SimpleLineStyle()` helper method.

#### Dash
Defines the dash pattern for a subsequent `LineStyle:_simple_` instruction.

```
Dash:<offset>,<dash_length>
```

- `<offset>` — starting offset into the pattern
- `<dash_length>` — length of the visible dash segment

```lua
featurePortrayal:AddInstructions('Dash:0,3.6;LineStyle:_simple_,5.4,0.32,CHMGD')  -- dash
featurePortrayal:AddInstructions('Dash:0,0.6;LineStyle:_simple_,1.8,0.32,CHMGD')  -- dot
featurePortrayal:AddInstructions('Dash:2,6;LineStyle:_simple_,8,0.32,CHMGF')      -- custom
```

#### SimpleLineStyle (helper method)
Not an instruction itself — a Lua helper that emits `Dash` + `LineStyle` instructions.

```lua
featurePortrayal:SimpleLineStyle('solid', 0.64, 'CSTLN')
-- emits: LineStyle:_simple_,,0.64,CSTLN

featurePortrayal:SimpleLineStyle('dash', 0.32, 'CHMGD')
-- emits: Dash:0,3.6;LineStyle:_simple_,5.4,0.32,CHMGD

featurePortrayal:SimpleLineStyle('dot', 0.32, 'CHMGD')
-- emits: Dash:0,0.6;LineStyle:_simple_,1.8,0.32,CHMGD
```

---

### Area Fill

#### ColorFill
Fills an area with a solid colour, optionally with transparency.

```
ColorFill:<colour_token>[,<opacity>]
```

- `<colour_token>` — IHO colour token name (e.g., DEPIT, DEPVS, NODTA)
- `<opacity>` — optional float 0.0–1.0 (default 1.0 = fully opaque)

```lua
featurePortrayal:AddInstructions('ColorFill:NODTA')          -- Fully opaque
featurePortrayal:AddInstructions('ColorFill:DEPIT')          -- Depth area
featurePortrayal:AddInstructions('ColorFill:NODTA,0.5')      -- 50% transparent
featurePortrayal:AddInstructions('ColorFill:CHGRF,0.5')      -- 50% transparent
featurePortrayal:AddInstructions('ColorFill:TRFCF,0.75')     -- 75% opaque
```

#### AreaFillReference
Fills an area with a named pattern from `AreaFills/*.xml`.

```
AreaFillReference:<pattern_name>
```

```lua
featurePortrayal:AddInstructions('AreaFillReference:PRTSUR01')  -- Port survey area
featurePortrayal:AddInstructions('AreaFillReference:MARSHES1')  -- Marshes
featurePortrayal:AddInstructions('AreaFillReference:DRGARE01')  -- Dredged area
featurePortrayal:AddInstructions('AreaFillReference:TSSJCT02')  -- TSS junction
```

25 named area fill XMLs exist in `portrayal/PortrayalCatalog/AreaFills/`.

#### AreaPlacement
Controls how labels/symbols are placed within areas.

```
AreaPlacement:<mode>
```

```lua
featurePortrayal:AddInstructions('AreaPlacement:VisibleParts')
```

#### AreaCRS
Specifies the coordinate reference system for area geometry operations.

```
AreaCRS:<crs_type>
```

```lua
featurePortrayal:AddInstructions('AreaCRS:GlobalGeometry')
```

---

### Text

#### TextInstruction
Renders text at a feature location. The text parameter is DEF-encoded.

```
TextInstruction:<encoded_text>
```

```lua
-- Generated by AddTextInstruction(), always preceded by ViewingGroup and DrawingPriority:
'ViewingGroup:23,27070;DrawingPriority:24;TextInstruction:Fl(2)W&m10s'
```

The `AddTextInstruction()` method wraps text with viewing group and priority. The text content is DEF-encoded (see [DEF String Encoding](#def-string-encoding)).

#### TextAlignHorizontal
Horizontal alignment of text relative to the placement point.

```
TextAlignHorizontal:<Start|Center|End>
```

```lua
featurePortrayal:AddInstructions('TextAlignHorizontal:Start')
featurePortrayal:AddInstructions('TextAlignHorizontal:Center')
featurePortrayal:AddInstructions('TextAlignHorizontal:End')
```

#### TextAlignVertical
Vertical alignment of text relative to the placement point.

```
TextAlignVertical:<Top|Center|Bottom>
```

```lua
featurePortrayal:AddInstructions('TextAlignVertical:Top')
featurePortrayal:AddInstructions('TextAlignVertical:Center')
featurePortrayal:AddInstructions('TextAlignVertical:Bottom')
```

#### TextVerticalOffset
Vertical offset applied to stacked text labels (e.g., multiple co-located features).

```
TextVerticalOffset:<offset_mm>
```

```lua
featurePortrayal:AddInstructions('TextVerticalOffset:' .. textOffsetLines * -3.51)
```

Typically used in multiples of -3.51 (one text line height).

---

### Font Styling

#### FontColor
Colour of text, using an IHO colour token.

```
FontColor:<colour_token>
```

```lua
featurePortrayal:AddInstructions('FontColor:CHBLK')
```

`CHBLK` (chart black) is the most common value.

#### FontSize
Text size in points.

```
FontSize:<int>
```

```lua
featurePortrayal:AddInstructions('FontSize:10')
```

Default is 10.

#### FontWeight
Text weight (boldness).

```
FontWeight:<Light|Medium|Bold>
```

```lua
featurePortrayal:AddInstructions('FontWeight:Light')
```

Default is `Medium`.

#### FontSlant
Text slant (italic).

```
FontSlant:<Upright|Italics>
```

```lua
featurePortrayal:AddInstructions('FontSlant:Italics')
```

Default is `Upright`.

#### FontProportion
Text spacing mode.

```
FontProportion:<Proportional|MonoSpaced>
```

Default is `Proportional`. Referenced in `PortrayalModel.lua` but not commonly set explicitly in rules.

#### FontSerifs
Whether the font has serifs.

```
FontSerifs:<true|false>
```

Default is `false`. Referenced in `PortrayalModel.lua` text copy logic.

#### FontUnderline
Whether text is underlined.

```
FontUnderline:<true|false>
```

Default is `false`. Referenced in `PortrayalModel.lua` text copy logic.

#### FontStrikethrough
Whether text has a strikethrough.

```
FontStrikethrough:<true|false>
```

Default is `false`. Referenced in `PortrayalModel.lua` text copy logic.

#### FontUpperline
Whether text has an overline.

```
FontUpperline:<true|false>
```

Default is `false`. Referenced in `PortrayalModel.lua` text copy logic.

#### FontReference
Reference to a named font.

```
FontReference:<font_name>
```

Default is empty string. Referenced in `PortrayalModel.lua` text copy logic.

#### FontBackgroundColor
Background colour behind text.

```
FontBackgroundColor:<colour_token>[,<transparency>]
```

Default is no background (transparency=1). Referenced in `PortrayalModel.lua` text copy logic.

---

### Geometry / Transform

#### LocalOffset
Offsets the placement point by X,Y in portrayal coordinate units (mm).

```
LocalOffset:<x>,<y>
```

```lua
featurePortrayal:AddInstructions('LocalOffset:7.02,0')       -- Right of feature
featurePortrayal:AddInstructions('LocalOffset:-3.51,3.51')    -- Upper-left
featurePortrayal:AddInstructions('LocalOffset:0,3.51')        -- Above
featurePortrayal:AddInstructions('LocalOffset:0,-3.51')       -- Below
featurePortrayal:AddInstructions('LocalOffset:0,0')           -- Reset
```

#### Rotation
Rotates the symbol/text by an angle in a specified CRS.

```
Rotation:<crs>,<angle_degrees>
```

- `<crs>` — `PortrayalCRS` (screen-relative) or `GeographicCRS` (true north)
- `<angle_degrees>` — rotation in degrees

```lua
featurePortrayal:AddInstructions('Rotation:PortrayalCRS,0')           -- No rotation
featurePortrayal:AddInstructions('Rotation:GeographicCRS,' .. angle)  -- True north rotation
```

#### ScaleFactor
Multiplier applied to symbol/text size.

```
ScaleFactor:<float>
```

```lua
featurePortrayal:AddInstructions('ScaleFactor:1')  -- Normal size
```

#### LinePlacement
Controls how a symbol or label is placed along a line geometry.

```
LinePlacement:<mode>,<position>[,<gap>,<initial>]
```

- `<mode>` — `Relative` (proportional along line)
- `<position>` — 0.0–1.0 (0 = start, 0.5 = midpoint, 1 = end)
- `<gap>` — optional gap between repeated placements
- `<initial>` — optional boolean, `true` to place at line start

```lua
featurePortrayal:AddInstructions('LinePlacement:Relative,0.5')
featurePortrayal:AddInstructions('LinePlacement:Relative,0.5,,true')
featurePortrayal:AddInstructions('LinePlacement:Relative,1')
```

#### ClearGeometry
Clears the current geometry buffer. Used when a rule needs to switch from one geometry context to another (e.g., from line rendering to point text placement).

```
ClearGeometry
```

(No parameters.)

```lua
featurePortrayal:AddInstructions('ClearGeometry')
featurePortrayal:AddInstructions('LineInstruction:_simple_;ClearGeometry')
featurePortrayal:AddInstructions('ClearGeometry;FontColor:CHBLK')
```

#### SpatialReference
References a specific spatial object (curve/surface) by ID. Used when a feature has multiple spatial associations and needs per-edge styling.

```
SpatialReference:<encoded_spatial_id>[,false]
```

- `<encoded_spatial_id>` — DEF-encoded spatial object ID
- `,false` — appended when orientation is Reverse (omitted for Forward)

```lua
-- Generated by AddSpatialReference():
featurePortrayal:AddSpatialReference(curveAssociation)
-- emits: SpatialReference:<id> or SpatialReference:<id>,false
```

Used extensively in shoreline construction (SLCONS04.lua) and other features with per-edge styling.

#### AugmentedPoint
Adds a geographic point to the geometry buffer.

```
AugmentedPoint:GeographicCRS,<lon>,<lat>
```

```lua
featurePortrayal:AddInstructions('AugmentedPoint:GeographicCRS,' .. point.X .. ',' .. point.Y)
```

Used in sounding rendering (SOUNDG03.lua) and DepthNoBottomFound.lua for multipoint features where each point needs individual treatment.

#### AugmentedRay
Adds a ray (directed line segment) to the geometry buffer. Used for light sector arcs and text offset positioning.

```
AugmentedRay:<start_crs>,<angle>,<end_crs>,<length>
```

- `<start_crs>` — CRS for the angle (`GeographicCRS` for true bearing)
- `<angle>` — direction in degrees
- `<end_crs>` — CRS for the length (`PortrayalCRS` for mm, `GeographicCRS` for geographic units)
- `<length>` — ray length

```lua
-- Light sector limit line:
featurePortrayal:AddInstructions('AugmentedRay:GeographicCRS,' .. sectorLimit .. ',GeographicCRS,' .. length)
-- Text offset positioning:
featurePortrayal:AddInstructions('AugmentedRay:GeographicCRS,' .. direction .. ',PortrayalCRS,' .. distance)
```

#### AugmentedPath
Connects the current geometry buffer points into a path/line.

```
AugmentedPath:<start_crs>,<segment_crs>,<end_crs>
```

```lua
featurePortrayal:AddInstructions('AugmentedPath:LocalCRS,LocalCRS,LocalCRS')
featurePortrayal:AddInstructions('AugmentedPath:LocalCRS,GeographicCRS,LocalCRS')
```

Used after `AugmentedRay` or `ArcByRadius` to form closed shapes for light sectors.

#### ArcByRadius
Adds a circular arc to the geometry buffer.

```
ArcByRadius:<cx>,<cy>,<radius>,<start_angle>,<end_angle>
```

- `<cx>,<cy>` — center point (typically 0,0 for feature-relative)
- `<radius>` — arc radius in portrayal units
- `<start_angle>` — start angle in degrees (0 = north, clockwise)
- `<end_angle>` — end angle in degrees

```lua
featurePortrayal:AddInstructions('ArcByRadius:0,0,26,0,360')   -- Full circle (major light)
featurePortrayal:AddInstructions('ArcByRadius:0,0,25,0,360')   -- Full circle
featurePortrayal:AddInstructions('ArcByRadius:0,0,20,' .. startAngle .. ',' .. endAngle)  -- Arc sector
```

Used for light halos and sector indicators.

---

### Alerts / Interaction

#### AlertReference
Associates the feature with an alert/hazard system for safety highlighting.

```
AlertReference:<alert_type>[,<group1>,<group2>]
```

- `<alert_type>` — `NavHazard`, `SafetyContour`, or area-specific like `ProhAre`
- `<group1>,<group2>` — optional viewing group numbers for the alert

```lua
featurePortrayal:AddInstructions('AlertReference:NavHazard')
featurePortrayal:AddInstructions('AlertReference:SafetyContour')
featurePortrayal:AddInstructions('AlertReference:ProhAre,53017,53017')
featurePortrayal:AddInstructions('AlertReference:ProhAre,53012,53012')
```

#### Hover
Enables hover/pick interaction for the feature.

```
Hover:<true|false>
```

```lua
featurePortrayal:AddInstructions('Hover:true')
```

When `true`, the feature can be picked/hovered for information display. Commonly paired with `AlertReference`.

---

### Temporal

These instructions control time-dependent visibility of features (seasonal aids to navigation, temporary restrictions, etc.).

#### Date
Specifies a date or date range for temporal validity.

```
Date:<start_date>,<end_date>
Date:<start_date>
Date:,<end_date>
```

Dates are in ISO format (YYYY-MM-DD or similar). Either start or end can be omitted for semi-intervals.

```lua
featurePortrayal:AddInstructions('Date:' .. dateStart .. ',' .. dateEnd .. ';TimeValid:closedInterval')
featurePortrayal:AddInstructions('Date:' .. dateStart .. ';TimeValid:geSemiInterval')
featurePortrayal:AddInstructions('Date:,' .. dateEnd .. ';TimeValid:leSemiInterval')
```

#### TimeValid
Specifies the type of temporal validity interval. Always follows a `Date` instruction.

```
TimeValid:<interval_type>
```

- `closedInterval` — feature valid between start and end dates
- `geSemiInterval` — feature valid from start date onward
- `leSemiInterval` — feature valid up to end date

#### ClearTime
Clears all accumulated temporal validity settings. Used when a rule needs to reset the time state before adding new temporal instructions.

```
ClearTime
```

(No parameters.)

Referenced in `PortrayalModel.lua` text copy logic for TextPlacement processing.

#### Time / DateTime
Additional temporal specification types. Referenced in the `PortrayalModel.lua` time command copy logic but not directly emitted by current rule files.

```
Time:<time_spec>
DateTime:<datetime_spec>
```

---

### Special

#### NullInstruction
Renders nothing. Used when a feature must be registered for pick/interaction purposes but has no visible rendering.

```
NullInstruction
```

(No parameters.)

```lua
featurePortrayal:AddInstructions('ViewingGroup:31010;DrawingPriority:0;DisplayPlane:UnderRadar;NullInstruction')
featurePortrayal:AddInstructions('ViewingGroup:27040;DrawingPriority:12;DisplayPlane:UnderRadar;NullInstruction')
```

---

## DEF String Encoding

Text values embedded in drawing instructions may contain characters that conflict with the instruction delimiter format. The DEF encoding escapes these:

| Character | Escape Sequence |
|-----------|----------------|
| `&` | `&a` |
| `;` | `&s` |
| `:` | `&c` |
| `,` | `&m` |

**Encoding** (applied in order): `&` → `&a`, `;` → `&s`, `:` → `&c`, `,` → `&m`

**Decoding** (applied in order): `&s` → `;`, `&c` → `:`, `&m` → `,`, `&a` → `&`

Note: Decoding order differs from encoding order — `&a` must be decoded last to avoid double-unescaping.

Examples from the Lua unit tests:

| Input | Encoded |
|-------|---------|
| `Hello, World!` | `Hello&m World!` |
| `Foo:bar` | `Foo&cbar` |
| `This & that` | `This &a that` |
| `Double ampersand &&` | `Double ampersand &a&a` |

The `EncodeString()` function in `S100Scripting.lua` handles formatting values and applying DEF encoding. It is used to encode text passed to `TextInstruction`.

---

## Real Examples

### DepthArea (Surface feature)

A typical depth area with safety contour alert:

```
ScaleMinimum:90000;ViewingGroup:13030;DrawingPriority:3;DisplayPlane:UnderRadar;AlertReference:SafetyContour;ColorFill:DEPVS;LineInstruction:SOLD,0.64,DEPSC
```

An incompletely surveyed depth area:

```
ViewingGroup:13030;DrawingPriority:3;DisplayPlane:UnderRadar;ColorFill:NODTA;AreaFillReference:PRTSUR01;LineStyle:_simple_,,0.64,CHGRD;LineInstruction:_simple_
```

### LightAllAround (Point feature, major light)

```
ViewingGroup:27070;DrawingPriority:24;DisplayPlane:OverRadar;Hover:true;ArcByRadius:0,0,26,0,360;AugmentedPath:LocalCRS,LocalCRS,LocalCRS;LineStyle:_simple_,,1.28,OUTLW;LineInstruction:_simple_;LineStyle:_simple_,,0.64,LITRD;LineInstruction:_simple_;ClearGeometry;FontColor:CHBLK;LocalOffset:7.02,0;TextAlignHorizontal:Start;TextAlignVertical:Center;ViewingGroup:23,27070;DrawingPriority:24;TextInstruction:Fl(2)R&m10s
```

### Default (Unknown feature, surface with plain boundaries)

```
ViewingGroup:21010;DrawingPriority:15;DisplayPlane:UnderRadar;PointInstruction:QUESMRK1;Dash:0,3.6;LineStyle:_simple_,5.4,0.32,CHMGD;LineInstruction:_simple_
```

### ShorelineConstruction (Curve feature with per-edge styling)

```
ViewingGroup:12410;DrawingPriority:15;DisplayPlane:UnderRadar;SpatialReference:spatial_001;LineStyle:_simple_,,0.64,CSTLN;LineInstruction:_simple_;ClearGeometry;SpatialReference:spatial_002;LineInstruction:LOWACC21;ClearGeometry
```

### Date-dependent feature

```
Date:2024-04-01,2024-10-31;TimeValid:closedInterval;ViewingGroup:17020;DrawingPriority:15;DisplayPlane:UnderRadar;PointInstruction:BUOYSP01;LocalOffset:0,0;LinePlacement:Relative,0.5;AreaPlacement:VisibleParts;AreaCRS:GlobalGeometry;Rotation:PortrayalCRS,0;ScaleFactor:1;ClearGeometry;Hover:true;DisplayPlane:OverRadar;ViewingGroup:17020,90022;DrawingPriority:24;PointInstruction:CHDATD01
```

### Sounding (MultiPoint with AugmentedPoint)

```
ViewingGroup:33010;DrawingPriority:15;DisplayPlane:UnderRadar;AugmentedPoint:GeographicCRS,1.234,56.789;FontSize:10;FontColor:SNDG2;TextAlignHorizontal:Center;TextAlignVertical:Center;ViewingGroup:33,33010;DrawingPriority:24;TextInstruction:12&m5
```

### Reset sequence (before nautical information / date symbols)

The framework adds this reset sequence before placing additional symbols on a feature:

```
LocalOffset:0,0;LinePlacement:Relative,0.5;AreaPlacement:VisibleParts;AreaCRS:GlobalGeometry;Rotation:PortrayalCRS,0;ScaleFactor:1;ClearGeometry
```

This clears all transform state (offset, placement mode, rotation, scale) and geometry, providing a clean slate for the next rendering instruction.

---

## Resource Catalogues

### Area Fill Patterns (25 files in `AreaFills/`)

AIRARE02, DIAMOND1, DQUALA11, DQUALA21, DQUALB01, DQUALC01, DQUALD01, DQUALU01, DRGARE01, FOULAR01, FSHFAC03, FSHFAC04, FSHHAV02, ICEARE04, MARCUL02, MARSHES1, NODATA03, OVERSC01, PRTSUR01, QUESMRK1, RCKLDG01, SNDWAV01, TSSJCT02, VEGATN03, VEGATN04

### Line Styles (59 files in `LineStyles/`)

ACHARE51, ACHRES51, ADMARE01, ARCSLN01, CBLARE51, CBLSUB06, CHCRDEL1, CHCRID01, CHRVDEL2, CHRVID02, COLREG01, CTNARE51, CTYARE51, CURENT01, DSCWTR51, DWLDEF01, DWRTCL05, DWRTCL06, DWRTCL07, DWRTCL08, DWRUTE51, ENTRES51, ERBLNA01, ESSARE01, FERYRT01, FERYRT02, FOULGRD1, FSHFAC02, FSHRES51, INDHLT02, INFARE51, LOWACC21, LOWACC31, LOWACC41, MARSYS51, NAVARE51, NAVARE52, NONHODAT, PILPNT01, PIPARE51, PIPARE61, PIPSOL05, PIPSOL06, PRCARE51, QUESMRK1, RCRDEF11, RCRTCL11, RCRTCL12, RCRTCL13, RCRTCL14, RECDEF02, RECTRC09, RECTRC10, RECTRC11, RECTRC12, RESARE51, SCLBDY51, TIDINF51, VTSARE51
