"""PostgreSQL observes canonical profile and direct-binding mutations."""

HISTORY_WRITER_LOCK_SQL = "SELECT pg_advisory_xact_lock(2119754201, 170434819)"
HISTORY_SNAPSHOT_LOCK_SQL = (
    "SELECT pg_advisory_xact_lock_shared(2119754201, 170434819)"
)

PROFILE_HASH = """
COALESCE(md5(string_agg(
    creator_user_id::text || ':' || active::text || ':' ||
    COALESCE(instagram_user_id, ''), ',' ORDER BY creator_user_id::text
)), md5(''))
"""
BINDING_HASH = """
COALESCE(md5(string_agg(
    referrer_user_id::text || ':' || referred_user_id::text || ':' ||
    extract(epoch FROM created_at)::text || ':' ||
    extract(epoch FROM registered_at)::text,
    ',' ORDER BY referred_user_id::text
)), md5(''))
"""

LOCK_SQL = """
LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE blogger_profiles IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE user_referral_bindings IN SHARE ROW EXCLUSIVE MODE;
"""

TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION creator_history_write_barrier()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(2119754201, 170434819);
    RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS creator_profile_write_barrier ON blogger_profiles;
CREATE TRIGGER creator_profile_write_barrier
BEFORE INSERT OR UPDATE OR DELETE ON blogger_profiles
FOR EACH STATEMENT EXECUTE FUNCTION creator_history_write_barrier();

DROP TRIGGER IF EXISTS creator_binding_write_barrier
    ON user_referral_bindings;
CREATE TRIGGER creator_binding_write_barrier
BEFORE INSERT OR UPDATE OR DELETE ON user_referral_bindings
FOR EACH STATEMENT EXECUTE FUNCTION creator_history_write_barrier();

CREATE OR REPLACE FUNCTION creator_history_deny_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'creator identity history is immutable';
END $$;

CREATE OR REPLACE FUNCTION creator_append_identity(
    p_creator uuid, p_instagram text, p_active boolean, p_observed timestamptz,
    p_fact timestamptz, p_source text, p_key text
) RETURNS void LANGUAGE plpgsql AS $$
DECLARE existing record;
BEGIN
    INSERT INTO creator_identity_observations (
        creator_user_id, instagram_user_id, active, observed_at,
        fact_at, source, business_key
    ) VALUES (
        p_creator, p_instagram, p_active, p_observed, p_fact, p_source, p_key
    ) ON CONFLICT (business_key) DO NOTHING;
    SELECT * INTO existing FROM creator_identity_observations
        WHERE business_key = p_key;
    IF existing.creator_user_id IS DISTINCT FROM p_creator
       OR existing.instagram_user_id IS DISTINCT FROM p_instagram
       OR existing.active IS DISTINCT FROM p_active
       OR existing.source IS DISTINCT FROM p_source THEN
        RAISE EXCEPTION 'identity_proof_replay_conflict';
    END IF;
END $$;

CREATE OR REPLACE FUNCTION creator_observe_profile()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    observed timestamptz := clock_timestamp();
    fact_time timestamptz;
    evidence_key text := NULLIF(current_setting('ugc.identity_key', true), '');
    evidence_source text := NULLIF(
        current_setting('ugc.identity_source', true), ''
    );
    old_id text;
    new_id text;
    creator uuid;
    prefix text;
    previous_sequence bigint;
BEGIN
    IF evidence_source IS NULL THEN
        evidence_source := 'canonical_profile_observed';
    ELSIF evidence_source NOT IN ('instagram_webhook', 'manual_code')
          OR evidence_key IS NULL THEN
        RAISE EXCEPTION 'trusted_identity_source_required';
    ELSE
        fact_time := NULLIF(current_setting('ugc.identity_fact_at', true), '')
            ::timestamptz;
        IF fact_time IS NULL OR fact_time > observed THEN
            RAISE EXCEPTION 'identity_fact_time_in_future';
        END IF;
    END IF;
    IF TG_OP <> 'INSERT' THEN
        old_id := NULLIF(trim(OLD.instagram_user_id), '');
    END IF;
    IF TG_OP <> 'DELETE' THEN
        new_id := NULLIF(trim(NEW.instagram_user_id), '');
    END IF;
    IF TG_OP = 'UPDATE' AND evidence_key IS NULL
       AND OLD.user_id = NEW.user_id
       AND OLD.confirmed = NEW.confirmed
       AND old_id IS NOT DISTINCT FROM new_id
       AND OLD.instagram_url IS NOT DISTINCT FROM NEW.instagram_url THEN
        RETURN NEW;
    END IF;
    creator := CASE WHEN TG_OP = 'DELETE' THEN OLD.user_id ELSE NEW.user_id END;
    SELECT COALESCE(max(observation_sequence), 0) INTO previous_sequence
        FROM creator_identity_observations WHERE creator_user_id = creator;
    prefix := CASE WHEN evidence_key IS NOT NULL THEN 'proof:' || evidence_key
        ELSE 'change:' || creator::text || ':' ||
            previous_sequence::text || ':' || TG_OP END;
    IF TG_OP <> 'INSERT' AND (
        TG_OP = 'DELETE' OR OLD.user_id IS DISTINCT FROM NEW.user_id
        OR old_id IS DISTINCT FROM new_id
    ) THEN
        PERFORM creator_append_identity(
            OLD.user_id, old_id, false, observed, fact_time, evidence_source,
            prefix || ':' || OLD.user_id::text || ':revoke'
        );
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM creator_append_identity(
            NEW.user_id, new_id, NEW.confirmed AND new_id IS NOT NULL,
            observed, fact_time, evidence_source,
            prefix || ':' || NEW.user_id::text || ':current'
        );
        RETURN NEW;
    END IF;
    RETURN OLD;
END $$;

CREATE OR REPLACE FUNCTION creator_observe_direct_binding()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    observed timestamptz := clock_timestamp();
    previous_sequence bigint;
    relation uuid;
    registration timestamptz;
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.referrer_user_id = NEW.referrer_user_id
       AND OLD.referred_user_id = NEW.referred_user_id
       AND OLD.created_at = NEW.created_at THEN
        RETURN NEW;
    END IF;
    relation := CASE WHEN TG_OP = 'DELETE'
        THEN OLD.referred_user_id ELSE NEW.referred_user_id END;
    SELECT COALESCE(max(observation_sequence), 0) INTO previous_sequence
        FROM creator_direct_binding_observations
        WHERE referred_user_id = relation;
    IF TG_OP <> 'INSERT' THEN
        SELECT registered_at INTO registration
            FROM creator_direct_binding_observations
            WHERE referred_user_id = OLD.referred_user_id
            ORDER BY observation_sequence LIMIT 1;
        IF registration IS NULL THEN
            SELECT created_at INTO registration FROM users
                WHERE user_id = OLD.referred_user_id;
        END IF;
        INSERT INTO creator_direct_binding_observations (
            referrer_user_id, referred_user_id, active, created_at,
            registered_at,
            observed_at, source, business_key
        ) VALUES (
            OLD.referrer_user_id, OLD.referred_user_id, false, OLD.created_at,
            registration,
            observed, 'direct_binding_observed',
            'binding:' || relation::text || ':' ||
                OLD.referred_user_id::text || ':' ||
                previous_sequence::text || ':' || TG_OP || ':revoke'
        );
    END IF;
    IF TG_OP <> 'DELETE' THEN
        SELECT registered_at INTO registration
            FROM creator_direct_binding_observations
            WHERE referred_user_id = NEW.referred_user_id
            ORDER BY observation_sequence LIMIT 1;
        IF registration IS NULL THEN
            SELECT created_at INTO registration FROM users
                WHERE user_id = NEW.referred_user_id;
        END IF;
        INSERT INTO creator_direct_binding_observations (
            referrer_user_id, referred_user_id, active, created_at,
            registered_at,
            observed_at, source, business_key
        ) VALUES (
            NEW.referrer_user_id, NEW.referred_user_id, true, NEW.created_at,
            registration,
            observed, 'direct_binding_observed',
            'binding:' || NEW.referred_user_id::text || ':' ||
                previous_sequence::text || ':' || TG_OP || ':current'
        );
        RETURN NEW;
    END IF;
    RETURN OLD;
END $$;

DROP TRIGGER IF EXISTS creator_profile_observation ON blogger_profiles;
CREATE TRIGGER creator_profile_observation
AFTER INSERT OR UPDATE OR DELETE ON blogger_profiles
FOR EACH ROW EXECUTE FUNCTION creator_observe_profile();

DROP TRIGGER IF EXISTS creator_binding_observation ON user_referral_bindings;
CREATE TRIGGER creator_binding_observation
AFTER INSERT OR UPDATE OR DELETE ON user_referral_bindings
FOR EACH ROW EXECUTE FUNCTION creator_observe_direct_binding();

DROP TRIGGER IF EXISTS creator_identity_immutable
    ON creator_identity_observations;
CREATE TRIGGER creator_identity_immutable
BEFORE UPDATE OR DELETE ON creator_identity_observations
FOR EACH ROW EXECUTE FUNCTION creator_history_deny_mutation();

DROP TRIGGER IF EXISTS creator_binding_immutable
    ON creator_direct_binding_observations;
CREATE TRIGGER creator_binding_immutable
BEFORE UPDATE OR DELETE ON creator_direct_binding_observations
FOR EACH ROW EXECUTE FUNCTION creator_history_deny_mutation();

DROP TRIGGER IF EXISTS creator_coverage_immutable ON creator_identity_coverage;
CREATE TRIGGER creator_coverage_immutable
BEFORE UPDATE OR DELETE ON creator_identity_coverage
FOR EACH ROW EXECUTE FUNCTION creator_history_deny_mutation();

CREATE OR REPLACE FUNCTION creator_history_deny_truncate()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        'creator identity history is immutable; row observations required';
END $$;

DROP TRIGGER IF EXISTS creator_identity_no_truncate
    ON creator_identity_observations;
CREATE TRIGGER creator_identity_no_truncate
BEFORE TRUNCATE ON creator_identity_observations
FOR EACH STATEMENT EXECUTE FUNCTION creator_history_deny_truncate();

DROP TRIGGER IF EXISTS creator_binding_no_truncate
    ON creator_direct_binding_observations;
CREATE TRIGGER creator_binding_no_truncate
BEFORE TRUNCATE ON creator_direct_binding_observations
FOR EACH STATEMENT EXECUTE FUNCTION creator_history_deny_truncate();

DROP TRIGGER IF EXISTS creator_coverage_no_truncate
    ON creator_identity_coverage;
CREATE TRIGGER creator_coverage_no_truncate
BEFORE TRUNCATE ON creator_identity_coverage
FOR EACH STATEMENT EXECUTE FUNCTION creator_history_deny_truncate();

DROP TRIGGER IF EXISTS creator_profile_no_truncate ON blogger_profiles;
CREATE TRIGGER creator_profile_no_truncate
BEFORE TRUNCATE ON blogger_profiles
FOR EACH STATEMENT EXECUTE FUNCTION creator_history_deny_truncate();

DROP TRIGGER IF EXISTS creator_canonical_binding_no_truncate
    ON user_referral_bindings;
CREATE TRIGGER creator_canonical_binding_no_truncate
BEFORE TRUNCATE ON user_referral_bindings
FOR EACH STATEMENT EXECUTE FUNCTION creator_history_deny_truncate();
"""

CUTOVER_SQL = """
DO $$
DECLARE cutover timestamptz := clock_timestamp();
BEGIN
    IF EXISTS (SELECT 1 FROM creator_identity_coverage) THEN RETURN; END IF;
    INSERT INTO creator_identity_coverage (
        coverage_key, covered_from, source, profile_seed_count,
        binding_seed_count, profile_seed_hash, binding_seed_hash
    ) SELECT 'v1', cutover, 'canonical_cutover',
        (SELECT count(*) FROM blogger_profiles),
        (SELECT count(*) FROM user_referral_bindings),
        (SELECT COALESCE(md5(string_agg(
            user_id::text || ':' ||
            (confirmed AND NULLIF(trim(instagram_user_id), '') IS NOT NULL)
                ::text || ':' ||
                COALESCE(NULLIF(trim(instagram_user_id), ''), ''),
            ',' ORDER BY user_id::text
        )), md5('')) FROM blogger_profiles),
        (SELECT COALESCE(md5(string_agg(
            referrer_user_id::text || ':' || referred_user_id::text || ':' ||
            extract(epoch FROM b.created_at)::text || ':' ||
            extract(epoch FROM u.created_at)::text,
            ',' ORDER BY referred_user_id::text
        )), md5('')) FROM user_referral_bindings b
            JOIN users u ON u.user_id = b.referred_user_id);
    INSERT INTO creator_identity_observations (
        creator_user_id, instagram_user_id, active, observed_at,
        fact_at, source, business_key
    ) SELECT user_id, NULLIF(trim(instagram_user_id), ''),
        confirmed AND NULLIF(trim(instagram_user_id), '') IS NOT NULL,
        cutover, NULL, 'canonical_profile_cutover',
        'cutover-profile:' || user_id::text FROM blogger_profiles;
    INSERT INTO creator_direct_binding_observations (
        referrer_user_id, referred_user_id, active, created_at, registered_at,
        observed_at, source, business_key
    ) SELECT referrer_user_id, referred_user_id, true,
        b.created_at, u.created_at,
        cutover,
        'direct_binding_cutover', 'cutover-binding:' || referred_user_id::text
        FROM user_referral_bindings b
        JOIN users u ON u.user_id = b.referred_user_id;
END $$;
"""
