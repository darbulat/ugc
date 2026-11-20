"""Catalog checks for the one-off residual purge rehearsal.

No application configuration, production connections or mutations on import.
Identifiers come only from the PostgreSQL catalog or the sealed manifest.
"""

import hashlib
import json
import re

from sqlalchemy import text


class UnsafePurge(ValueError):
    """A precondition changed; the whole operation must be abandoned."""


def require(condition, message):
    if not condition:
        raise UnsafePurge(message)


def quote(value):
    require(bool(re.fullmatch(r"[a-z][a-z0-9_]*", value)), "bad_identifier")
    return '"' + value + '"'


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def rows(db, statement, params=None):
    return [
        dict(row)
        for row in db.execute(text(statement), params or {}).mappings()
    ]


def primary_keys(db):
    return {
        row["table_name"]: row["columns"]
        for row in rows(
            db,
            """

            SELECT c.relname AS table_name,
                   array_agg(a.attname ORDER BY
k.ordinality) AS columns
            FROM pg_index i JOIN pg_class c ON
c.oid=i.indrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            JOIN LATERAL unnest(i.indkey) WITH
ORDINALITY k(attnum,ordinality)
                ON true
            JOIN pg_attribute a ON a.attrelid=c.oid
AND a.attnum=k.attnum
            WHERE i.indisprimary AND n.nspname=current_schema()
            GROUP BY c.relname

""",
        )
    }


def foreign_keys(db):
    return rows(
        db,
        """

        SELECT c.conname, child.relname AS child,
 parent.relname AS parent,
               c.confdeltype AS action,
               array_agg(ca.attname ORDER BY k.ordinality)
AS child_cols,
               array_agg(pa.attname ORDER BY k.ordinality)
AS parent_cols
        FROM pg_constraint c
        JOIN pg_class child ON child.oid=c.conrelid
        JOIN pg_class parent ON parent.oid=c.confrelid
        JOIN pg_namespace n ON n.oid=child.relnamespace
        JOIN LATERAL unnest(c.conkey,c.confkey)
WITH ORDINALITY
            k(ck,pk,ordinality) ON true
        JOIN pg_attribute ca ON ca.attrelid=child.oid
AND ca.attnum=k.ck
        JOIN pg_attribute pa ON pa.attrelid=parent.oid
AND pa.attnum=k.pk
        WHERE c.contype='f' AND n.nspname=current_schema()
        GROUP BY c.conname,child.relname,parent.relname,
c.confdeltype
        ORDER BY child.relname,c.conname

""",
    )


def triggers(db, tables):
    return rows(
        db,
        """
        SELECT c.relname AS table_name, t.tgname AS trigger_name,
               t.tgenabled, t.tgtype,
               pg_get_triggerdef(t.oid) AS definition,
               pg_get_functiondef(t.tgfoid) AS function_definition
        FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE NOT t.tgisinternal AND n.nspname=current_schema()
          AND c.relname=ANY(CAST(:tables AS text[]))
        ORDER BY c.relname,t.tgname
    """,
        {"tables": list(tables)},
    )


def schema_signature(db, tables):
    columns = rows(
        db,
        """

        SELECT c.relname, a.attname, a.attnum,
a.attnotnull, a.attidentity,
               a.attgenerated, format_type(a.atttypid,
a.atttypmod) AS type,
               pg_get_expr(d.adbin,d.adrelid) AS
default_expression
        FROM pg_attribute a JOIN pg_class c ON
c.oid=a.attrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid
AND d.adnum=a.attnum
        WHERE n.nspname=current_schema() AND a.attnum>0
AND NOT a.attisdropped
          AND c.relname=ANY(CAST(:tables AS text[]))
        ORDER BY c.relname,a.attnum

""",
        {"tables": list(tables)},
    )
    constraints = rows(
        db,
        """
        SELECT c.relname, k.conname, k.convalidated,
               pg_get_constraintdef(k.oid) AS definition
        FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=current_schema()
        ORDER BY c.relname,k.conname
    """,
    )
    return digest(
        {
            "columns": columns,
            "constraints": constraints,
            "triggers": triggers(db, tables),
        }
    )


def row_documents(db, table, fingerprints):
    return rows(
        db,
        f"""
        SELECT md5(to_jsonb(t)::text) AS fingerprint,
               to_jsonb(t)::text AS document
        FROM {quote(table)} t
        WHERE md5(to_jsonb(t)::text)=ANY(CAST(:hashes AS text[]))
        ORDER BY md5(to_jsonb(t)::text)
    """,
        {"hashes": fingerprints},
    )


def check_incoming_references(db, selected):
    """Include SET NULL/CASCADE edges: neither may change unrelated rows."""
    for fk in foreign_keys(db):
        if fk["parent"] not in selected:
            continue
        join = " AND ".join(
            f"c.{quote(c)}=p.{quote(p)}"
            for c, p in zip(fk["child_cols"], fk["parent_cols"], strict=True)
        )
        found = db.scalar(
            text(f"""

            SELECT EXISTS (
                SELECT 1 FROM {quote(fk["child"])}
c
                JOIN {quote(fk["parent"])} p ON
{join}
                WHERE md5(to_jsonb(p)::text)=ANY(CAST(:parents
AS text[]))
                  AND NOT (md5(to_jsonb(c)::text)=ANY(CAST(:children
AS text[])))
            )

"""),
            {
                "parents": selected[fk["parent"]],
                "children": selected.get(fk["child"], []),
            },
        )
        require(not found, "outside_foreign_key_reference:" + fk["child"])


def reference_columns(db):
    return rows(
        db,
        """

        SELECT c.table_name,c.column_name FROM
information_schema.columns c
        JOIN information_schema.tables t USING
(table_catalog,table_schema,

 table_name)
        WHERE c.table_schema=current_schema() AND
t.table_type='BASE TABLE'
          AND c.data_type IN ('uuid','json','jsonb',
'text',
                              'character varying',
'character')
        ORDER BY c.table_name,c.ordinal_position

""",
    )


def check_logical_references(db, selected, roots, audit_id, *, redacted=False):
    """Fail closed on UUID, JSON and text references without an FK."""
    for col in reference_columns(db):
        table, column = col["table_name"], col["column_name"]
        conditions = " OR ".join(
            f"strpos(t.{quote(column)}::text,:root{i})>0"
            for i in range(len(roots))
        )
        audit_exception = (
            "AND t.id<>CAST(:audit_id AS uuid)"
            if table == "audit_log" and not redacted
            else ""
        )
        params = {f"root{i}": root for i, root in enumerate(roots)}
        params.update(hashes=selected.get(table, []), audit_id=audit_id)
        found = db.scalar(
            text(f"""

            SELECT EXISTS (SELECT 1 FROM {quote(table)}
t
                WHERE ({conditions})
                  AND NOT (md5(to_jsonb(t)::text)=ANY(CAST(:hashes
AS text[])))
                  {audit_exception})

"""),
            params,
        )
        require(not found, f"outside_logical_reference:{table}.{column}")


def deletion_order(db, tables):
    remaining = set(tables)
    edges = [
        (r["child"], r["parent"])
        for r in foreign_keys(db)
        if r["child"] != r["parent"]
    ]
    result = []
    while remaining:
        leaves = sorted(
            t
            for t in remaining
            if not any(
                parent == t and child in remaining for child, parent in edges
            )
        )
        require(bool(leaves), "cyclic_foreign_keys")
        result.extend(leaves)
        remaining.difference_update(leaves)
    return result


def retained_fingerprints(db, selected, *, audit_ids=()):
    result = {}
    tables = [
        r["table_name"]
        for r in rows(
            db,
            """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema=current_schema() AND table_type='BASE TABLE'
        ORDER BY table_name
    """,
        )
    ]
    for table in tables:
        extra = (
            "AND t.id<>ALL(CAST(:audit_ids AS uuid[]))"
            if table == "audit_log"
            else ""
        )
        result[table] = db.scalar(
            text(f"""

            SELECT md5(COALESCE(string_agg(fingerprint,
',' ORDER BY fingerprint),''))
            FROM (SELECT md5(to_jsonb(t)::text)
AS fingerprint
                  FROM {quote(table)} t
                  WHERE NOT (md5(to_jsonb(t)::text)=ANY(CAST(:hashes
AS text[])))
                    {extra}) s

"""),
            {"hashes": selected.get(table, []), "audit_ids": list(audit_ids)},
        )
    return result
