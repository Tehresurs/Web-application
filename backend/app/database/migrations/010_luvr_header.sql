CREATE TABLE IF NOT EXISTS luvr_settings (
    id INTEGER PRIMARY KEY CHECK(id=1),
    approver_position TEXT NOT NULL,
    approver_name TEXT NOT NULL,
    document_title TEXT NOT NULL
);
INSERT INTO luvr_settings VALUES (1,'Генеральный директор','Мясников А.В.',
'Лист учета времени посещения объектов
специалистами НТН ООО «Техресурс»
на объектах ООО «Салым Петролеум Девелопмент»
и в интересах ООО «Салым Петролеум Девелопмент»
по договору № MOS.25.0008 от 01.07.2025 года.') ON CONFLICT DO NOTHING;
ALTER TABLE luvr_months ADD COLUMN IF NOT EXISTS approver_position_snapshot TEXT;
ALTER TABLE luvr_months ADD COLUMN IF NOT EXISTS approver_name_snapshot TEXT;
ALTER TABLE luvr_months ADD COLUMN IF NOT EXISTS document_title_snapshot TEXT;
-- Existing months predate snapshots: initialize once during this explicit migration.
UPDATE luvr_months SET approver_position_snapshot=s.approver_position,
    approver_name_snapshot=s.approver_name, document_title_snapshot=s.document_title
FROM luvr_settings s WHERE s.id=1 AND approver_position_snapshot IS NULL
    AND approver_name_snapshot IS NULL AND document_title_snapshot IS NULL;
