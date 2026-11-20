"""Lossless EWKB proof for the one wide spatial field in the closed scope.

Capture still verifies the original full JSON fingerprint in READ ONLY. The
critical transaction checks the same fields with lossless binary geometry,
avoiding repeated conversion of a 4.7 MB GeoJSON object. Authenticated backups
retain both documents. EWKB preserves full coordinate precision on restore.
"""

import hashlib
import json
import re

from shapely import from_wkb, get_srid
from shapely.errors import GEOSException
from shapely.geometry import shape

from scripts.residual_purge_catalog import quote, require

SPATIAL_COLUMN = "location_geometry"
SPATIAL_PROOF = "orders-location-ewkb-ndr-v1"


def _same_geometry(original, encoded):
    if original is None:
        return encoded is None
    try:
        binary = from_wkb(bytes.fromhex(encoded))
        # GeoJSON's decimal representation is the approved old fingerprint.
        # The EWKB proof additionally preserves every original binary bit.
        return get_srid(binary) == 4326 and shape(original).equals_exact(
            binary, tolerance=1e-9
        )
    except (TypeError, ValueError, GEOSException):
        return False


def spatial_document(columns, alias="t"):
    require(SPATIAL_COLUMN in columns, "spatial_column_missing")
    require(len(columns) == len(set(columns)), "duplicate_spatial_column")
    projection = [
        f"{alias}.{quote(c)}" for c in sorted(columns) if c != SPATIAL_COLUMN
    ]
    projection.append(
        f"encode(ST_AsEWKB({alias}.{quote(SPATIAL_COLUMN)},'NDR'),'hex') "
        f"AS {quote(SPATIAL_COLUMN)}"
    )
    return (
        "(SELECT to_jsonb(p)::text FROM (SELECT "
        + ",".join(projection)
        + ") p)"
    )


def validate_spatial_documents(snapshot):
    if not snapshot.get("spatial_proof"):
        require(
            all(
                not any(
                    k in r for k in ("restore_document", "restore_fingerprint")
                )
                for rows in snapshot["rows"].values()
                for r in rows
            ),
            "unversioned_spatial_document",
        )
        return
    require(
        snapshot["spatial_proof"] == SPATIAL_PROOF and snapshot["version"] == 3,
        "wrong_spatial_proof",
    )
    for table, rows in snapshot["rows"].items():
        for row in rows:
            if table != "orders":
                require(
                    "restore_document" not in row, "unexpected_spatial_table"
                )
                continue
            original = json.loads(row["document"])
            restored = json.loads(row["restore_document"])
            require(
                set(original) == set(restored)
                and all(
                    original[k] == restored[k]
                    for k in original
                    if k != SPATIAL_COLUMN
                ),
                "spatial_non_geometry_fields_changed",
            )
            geometry = restored[SPATIAL_COLUMN]
            require(
                (original[SPATIAL_COLUMN] is None and geometry is None)
                or (
                    original[SPATIAL_COLUMN] is not None
                    and isinstance(geometry, str)
                    and bool(re.fullmatch(r"01[a-f0-9]+", geometry))
                    and len(geometry) % 2 == 0
                ),
                "invalid_lossless_spatial_document",
            )
            require(
                _same_geometry(original[SPATIAL_COLUMN], geometry),
                "spatial_geometry_differs_from_approved_document",
            )
            require(
                hashlib.md5(row["restore_document"].encode()).hexdigest()
                == row["restore_fingerprint"],
                "spatial_document_fingerprint_changed",
            )
