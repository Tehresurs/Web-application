from datetime import date
import unittest
from unittest.mock import Mock, patch
from pydantic import ValidationError
from app.services import vou_settings as settings
from app.api.vou_settings import SettingsRequest, put_settings


class VouSettingsTests(unittest.TestCase):
    def test_empty_settings_allow_later_configuration_but_block_generation(self):
        item = settings.view({})
        self.assertFalse(item['configured'])
        self.assertEqual(len(item['missing_fields']), 5)
        self.assertEqual(item['contract_number'], '')
        with self.assertRaisesRegex(ValueError, 'Заполните реквизиты'):
            settings.require_configured(item)

    def test_snapshot_is_independent_and_date_is_serializable(self):
        values = dict(contract_number=' Тест ', contract_date=date(2026, 10, 18),
                      contract_revision='2', customer_signer_name='Заказчик', contractor_signer_name='Исполнитель')
        snapshot = settings.require_configured(values)
        values['contract_number'] = 'Другой'
        self.assertEqual(snapshot['contract_number'], 'Тест')
        self.assertEqual(snapshot['contract_date'], '2026-10-18')

    def test_wrong_database_is_rejected(self):
        conn = Mock()
        conn.execute.return_value.fetchone.return_value = ('ai_excel_agent', 'public')
        with self.assertRaises(RuntimeError):
            settings.assert_target(conn)

    def test_api_accepts_partial_settings_and_rejects_unexpected_fields(self):
        values = {field: None if field == 'contract_date' else '' for field in settings.FIELDS}
        with patch.object(settings, 'save_settings', side_effect=settings.view) as save:
            response = put_settings(SettingsRequest(**values))
            self.assertFalse(response['item']['configured'])
            save.assert_called_once()
            with self.assertRaises(ValidationError):
                SettingsRequest(**values, customer_position='Другой')
            self.assertEqual(save.call_count, 1)

    def test_invalid_date_or_control_characters_are_rejected(self):
        values = {field: None if field == 'contract_date' else '' for field in settings.FIELDS}
        with self.assertRaises(ValueError):
            settings.normalize({**values, 'contract_date': '2026-02-29'})
        with self.assertRaises(ValueError):
            settings.normalize({**values, 'contract_number': 'a\nb'})
