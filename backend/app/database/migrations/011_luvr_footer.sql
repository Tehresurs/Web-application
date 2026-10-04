ALTER TABLE luvr_settings ADD COLUMN IF NOT EXISTS developer_position TEXT;
ALTER TABLE luvr_settings ADD COLUMN IF NOT EXISTS developer_name TEXT;
ALTER TABLE luvr_settings ADD COLUMN IF NOT EXISTS agreed_position TEXT;
ALTER TABLE luvr_settings ADD COLUMN IF NOT EXISTS agreed_name TEXT;
ALTER TABLE luvr_settings ADD COLUMN IF NOT EXISTS legend TEXT;
UPDATE luvr_settings SET
    developer_position=COALESCE(developer_position,'Ведущий инженер - руководитель группы'),
    developer_name=COALESCE(developer_name,'Аниськов В.И.'),
    agreed_position=COALESCE(agreed_position,'Руководитель проекта СК'),
    agreed_name=COALESCE(agreed_name,NULLIF(current_setting('luvr.initial_agreed_name',true),'')),
    legend=COALESCE(legend,'(1) - рабочий день
(0,5) - половина рабочего дня
(Д) - день в пути
(МВ) - межвахтовый отдых
(П) - простой
(Уволен) - увольнение сотрудника')
WHERE id=1;
ALTER TABLE luvr_months ADD COLUMN IF NOT EXISTS developer_position_snapshot TEXT;
ALTER TABLE luvr_months ADD COLUMN IF NOT EXISTS developer_name_snapshot TEXT;
ALTER TABLE luvr_months ADD COLUMN IF NOT EXISTS agreed_position_snapshot TEXT;
ALTER TABLE luvr_months ADD COLUMN IF NOT EXISTS agreed_name_snapshot TEXT;
ALTER TABLE luvr_months ADD COLUMN IF NOT EXISTS legend_snapshot TEXT;
-- One-time technical initialization, not recovery of historical signatories.
UPDATE luvr_months m SET developer_position_snapshot=s.developer_position,
    developer_name_snapshot=s.developer_name,agreed_position_snapshot=s.agreed_position,
    agreed_name_snapshot=s.agreed_name,legend_snapshot=s.legend
FROM luvr_settings s WHERE s.id=1 AND NULLIF(btrim(s.agreed_name),'') IS NOT NULL
    AND m.developer_position_snapshot IS NULL AND m.developer_name_snapshot IS NULL
    AND m.agreed_position_snapshot IS NULL AND m.agreed_name_snapshot IS NULL
    AND m.legend_snapshot IS NULL;
