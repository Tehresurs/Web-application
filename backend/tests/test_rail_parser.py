import unittest
from pathlib import Path
from datetime import datetime
from rail_fixture import coupon_pdf,combine_pdfs
from app.services.rail_ticket_parser import parse_rail_document,luvr_route
from app.services.rail_ticket_parser import parse_rail_ticket,normalize_passenger,safe_filename,MAX_TICKET_BYTES


class RailParserTests(unittest.TestCase):
    def test_mikheev_real_layout_single_ticket(self):
        items=parse_rail_document((Path(__file__).parent/'fixtures/rail/salym_astrakhan.pdf').read_bytes(),'mikheev.pdf')
        self.assertEqual(len(items),1);p=items[0]
        self.assertEqual(p.full_name_raw,'МИХЕЕВ СТАНИСЛАВ АЛЕКСАНДРОВИЧ');self.assertEqual(p.source_page,1)
        self.assertEqual((p.departure_station,p.departure_datetime,p.arrival_station,p.arrival_datetime),('Салым',datetime(2026,10,5,9,46),'Астрахань 1',datetime(2026,10,8,0,12)))
        self.assertEqual(luvr_route(p.departure_station,p.arrival_station)[1],'DEPARTURE')

    def test_kanshin_real_two_independent_tickets(self):
        items=parse_rail_document((Path(__file__).parent/'fixtures/rail/round_trip.pdf').read_bytes(),'kanshin.pdf')
        self.assertEqual(len(items),2);first,second=items
        self.assertEqual([x.source_page for x in items],[1,2])
        self.assertTrue(all(x.full_name_raw=='КАНЬШИН ЕГОР ВИКТОРОВИЧ' and x.parse_status=='PARSED' for x in items))
        self.assertEqual((first.departure_station,first.departure_datetime,first.arrival_station,first.arrival_datetime),('Салым',datetime(2026,10,9,6,54),'Тюмень',datetime(2026,10,9,15,30)))
        self.assertEqual((second.departure_station,second.departure_datetime,second.arrival_station,second.arrival_datetime),('Тюмень',datetime(2026,10,11,23,4),'Салым',datetime(2026,10,12,7,29)))
        self.assertEqual([luvr_route(x.departure_station,x.arrival_station)[1] for x in items],['DEPARTURE','ARRIVAL'])

    def test_pages_never_borrow_missing_fields_or_names(self):
        items=parse_rail_document(combine_pdfs(coupon_pdf(full_name='ПЕРВЫЙ ИВАН ИВАНОВИЧ',arrival_datetime=None),coupon_pdf(full_name='ВТОРОЙ ПЕТР ПЕТРОВИЧ',departure_datetime=None)),'mixed.pdf')
        self.assertEqual(len(items),2)
        self.assertEqual(items[0].full_name,'ПЕРВЫЙ ИВАН ИВАНОВИЧ');self.assertEqual(items[1].full_name,'ВТОРОЙ ПЕТР ПЕТРОВИЧ')
        self.assertIsNone(items[0].arrival_datetime);self.assertIsNone(items[1].departure_datetime)
        self.assertTrue(all(x.parse_status=='PARSE_ERROR' for x in items))

    def test_provided_coupons_safe_structure_copies(self):
        for filename,expected in [
            ('salym_surgut.pdf',('АНИСЬКОВ ВЛАДИМИР ИВАНОВИЧ','Салым',datetime(2026,9,6,7,32),'Сургут',datetime(2026,9,6,11,12))),
            ('tyumen_salym.pdf',('ПЕТРОВ АЛЕКСЕЙ ВЛАДИМИРОВИЧ','Тюмень',datetime(2026,9,10,23,4),'Салым',datetime(2026,9,11,7,29)))]:
            parsed=parse_rail_ticket((Path(__file__).parent/'fixtures/rail'/filename).read_bytes(),filename)
            self.assertEqual(parsed.parse_status,'PARSED',parsed.parse_errors)
            self.assertEqual((parsed.full_name,parsed.departure_station,parsed.departure_datetime,parsed.arrival_station,parsed.arrival_datetime),expected)
            self.assertIsNone(parsed.arrival_datetime.tzinfo)

    def test_missing_name_departure_arrival(self):
        for field in ('full_name','departure_station','departure_datetime','arrival_station','arrival_datetime'):
            with self.subTest(field=field):
                p=parse_rail_ticket(coupon_pdf(**{field:None}),'ticket.pdf')
                self.assertEqual(p.parse_status,'PARSE_ERROR');self.assertIsNone(getattr(p,field));self.assertTrue(p.parse_errors)

    def test_empty_corrupt_unsupported_oversized(self):
        for data,name in [(b'','x.pdf'),(b'%PDF-1.4\nbroken','x.pdf'),(b'%PDF-'+b'x'*MAX_TICKET_BYTES,'x.pdf')]:
            self.assertEqual(parse_rail_ticket(data,name).parse_status,'PARSE_ERROR')
        for data,name in [(b'word','x.docx'),(coupon_pdf(),'x.docx')]:
            self.assertEqual(parse_rail_ticket(data,name).parse_status,'UNSUPPORTED')

    def test_unrecognized_or_scanned_layout_requires_review(self):
        self.assertEqual(parse_rail_ticket(coupon_pdf(header=False),'scan.pdf').parse_status,'UNSUPPORTED')

    def test_invalid_dates_not_guessed(self):
        for value in ('31.02.2026 12:00','01.10.2026 25:00'):
            self.assertEqual(parse_rail_ticket(coupon_pdf(arrival_datetime=value),'ticket.pdf').parse_status,'PARSE_ERROR')

    def test_normalization_only_case_and_spaces(self):
        self.assertEqual(normalize_passenger('  Иванов  ИВАН\tИванович '),normalize_passenger('Иванов Иван Иванович'))
        for name in ('Иванов Иван Петрович','Иванов И.И.','Иваноф Иван Иванович'):
            self.assertNotEqual(normalize_passenger(name),normalize_passenger('Иванов Иван Иванович'))
        self.assertNotEqual(normalize_passenger('Семенов'),normalize_passenger('Семёнов'))

    def test_safe_filename_no_client_path(self):
        self.assertEqual(safe_filename(r'C:\Users\secret\ticket.pdf'),'ticket.pdf')
        self.assertEqual(safe_filename('../../ticket.pdf'),'ticket.pdf')
        self.assertNotIn('\x00',safe_filename('bad\x00.pdf'))

    def test_doubled_text_preserves_real_repeated_letters(self):
        p=parse_rail_ticket(coupon_pdf(full_name='АННА АННА АННОВНА',departure_station='Рассказово'),'ticket.pdf')
        self.assertEqual(p.full_name,'АННА АННА АННОВНА');self.assertEqual(p.departure_station,'Рассказово')
