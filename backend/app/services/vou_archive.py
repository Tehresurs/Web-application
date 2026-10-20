"""Immutable application archive of successfully verified VOU workbooks.

No database writes. Only the report generator may publish; HTTP is read-only.
Incomplete staging directories are never listed or served.
"""
from calendar import monthrange
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
from uuid import uuid4
from zipfile import ZipFile, BadZipFile
from app.services.vou_settings import require_configured

OUTPUT = Path(__file__).resolve().parents[2] / 'output' / 'vou'
ARCHIVE_ROOT = OUTPUT / 'archive'
REQUIRED_CHECKS = ('excel_reopened', 'preservation_accepted', 'data_totals_match')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class VouArchive:
    def __init__(self, root=ARCHIVE_ROOT, source_root=OUTPUT):
        self.root = Path(root).resolve()
        self.source_root = Path(source_root).resolve()

    def _directory(self, report_id):
        if not isinstance(report_id, str) or not re.fullmatch(r'[0-9a-f]{32}', report_id):
            raise ValueError('Некорректный номер архивного отчёта')
        directory = (self.root / report_id).resolve()
        if directory.parent != self.root:
            raise ValueError('Недопустимый путь архива')
        return directory

    def _file(self, directory, name):
        path = (directory / name).resolve()
        if path.parent != directory:
            raise ValueError('Недопустимый путь файла архива')
        return path

    def publish(self, source, *, data, settings, verification):
        # Copy snapshots before file I/O; later changes cannot affect the record.
        requisites = require_configured(settings)
        snapshot = json.loads(json.dumps(data, ensure_ascii=False, allow_nan=False))
        checks = json.loads(json.dumps(verification, ensure_ascii=False, allow_nan=False))
        if checks.get('technical_only') is True:
            raise ValueError('Технические отчёты не публикуются в рабочем архиве')
        if any(checks.get(key) is not True for key in REQUIRED_CHECKS):
            raise ValueError('Архив принимает только проверенные результаты Excel и сверки данных')
        year, month = snapshot['year'], snapshot['month']
        if type(year) is not int or type(month) is not int:
            raise ValueError('Некорректный отчётный период')
        last = monthrange(year, month)[1]
        if not 1900 <= year <= 9999:
            raise ValueError('Некорректный год отчёта')
        if snapshot['total_cents'] != sum(s['total_cents'] for s in snapshot['sections']):
            raise ValueError('Контрольная сумма данных ВОУ не совпадает')
        source = Path(source).resolve(strict=True)
        if source.suffix.lower() != '.xlsm' or not source.is_relative_to(self.source_root):
            raise ValueError('Источник архива должен быть результатом XLSM в каталоге ВОУ')
        if source.is_relative_to(self.root):
            raise ValueError('Повторная публикация архивного файла запрещена')
        try:
            with ZipFile(source) as workbook:
                if workbook.testzip() or not {'xl/workbook.xml','xl/vbaProject.bin'}.issubset(workbook.namelist()):
                    raise ValueError('Повреждён XLSM или отсутствует VBA')
        except BadZipFile as exc:
            raise ValueError('Некорректный XLSM') from exc
        report_id = uuid4().hex
        self.root.mkdir(parents=True, exist_ok=True)
        directory = self._directory(report_id)
        staging = self.root / ('.pending-' + report_id)
        staging.mkdir(exist_ok=False)
        try:
            target = staging / 'report.xlsm'
            before = digest(source)
            with source.open('rb') as incoming, target.open('xb') as outgoing:
                shutil.copyfileobj(incoming, outgoing)
            if digest(target) != before or digest(source) != before:
                raise ValueError('Исходный файл изменился во время архивирования')
            metadata = dict(schema_version=1, id=report_id,
                generated_at=datetime.now(timezone.utc).isoformat(), year=year, month=month,
                date_from=f'{year:04d}-{month:02d}-01',date_to=f'{year:04d}-{month:02d}-{last:02d}',
                filename=f'Отчет ВОУ_{year:04d}-{month:02d}_{report_id}.xlsm',
                settings=requisites, total_cents=snapshot['total_cents'],
                sha256=before, data=snapshot, verification=checks)
            with (staging/'snapshot.json').open('x',encoding='utf-8') as stream:
                json.dump(metadata,stream,ensure_ascii=False,indent=2,allow_nan=False)
            # Unique directory publication on the same filesystem is atomic.
            staging.rename(directory)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return self.summary(metadata)

    @staticmethod
    def summary(metadata):
        return {key: metadata[key] for key in ('id','generated_at','year','month','date_from',
                'date_to','filename','settings','total_cents','sha256')}

    def read(self, report_id):
        directory = self._directory(report_id)
        metadata_path = self._file(directory, 'snapshot.json')
        metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
        if metadata.get('id') != report_id or metadata.get('schema_version') != 1:
            raise ValueError('Повреждены сведения архивного отчёта')
        file = self._file(directory, 'report.xlsm')
        if digest(file) != metadata.get('sha256'):
            raise ValueError('Архивный файл изменён: контрольная сумма не совпадает')
        return metadata, file

    def list_reports(self):
        if not self.root.exists():
            return dict(items=[], warnings=[])
        items, warnings = [], []
        for directory in self.root.iterdir():
            if not directory.is_dir() or not re.fullmatch(r'[0-9a-f]{32}',directory.name):
                continue
            try:
                metadata, _ = self.read(directory.name)
                items.append(self.summary(metadata))
            except (OSError,ValueError,KeyError):
                warnings.append(dict(id=directory.name,message='Архивный отчёт недоступен или повреждён'))
        return dict(items=sorted(items,key=lambda item:(item['generated_at'],item['id']),reverse=True),warnings=warnings)
