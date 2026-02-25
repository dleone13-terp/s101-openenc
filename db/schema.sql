-- ============================================================
-- AREAS  (polygons: DEPARE, LNDARE, RESARE, DRGARE, ...)
-- ============================================================
CREATE TABLE enc_area (
    id              BIGSERIAL PRIMARY KEY,
    foid            TEXT NOT NULL,          -- S-101 Feature Object Identifier
    feature_code    TEXT NOT NULL,          -- e.g. 'DepthArea'
    cell_file       TEXT NOT NULL,

    geom            GEOMETRY(MultiPolygon, 4326) NOT NULL,

    -- From Drawing Instructions
    di_vg           INTEGER,               -- viewing group
    di_dp           SMALLINT,              -- display priority
    di_ac           TEXT,                  -- area colour token  e.g. 'DEPDW'
    di_ap           TEXT,                  -- area pattern symbol ref
    di_lc           TEXT,                  -- line colour token
    di_ls           TEXT,                  -- line style reference
    di_lw           NUMERIC(4,1),          -- line width (mm)

    -- Raw important attributes for client-side depth expressions
    drval1          NUMERIC(8,2),
    drval2          NUMERIC(8,2)
);
CREATE INDEX ON enc_area USING GIST (geom);
CREATE INDEX ON enc_area (di_vg);

-- ============================================================
-- LINES  (contours, boundaries, routes, cables, ...)
-- ============================================================
CREATE TABLE enc_line (
    id              BIGSERIAL PRIMARY KEY,
    foid            TEXT NOT NULL,
    feature_code    TEXT NOT NULL,
    cell_file       TEXT NOT NULL,

    geom            GEOMETRY(MultiLineString, 4326) NOT NULL,

    di_vg           INTEGER,
    di_dp           SMALLINT,
    di_lc           TEXT,                  -- line colour token
    di_ls           TEXT,                  -- line style ref
    di_lw           NUMERIC(4,1),
    di_ac           TEXT                   -- fill colour for closed lines used as area outlines
);
CREATE INDEX ON enc_line USING GIST (geom);
CREATE INDEX ON enc_line (di_vg);

-- ============================================================
-- POINTS  (buoys, lights, beacons, wrecks, obstructions, ...)
-- ============================================================
CREATE TABLE enc_point (
    id              BIGSERIAL PRIMARY KEY,
    foid            TEXT NOT NULL,
    feature_code    TEXT NOT NULL,
    cell_file       TEXT NOT NULL,

    geom            GEOMETRY(Point, 4326) NOT NULL,

    di_vg           INTEGER,
    di_dp           SMALLINT,
    di_sy           TEXT,                  -- symbol reference  e.g. 'LIGHTS81'
    di_sy_rot       NUMERIC(6,2),          -- symbol rotation degrees (true north)
    di_sy_rot_type  TEXT                   -- 'TrueNorth' | 'PortrayalContext' | NULL
);
CREATE INDEX ON enc_point USING GIST (geom);
CREATE INDEX ON enc_point (di_vg);
CREATE INDEX ON enc_point (di_sy);

-- ============================================================
-- SOUNDINGS  (high-volume, treated separately)
-- ============================================================
CREATE TABLE enc_sounding (
    id              BIGSERIAL PRIMARY KEY,
    foid            TEXT NOT NULL,
    cell_file       TEXT NOT NULL,
    geom            GEOMETRY(Point, 4326) NOT NULL,
    depth_m         NUMERIC(8,3) NOT NULL,
    di_vg           INTEGER DEFAULT 33022,
    di_dp           SMALLINT DEFAULT 20
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

    di_vg           INTEGER,
    di_dp           SMALLINT,
    label_text      TEXT NOT NULL,
    offset_x        NUMERIC(5,2) DEFAULT 0,   -- mm
    offset_y        NUMERIC(5,2) DEFAULT 0,
    font_colour     TEXT,                       -- colour token e.g. 'CHBLK'
    font_size       SMALLINT DEFAULT 10
);
CREATE INDEX ON enc_label USING GIST (geom);