"""
injest/db_writer.py

DB writer that persists portrayal drawing instructions to PostGIS.
"""
import os
import psycopg2

from .base import FeatureDict, FeatureWriter
from .parse_di import DrawingInstructions


class DBWriter(FeatureWriter):
    """Write portrayed features into PostGIS.

    The DB connection URL is read from the environment variable
    `DATABASE_URL`. This class raises RuntimeError if the env var is not set.
    """

    def __init__(self):
        db_url = os.environ.get('DATABASE_URL')
        if not db_url:
            raise RuntimeError('Environment variable DATABASE_URL is required')
        self.conn = psycopg2.connect(db_url)

    def write(self, feature: FeatureDict, dis: list[DrawingInstructions], cell_file: str) -> None:
        if not dis:
            return

        # Merge all DIs for this feature (a feature can emit multiple)
        merged = DrawingInstructions()
        all_texts = []
        for di in dis:
            if di.viewing_group is not None:       merged.viewing_group = di.viewing_group
            if di.drawing_priority is not None:    merged.drawing_priority = di.drawing_priority
            if di.display_plane != 'UnderRadar':   merged.display_plane = di.display_plane
            if di.scale_min is not None:           merged.scale_min = di.scale_min
            if di.scale_max is not None:           merged.scale_max = di.scale_max
            if di.color_fill is not None:          merged.color_fill = di.color_fill
            if di.color_fill_alpha is not None:    merged.color_fill_alpha = di.color_fill_alpha
            if di.area_pattern is not None:        merged.area_pattern = di.area_pattern
            if di.line_color is not None:          merged.line_color = di.line_color
            if di.line_style is not None:          merged.line_style = di.line_style
            if di.line_width is not None:          merged.line_width = di.line_width
            if di.dash_offset is not None:         merged.dash_offset = di.dash_offset
            if di.dash_length is not None:         merged.dash_length = di.dash_length
            if di.symbol_ref is not None:          merged.symbol_ref = di.symbol_ref
            if di.symbol_rotation is not None:     merged.symbol_rotation = di.symbol_rotation
            if di.symbol_rotation_type is not None: merged.symbol_rotation_type = di.symbol_rotation_type
            if di.hover:                           merged.hover = True
            if di.alert is not None:               merged.alert = di.alert
            all_texts.extend(di.texts)

        geom_type = feature.get('geometry', 'Point')
        wkt       = feature['wkt']
        foid      = feature['id']
        fcode     = feature['code']

        cur = self.conn.cursor()
        try:
            if geom_type == 'Surface':
                cur.execute("""
                    INSERT INTO enc_area
                      (foid, feature_code, cell_file, geom,
                       di_viewing_group, di_drawing_priority,
                       di_color_fill, di_area_pattern,
                       di_line_color, di_line_style, di_line_width,
                       display_plane, scale_min, scale_max,
                       di_color_fill_alpha, di_dash_offset, di_dash_length,
                       drval1, drval2)
                    VALUES (%s,%s,%s, ST_Multi(ST_GeomFromText(%s,4326)),
                            %s,%s, %s,%s, %s,%s,%s, %s,%s,%s, %s,%s,%s, %s,%s)
                    ON CONFLICT (foid) DO UPDATE SET
                      di_viewing_group=EXCLUDED.di_viewing_group,
                      di_drawing_priority=EXCLUDED.di_drawing_priority,
                      di_color_fill=EXCLUDED.di_color_fill,
                      di_area_pattern=EXCLUDED.di_area_pattern,
                      di_line_color=EXCLUDED.di_line_color,
                      di_line_style=EXCLUDED.di_line_style,
                      di_line_width=EXCLUDED.di_line_width,
                      display_plane=EXCLUDED.display_plane,
                      scale_min=EXCLUDED.scale_min,
                      scale_max=EXCLUDED.scale_max,
                      di_color_fill_alpha=EXCLUDED.di_color_fill_alpha,
                      di_dash_offset=EXCLUDED.di_dash_offset,
                      di_dash_length=EXCLUDED.di_dash_length
                """, (
                    foid, fcode, cell_file, wkt,
                    merged.viewing_group, merged.drawing_priority,
                    merged.color_fill, merged.area_pattern,
                    merged.line_color, merged.line_style, merged.line_width,
                    merged.display_plane, merged.scale_min, merged.scale_max,
                    merged.color_fill_alpha, merged.dash_offset, merged.dash_length,
                    feature['attributes'].get('depthRangeMinimumValue'),
                    feature['attributes'].get('depthRangeMaximumValue'),
                ))

            elif geom_type == 'Curve':
                cur.execute("""
                    INSERT INTO enc_line
                      (foid, feature_code, cell_file, geom,
                       di_viewing_group, di_drawing_priority,
                       di_line_color, di_line_style, di_line_width, di_color_fill,
                       display_plane, scale_min, scale_max,
                       di_dash_offset, di_dash_length)
                    VALUES (%s,%s,%s, ST_Multi(ST_GeomFromText(%s,4326)),
                            %s,%s, %s,%s,%s,%s, %s,%s,%s, %s,%s)
                    ON CONFLICT (foid) DO UPDATE SET
                      di_viewing_group=EXCLUDED.di_viewing_group,
                      di_drawing_priority=EXCLUDED.di_drawing_priority,
                      di_line_color=EXCLUDED.di_line_color,
                      di_line_style=EXCLUDED.di_line_style,
                      di_line_width=EXCLUDED.di_line_width,
                      di_color_fill=EXCLUDED.di_color_fill,
                      display_plane=EXCLUDED.display_plane,
                      scale_min=EXCLUDED.scale_min,
                      scale_max=EXCLUDED.scale_max,
                      di_dash_offset=EXCLUDED.di_dash_offset,
                      di_dash_length=EXCLUDED.di_dash_length
                """, (
                    foid, fcode, cell_file, wkt,
                    merged.viewing_group, merged.drawing_priority,
                    merged.line_color, merged.line_style, merged.line_width, merged.color_fill,
                    merged.display_plane, merged.scale_min, merged.scale_max,
                    merged.dash_offset, merged.dash_length,
                ))

            elif geom_type == 'Point':
                if fcode == 'Sounding':
                    cur.execute("""
                        INSERT INTO enc_sounding (foid, cell_file, geom, depth_m)
                        VALUES (%s,%s, ST_GeomFromText(%s,4326), %s)
                    """, (foid, cell_file, wkt,
                          feature['attributes'].get('valueOfSounding', 0)))
                else:
                    cur.execute("""
                        INSERT INTO enc_point
                          (foid, feature_code, cell_file, geom,
                           di_viewing_group, di_drawing_priority,
                           di_symbol_ref, di_symbol_rotation, di_symbol_rotation_type,
                           display_plane, scale_min, scale_max)
                        VALUES (%s,%s,%s, ST_GeomFromText(%s,4326),
                                %s,%s, %s,%s,%s, %s,%s,%s)
                        ON CONFLICT (foid) DO UPDATE SET
                          di_viewing_group=EXCLUDED.di_viewing_group,
                          di_drawing_priority=EXCLUDED.di_drawing_priority,
                          di_symbol_ref=EXCLUDED.di_symbol_ref,
                          di_symbol_rotation=EXCLUDED.di_symbol_rotation,
                          di_symbol_rotation_type=EXCLUDED.di_symbol_rotation_type,
                          display_plane=EXCLUDED.display_plane,
                          scale_min=EXCLUDED.scale_min,
                          scale_max=EXCLUDED.scale_max
                    """, (
                        foid, fcode, cell_file, wkt,
                        merged.viewing_group, merged.drawing_priority,
                        merged.symbol_ref, merged.symbol_rotation, merged.symbol_rotation_type,
                        merged.display_plane, merged.scale_min, merged.scale_max,
                    ))

            # Write text labels
            for txt in all_texts:
                if txt['text']:
                    cur.execute("""
                        INSERT INTO enc_label
                          (foid, cell_file, geom,
                           di_viewing_group, di_drawing_priority,
                           label_text, offset_x, offset_y, font_colour, font_size,
                           hjust, vjust)
                        VALUES (%s,%s, ST_GeomFromText(%s,4326),
                                %s,%s, %s,%s,%s,%s,%s, %s,%s)
                    """, (
                        foid, cell_file, wkt,
                        merged.viewing_group, merged.drawing_priority,
                        txt['text'], txt['offset_x'], txt['offset_y'],
                        txt['colour'], txt['size'],
                        txt['hjust'], txt['vjust'],
                    ))

            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cur.close()
