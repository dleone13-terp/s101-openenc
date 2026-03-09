"""
injest/s57_reader.py — Read S-57 (.000) ENC files and ingest into PostGIS.

Usage:
    python -m injest.s57_reader <file.000> [options]

Notes:
    - This tool requires the environment variable `DATABASE_URL` to be set
      when not using `--dry-run`.

Options:
    --dry-run       Map and parse features without writing to database
    -v, --verbose   Enable DEBUG logging
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Iterator

from osgeo import ogr

from .base import FeatureDict, FeaturePortrayer, FeatureReader, FeatureWriter, NullPortrayer, NullWriter

log = logging.getLogger(__name__)
ogr.UseExceptions()

# ---------------------------------------------------------------------------
# Feature code mapping: S-57 6-char layer name → S-101 feature code
# Verified against portrayal/PortrayalCatalog/Rules/ (342 files)
# ---------------------------------------------------------------------------
FEATURE_CODE_MAP: dict[str, str] = {
    # Depths
    'DEPARE': 'DepthArea',
    'DEPCNT': 'DepthContour',
    'DRGARE': 'DredgedArea',
    'SBDARE': 'SeabedArea',
    'SWPARE': 'SweptArea',
    'UWTROC': 'UnderwaterAwashRock',
    # Land
    'LNDARE': 'LandArea',
    'COALNE': 'Coastline',
    'SLCONS': 'ShorelineConstruction',
    'LNDELV': 'LandElevation',
    'RIVERS': 'River',
    'CANALS': 'Canal',
    'LAKARE': 'Lake',
    # Navigation aids
    'BOYLAT': 'LateralBuoy',
    'BOYCAR': 'CardinalBuoy',
    'BOYISD': 'IsolatedDangerBuoy',
    'BOYSAW': 'SafeWaterBuoy',
    'BOYSPP': 'SpecialPurposeGeneralBuoy',
    'BCNLAT': 'LateralBeacon',
    'BCNCAR': 'CardinalBeacon',
    'BCNISD': 'IsolatedDangerBeacon',
    'BCNSAW': 'SafeWaterBeacon',
    'BCNSPP': 'SpecialPurposeGeneralBeacon',
    'LIGHTS': 'LightAllAround',
    'LITFLT': 'LightFloat',
    'LITVES': 'LightVessel',
    'DAYMAR': 'Daymark',
    'FOGSIG': 'FogSignal',
    # Hazards
    'WRECKS': 'Wreck',
    'OBSTRN': 'Obstruction',
    'SOUNDG': 'Sounding',
    # Routing and traffic
    'FAIRWY': 'Fairway',
    'RECTRC': 'RecommendedTrack',
    'TSSLPT': 'TrafficSeparationSchemeLanePart',
    'TSSRON': 'TrafficSeparationSchemeRoundabout',
    'DWRTCL': 'DeepWaterRouteCentreline',
    # Restricted and regulated areas
    'RESARE': 'RestrictedArea',
    'ACHARE': 'AnchorageArea',
    'MIPARE': 'MilitaryPracticeArea',
    'DMPGRD': 'DumpingGround',
    # Infrastructure
    'BRIDGE': 'Bridge',
    'CBLSUB': 'CableSubmarine',
    'CBLOHD': 'CableOverhead',
    'PIPARE': 'SubmarinePipelineArea',
    'PIPSOL': 'PipelineSubmarineOnLand',
    'LNDMRK': 'Landmark',
    'MORFAC': 'MooringArea',
    'HULKES': 'Hulk',
    'PILPNT': 'Pile',
}

# ---------------------------------------------------------------------------
# Attribute mapping: S-57 attribute code → S-101 attribute name
# ---------------------------------------------------------------------------
ATTRIBUTE_MAP: dict[str, str] = {
    # Depths
    'DRVAL1': 'depthRangeMinimumValue',
    'DRVAL2': 'depthRangeMaximumValue',
    'VALDCO': 'valueOfDepthContour',
    'VALSOU': 'valueOfSounding',
    'QUASOU': 'qualityOfSoundingMeasurement',
    # Colour and shape — buoy/beacon portrayal
    'COLOUR': 'colour',
    'COLPAT': 'colourPattern',
    'BOYSHP': 'buoyShape',
    'BCNSHP': 'beaconShape',
    'CATLAM': 'categoryOfLateralMark',
    'CATCAM': 'categoryOfCardinalMark',
    'CATSPM': 'categoryOfSpecialPurposeMark',
    # Lights
    'CATLIT': 'categoryOfLight',
    'VALNMR': 'valueOfNominalRange',
    'SECTR1': 'sectorLimitOne',
    'SECTR2': 'sectorLimitTwo',
    'ORIENT': 'orientation',
    'HEIGHT': 'height',
    'STATUS': 'status',
    # Wrecks and obstructions
    'CATWRK': 'categoryOfWreck',
    'CATOBS': 'categoryOfObstruction',
    'WATLEV': 'waterLevelEffect',
    # Coastline
    'CATCOA': 'categoryOfCoastline',
    # Landmark
    'CONDTN': 'condition',
    'CATLMK': 'categoryOfLandmark',
    'FUNCTN': 'function',
    'VISLNG': 'visualProminence',
    # General
    'NATSUR': 'natureOfSurface',
    'INFORM': 'information',
}

# Geometry type WKB constant → S-101 geometry type string
_WKB_TO_GEOM: dict[int, str] = {
    ogr.wkbPoint:           'Point',
    ogr.wkbPoint25D:        'Point',
    ogr.wkbLineString:      'Curve',
    ogr.wkbLineString25D:   'Curve',
    ogr.wkbMultiLineString: 'Curve',
    ogr.wkbPolygon:         'Surface',
    ogr.wkbPolygon25D:      'Surface',
    ogr.wkbMultiPolygon:    'Surface',
    ogr.wkbMultiPolygon25D: 'Surface',
}

# Tracks unseen S-57 layer names so we only warn once each
_warned_codes: set[str] = set()


def _map_attributes(ogr_feat) -> dict:
    """Read all OGR field values and map S-57 attribute names to S-101 names."""
    attrs: dict = {}
    defn = ogr_feat.GetDefnRef()
    for i in range(defn.GetFieldCount()):
        field_defn = defn.GetFieldDefn(i)
        s57_name = field_defn.GetName()

        if not ogr_feat.IsFieldSet(i):
            continue

        raw_value = ogr_feat.GetField(i)
        if raw_value is None:
            continue

        # Feature name: S-57 OBJNAM → S-101 featureName list structure
        if s57_name == 'OBJNAM' and raw_value:
            attrs['featureName'] = [{'name': raw_value}]
            continue

        s101_name = ATTRIBUTE_MAP.get(s57_name)
        if s101_name is None:
            continue

        # GDAL returns COLOUR/COLPAT as Python lists already
        if s57_name in ('COLOUR', 'COLPAT'):
            attrs[s101_name] = list(raw_value) if raw_value else []
        else:
            attrs[s101_name] = raw_value

    return attrs


def _iter_soundings(ogr_feat, cell_file: str) -> Iterator[FeatureDict]:
    """Explode a SOUNDG MultiPoint25D into individual Point sounding dicts."""
    geom = ogr_feat.GetGeometryRef()
    fid = ogr_feat.GetFID()
    n = geom.GetGeometryCount()
    sub_geoms = [geom.GetGeometryRef(i) for i in range(n)] if n > 0 else [geom]
    for i, sub in enumerate(sub_geoms):
        yield {
            'code': 'Sounding',
            'id': f's57_{fid}_{i}',
            'geometry': 'Point',
            'attributes': {'valueOfSounding': sub.GetZ()},
            'wkt': f'POINT({sub.GetX()} {sub.GetY()})',
        }


def _ogr_to_dict(ogr_feat, layer_name: str, cell_file: str) -> FeatureDict | None:
    """Convert an OGR feature to a FeatureDict."""
    global _warned_codes

    geom = ogr_feat.GetGeometryRef()
    if geom is None:
        return None

    geom_type = _WKB_TO_GEOM.get(geom.GetGeometryType())
    if geom_type is None:
        log.debug("layer=%s FID=%d: unhandled geometry type %d, skipping",
                  layer_name, ogr_feat.GetFID(), geom.GetGeometryType())
        return None

    # Map S-57 layer name → S-101 feature code
    feature_code = FEATURE_CODE_MAP.get(layer_name, layer_name)
    if layer_name not in FEATURE_CODE_MAP and layer_name not in _warned_codes:
        log.warning("Unknown S-57 layer '%s' — passing through as-is", layer_name)
        _warned_codes.add(layer_name)

    # Flatten Z coordinates; PostGIS 2D geometry columns reject POLYGON Z WKT
    geom.FlattenTo2D()
    wkt = geom.ExportToWkt()

    fid = ogr_feat.GetFID()
    attrs = _map_attributes(ogr_feat)

    return {
        'code': feature_code,
        'id': f's57_{layer_name}_{fid}',
        'geometry': geom_type,
        'attributes': attrs,
        'wkt': wkt,
    }


class S57Reader(FeatureReader):
    """Read features from an S-57 (.000) ENC file."""

    def read(self, path) -> Iterator[FeatureDict]:
        ds = ogr.Open(str(path), 0)  # 0 = read-only
        if ds is None:
            raise RuntimeError(f"GDAL could not open '{path}'")

        cell_file = Path(path).name

        try:
            for i in range(ds.GetLayerCount()):
                layer = ds.GetLayerByIndex(i)
                layer_name = layer.GetName()
                log.debug("Processing layer: %s (%d features)", layer_name, layer.GetFeatureCount())

                for ogr_feat in layer:
                    geom = ogr_feat.GetGeometryRef()
                    if geom is None:
                        log.debug("layer=%s FID=%d: no geometry, skipping",
                                  layer_name, ogr_feat.GetFID())
                        continue

                    if layer_name == 'SOUNDG':
                        yield from _iter_soundings(ogr_feat, cell_file)
                        continue

                    feat = _ogr_to_dict(ogr_feat, layer_name, cell_file)
                    if feat is not None:
                        yield feat
        finally:
            ds = None  # close GDAL datasource


def ingest_s57_file(path, *, portrayer: FeaturePortrayer, writer: FeatureWriter) -> dict:
    """
    Open an S-57 .000 file and ingest all features.

    Returns a stats dict with keys 'ingested', 'skipped', 'errors'.
    """
    cell_file = Path(path).name
    reader = S57Reader()
    stats = {'ingested': 0, 'skipped': 0, 'errors': 0}

    ds = ogr.Open(str(path), 0)
    if ds is None:
        raise RuntimeError(f"GDAL could not open '{path}'")

    try:
        for i in range(ds.GetLayerCount()):
            layer = ds.GetLayerByIndex(i)
            layer_name = layer.GetName()
            log.debug("Processing layer: %s (%d features)", layer_name, layer.GetFeatureCount())

            for ogr_feat in layer:
                try:
                    geom = ogr_feat.GetGeometryRef()
                    if geom is None:
                        log.debug("layer=%s FID=%d: no geometry, skipping",
                                  layer_name, ogr_feat.GetFID())
                        stats['skipped'] += 1
                        continue

                    if layer_name == 'SOUNDG':
                        for feat in _iter_soundings(ogr_feat, cell_file):
                            dis = portrayer.portray(feat)
                            writer.write(feat, dis, cell_file)
                            stats['ingested'] += 1
                        continue

                    feat = _ogr_to_dict(ogr_feat, layer_name, cell_file)
                    if feat is None:
                        stats['skipped'] += 1
                        continue

                    log.debug("ingesting %s id=%s geom=%s", feat['code'], feat['id'], feat['geometry'])
                    dis = portrayer.portray(feat)
                    writer.write(feat, dis, cell_file)
                    stats['ingested'] += 1

                except Exception as e:
                    log.error("FID=%d layer=%s: %s", ogr_feat.GetFID(), layer_name, e)
                    stats['errors'] += 1
    finally:
        ds = None  # close GDAL datasource

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Ingest S-57 (.000) ENC file into PostGIS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('file', help="Path to S-57 .000 chart cell file")
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help="Map and parse features without writing to database",
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help="Enable DEBUG logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(levelname)s %(name)s: %(message)s',
    )

    path = Path(args.file)
    if not path.exists():
        log.error("File not found: %s", path)
        sys.exit(1)

    log.info("Reading %s (dry_run=%s)", path, args.dry_run)

    if args.dry_run:
        portrayer: FeaturePortrayer = NullPortrayer()
        writer: FeatureWriter = NullWriter()
    else:
        from .lua_host import LuaHost
        from .db_writer import DBWriter
        portrayer = LuaHost()
        writer = DBWriter()

    stats = ingest_s57_file(path, portrayer=portrayer, writer=writer)

    log.info("Done — ingested=%d skipped=%d errors=%d",
             stats['ingested'], stats['skipped'], stats['errors'])

    if stats['errors']:
        sys.exit(1)


if __name__ == '__main__':
    main()
