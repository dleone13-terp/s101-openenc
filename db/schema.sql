-- ============================================================
-- AREAS  (polygons: DEPARE, LNDARE, RESARE, DRGARE, ...)
-- ============================================================
CREATE TABLE enc_area (
    id              BIGSERIAL PRIMARY KEY,
    foid            TEXT NOT NULL UNIQUE,   -- S-101 Feature Object Identifier
    feature_code    TEXT NOT NULL,          -- e.g. 'DepthArea'
    cell_file       TEXT NOT NULL,

    geom            GEOMETRY(MultiPolygon, 4326) NOT NULL,

    -- From Drawing Instructions
    di_viewing_group    INTEGER,               -- viewing group
    di_drawing_priority SMALLINT,              -- display priority
    di_color_fill       TEXT,                  -- area colour token  e.g. 'DEPDW'
    di_area_pattern     TEXT,                  -- area pattern symbol ref
    di_line_color       TEXT,                  -- line colour token
    di_line_style       TEXT,                  -- line style reference
    di_line_width       NUMERIC(4,1),          -- line width (mm)

    display_plane       TEXT    DEFAULT 'UnderRadar',
    scale_min           INTEGER,
    scale_max           INTEGER,
    di_color_fill_alpha NUMERIC(4,3),
    di_dash_offset      NUMERIC(5,2),
    di_dash_length      NUMERIC(5,2),

    -- Raw important attributes for client-side depth expressions
    drval1          NUMERIC(8,2),
    drval2          NUMERIC(8,2)
);
CREATE INDEX ON enc_area USING GIST (geom);
CREATE INDEX ON enc_area (di_viewing_group);

-- ============================================================
-- LINES  (contours, boundaries, routes, cables, ...)
-- ============================================================
CREATE TABLE enc_line (
    id              BIGSERIAL PRIMARY KEY,
    foid            TEXT NOT NULL UNIQUE,
    feature_code    TEXT NOT NULL,
    cell_file       TEXT NOT NULL,

    geom            GEOMETRY(MultiLineString, 4326) NOT NULL,

    di_viewing_group    INTEGER,
    di_drawing_priority SMALLINT,
    di_line_color       TEXT,                  -- line colour token
    di_line_style       TEXT,                  -- line style ref
    di_line_width       NUMERIC(4,1),
    di_color_fill       TEXT,                  -- fill colour for closed lines used as area outlines
    display_plane       TEXT    DEFAULT 'UnderRadar',
    scale_min           INTEGER,
    scale_max           INTEGER,
    di_dash_offset      NUMERIC(5,2),
    di_dash_length      NUMERIC(5,2)
);
CREATE INDEX ON enc_line USING GIST (geom);
CREATE INDEX ON enc_line (di_viewing_group);

-- ============================================================
-- POINTS  (buoys, lights, beacons, wrecks, obstructions, ...)
-- ============================================================
CREATE TABLE enc_point (
    id              BIGSERIAL PRIMARY KEY,
    foid            TEXT NOT NULL UNIQUE,
    feature_code    TEXT NOT NULL,
    cell_file       TEXT NOT NULL,

    geom            GEOMETRY(Point, 4326) NOT NULL,

    di_viewing_group        INTEGER,
    di_drawing_priority     SMALLINT,
    di_symbol_ref           TEXT,                  -- symbol reference  e.g. 'LIGHTS81'
    di_symbol_rotation      NUMERIC(6,2),          -- symbol rotation degrees (true north)
    di_symbol_rotation_type TEXT,                  -- 'TrueNorth' | 'PortrayalContext' | NULL
    display_plane           TEXT    DEFAULT 'UnderRadar',
    scale_min               INTEGER,
    scale_max               INTEGER
);
CREATE INDEX ON enc_point USING GIST (geom);
CREATE INDEX ON enc_point (di_viewing_group);
CREATE INDEX ON enc_point (di_symbol_ref);

-- ============================================================
-- SOUNDINGS  (high-volume, treated separately)
-- ============================================================
CREATE TABLE enc_sounding (
    id              BIGSERIAL PRIMARY KEY,
    foid            TEXT NOT NULL,
    cell_file       TEXT NOT NULL,
    geom            GEOMETRY(Point, 4326) NOT NULL,
    depth_m         NUMERIC(8,3) NOT NULL,
    di_viewing_group    INTEGER DEFAULT 33022,
    di_drawing_priority SMALLINT DEFAULT 20
);
CREATE INDEX ON enc_sounding USING GIST (geom);

-- ============================================================
-- TEXT LABELS  (separate so they can be independently toggled)
-- ============================================================
CREATE TABLE enc_label (
    id              BIGSERIAL PRIMARY KEY,
    foid            TEXT NOT NULL,          -- links back to parent feature
    cell_file       TEXT NOT NULL,
    geom            GEOMETRY(Point, 4326) NOT NULL,  -- anchor point

    di_viewing_group    INTEGER,
    di_drawing_priority SMALLINT,
    label_text      TEXT NOT NULL,
    offset_x        NUMERIC(5,2) DEFAULT 0,   -- mm
    offset_y        NUMERIC(5,2) DEFAULT 0,
    font_colour     TEXT,                       -- colour token e.g. 'CHBLK'
    font_size       SMALLINT DEFAULT 10,
    hjust           TEXT    DEFAULT 'Center',
    vjust           TEXT    DEFAULT 'Center'
);
CREATE INDEX ON enc_label USING GIST (geom);