-- Transactional PostgreSQL smoke test for 024_construction_entities_clean_start.sql.
-- Run only against the explicitly approved ai_excel_agent_stage41210_20261014_1634 rehearsal database.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '1min';

DO $test$
DECLARE
    approved_database TEXT := current_setting('app.stage4129_rehearsal_database', TRUE);
    root_id BIGINT;
    child_id BIGINT;
    mover_id BIGINT;
    destination_id BIGINT;
    archived_id BIGINT;
    inactive_id BIGINT;
    change_id BIGINT;
    ticket_id BIGINT;
    v_alias_id BIGINT;
    rejected BOOLEAN;
BEGIN
    IF current_database() NOT IN (
           'ai_excel_agent_stage41210_20261014_1634',
           'ai_excel_agent_stage4151_20261019_988ebc2b',
           'ai_excel_agent_stage4151_20261019_86bf41ed'
       )
       OR approved_database IS DISTINCT FROM current_database()
       OR current_schema() <> 'public' THEN
        RAISE EXCEPTION 'Smoke test requires the explicitly named clean-start rehearsal database';
    END IF;

    INSERT INTO public.construction_entities(name)
    VALUES ('stage41210 root ' || txid_current()::TEXT)
    RETURNING entity_id INTO root_id;

    INSERT INTO public.construction_entities(name, parent_entity_id)
    VALUES ('stage41210 child ' || txid_current()::TEXT, root_id)
    RETURNING entity_id INTO child_id;

    INSERT INTO public.construction_entity_aliases(entity_id, source_value)
    VALUES (child_id, 'stage41210 alias ' || txid_current()::TEXT)
    RETURNING alias_id INTO v_alias_id;
    IF NOT EXISTS (
        SELECT 1
        FROM public.construction_entity_aliases
        WHERE construction_entity_aliases.alias_id = v_alias_id
          AND construction_entity_aliases.entity_id = child_id
          AND construction_entity_aliases.normalized_source_value =
              public.normalize_known_value(
                  'object', construction_entity_aliases.source_value
              )
    ) THEN
        RAISE EXCEPTION 'Construction alias was not stored against entity_id';
    END IF;

    INSERT INTO public.construction_entities(name)
    VALUES ('stage41210 movable ' || txid_current()::TEXT)
    RETURNING entity_id INTO mover_id;

    INSERT INTO public.construction_entities(name)
    VALUES ('stage41210 destination ' || txid_current()::TEXT)
    RETURNING entity_id INTO destination_id;

    INSERT INTO public.construction_entities(name, is_archived, archived_at)
    VALUES ('stage41210 archived ' || txid_current()::TEXT, TRUE, clock_timestamp())
    RETURNING entity_id INTO archived_id;

    INSERT INTO public.construction_entities(name, is_active)
    VALUES ('stage41210 inactive ' || txid_current()::TEXT, FALSE)
    RETURNING entity_id INTO inactive_id;

    INSERT INTO public.employee_assignments(employee_id, entity_id, po_id, category_id)
    VALUES (52, child_id, 12, 7);

    INSERT INTO public.daily_control_results(
        report_date, employee_id, entity_id, po_id, category_id, source_file, source_sha256
    )
    VALUES (
        DATE '2099-12-30', 52, child_id, 12, 7,
        'stage41210-smoke-test', repeat('b', 64)
    );

    INSERT INTO public.production_assignment_changes(
        employee_id, effective_from, period_kind, period_start, period_end,
        period_revision, source_kind, assignment_state
    )
    VALUES (
        52, DATE '2099-12-30', 'EXPLICIT', DATE '2099-12-30', DATE '2099-12-31',
        'stage41210-smoke-test', 'MANUAL', 'OBJECTS'
    )
    RETURNING id INTO change_id;

    INSERT INTO public.production_assignment_items(change_id, entity_id, po_id, initial_category_id)
    VALUES (change_id, child_id, 12, 7);
    SET CONSTRAINTS ALL IMMEDIATE;

    INSERT INTO public.rail_tickets(file_hash, source_filename, status, entity_id)
    VALUES (repeat('a', 64), 'stage41210-smoke-ticket', 'PARSED', child_id)
    RETURNING id INTO ticket_id;

    UPDATE public.construction_entities
    SET parent_entity_id = destination_id
    WHERE entity_id = mover_id;
    UPDATE public.construction_entities
    SET parent_entity_id = NULL
    WHERE entity_id = mover_id;

    IF (SELECT entity_id FROM public.construction_entities WHERE entity_id = mover_id) <> mover_id THEN
        RAISE EXCEPTION 'entity_id changed during object/subobject conversion';
    END IF;

    rejected := FALSE;
    BEGIN
        INSERT INTO public.construction_entities(name, parent_entity_id)
        VALUES ('stage41210 forbidden grandchild ' || txid_current()::TEXT, child_id);
    EXCEPTION WHEN check_violation THEN
        rejected := TRUE;
    END;
    IF NOT rejected THEN
        RAISE EXCEPTION 'Three-level hierarchy was not rejected';
    END IF;

    rejected := FALSE;
    BEGIN
        INSERT INTO public.employee_assignments(employee_id, po_id, category_id)
        VALUES (52, 12, 7);
    EXCEPTION WHEN check_violation THEN
        rejected := TRUE;
    END;
    IF NOT rejected THEN
        RAISE EXCEPTION 'An assignment without entity_id was accepted';
    END IF;

    rejected := FALSE;
    BEGIN
        INSERT INTO public.employee_assignments(employee_id, object_id, entity_id, po_id, category_id)
        VALUES (52, 1, child_id, 12, 7);
    EXCEPTION WHEN check_violation THEN
        rejected := TRUE;
    END;
    IF NOT rejected THEN
        RAISE EXCEPTION 'A legacy object_id was accepted by the clean-start model';
    END IF;

    rejected := FALSE;
    BEGIN
        INSERT INTO public.daily_control_results(
            report_date, employee_id, object_id, entity_id, po_id, category_id,
            source_file, source_sha256
        )
        VALUES (
            DATE '2099-12-31', 52, 1, child_id, 12, 7,
            'stage41210-legacy-fact', repeat('c', 64)
        );
    EXCEPTION WHEN check_violation THEN
        rejected := TRUE;
    END;
    IF NOT rejected THEN
        RAISE EXCEPTION 'A legacy object_id was accepted for an entity-only daily fact';
    END IF;

    rejected := FALSE;
    BEGIN
        INSERT INTO public.production_assignment_items(
            change_id, object_id, entity_id, po_id, initial_category_id
        )
        VALUES (change_id, 1, child_id, 12, 7);
    EXCEPTION WHEN check_violation THEN
        rejected := TRUE;
    END;
    IF NOT rejected THEN
        RAISE EXCEPTION 'A legacy object_id was accepted for an entity-only production item';
    END IF;

    rejected := FALSE;
    BEGIN
        INSERT INTO public.rail_tickets(
            file_hash, source_filename, status, object_id, entity_id
        )
        VALUES (repeat('c', 64), 'stage41210-legacy-ticket', 'PARSED', 1, child_id);
    EXCEPTION WHEN check_violation THEN
        rejected := TRUE;
    END;
    IF NOT rejected THEN
        RAISE EXCEPTION 'A legacy object_id was accepted for an entity-linked ticket';
    END IF;

    rejected := FALSE;
    BEGIN
        INSERT INTO public.employee_assignments(employee_id, entity_id, po_id, category_id)
        VALUES (52, 9223372036854775807, 12, 7);
    EXCEPTION WHEN foreign_key_violation THEN
        rejected := TRUE;
    END;
    IF NOT rejected THEN
        RAISE EXCEPTION 'An unknown entity_id was accepted';
    END IF;

    rejected := FALSE;
    BEGIN
        INSERT INTO public.construction_entity_aliases(entity_id, source_value)
        VALUES (9223372036854775807, 'stage41210 alias without entity');
    EXCEPTION WHEN foreign_key_violation THEN
        rejected := TRUE;
    END;
    IF NOT rejected THEN
        RAISE EXCEPTION 'A construction alias accepted an unknown entity_id';
    END IF;

    rejected := FALSE;
    BEGIN
        INSERT INTO public.employee_assignments(employee_id, entity_id, po_id, category_id)
        VALUES (52, archived_id, 12, 7);
    EXCEPTION WHEN check_violation THEN
        rejected := TRUE;
    END;
    IF NOT rejected THEN
        RAISE EXCEPTION 'An archived entity accepted a new assignment';
    END IF;

    rejected := FALSE;
    BEGIN
        INSERT INTO public.employee_assignments(employee_id, entity_id, po_id, category_id)
        VALUES (52, inactive_id, 12, 7);
    EXCEPTION WHEN check_violation THEN
        rejected := TRUE;
    END;
    IF NOT rejected THEN
        RAISE EXCEPTION 'An inactive entity accepted a new assignment';
    END IF;

    rejected := FALSE;
    BEGIN
        INSERT INTO public.construction_entities(name, parent_entity_id)
        VALUES ('stage41210 child of inactive ' || txid_current()::TEXT, inactive_id);
    EXCEPTION WHEN check_violation THEN
        rejected := TRUE;
    END;
    IF NOT rejected THEN
        RAISE EXCEPTION 'An inactive parent accepted a new child';
    END IF;

    UPDATE public.construction_entities
    SET is_archived = TRUE, archived_at = clock_timestamp()
    WHERE entity_id = root_id;
    rejected := FALSE;
    BEGIN
        INSERT INTO public.employee_assignments(employee_id, entity_id, po_id, category_id)
        VALUES (52, child_id, 12, 7);
    EXCEPTION WHEN check_violation THEN
        rejected := TRUE;
    END;
    IF NOT rejected THEN
        RAISE EXCEPTION 'A child of an archived parent accepted a new assignment';
    END IF;
    UPDATE public.construction_entities
    SET is_archived = FALSE, archived_at = NULL
    WHERE entity_id = root_id;
    UPDATE public.construction_entities
    SET is_archived = TRUE, archived_at = clock_timestamp()
    WHERE entity_id = child_id;
    UPDATE public.construction_entities
    SET is_archived = FALSE, archived_at = NULL
    WHERE entity_id = child_id;

    IF (SELECT count(*) FROM public.employee_assignments WHERE entity_id = child_id AND object_id IS NULL) <> 1
       OR (SELECT count(*) FROM public.daily_control_results
           WHERE entity_id = child_id AND object_id IS NULL AND subobject_id IS NULL) <> 1
       OR (SELECT count(*) FROM public.production_assignment_items
           WHERE entity_id = child_id AND object_id IS NULL AND subobject_id IS NULL) <> 1
       OR (SELECT count(*) FROM public.rail_tickets
           WHERE id = ticket_id AND entity_id = child_id AND object_id IS NULL) <> 1 THEN
        RAISE EXCEPTION 'An entity-only consumer row was not stored with null legacy IDs';
    END IF;
END
$test$;

ROLLBACK;
