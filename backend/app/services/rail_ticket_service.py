import hashlib
import logging
from app.services.rail_ticket_parser import parse_rail_ticket, parse_rail_document, safe_filename, MAX_TICKET_BYTES
from app.repositories.rail_tickets import store_parsed_ticket

log=logging.getLogger(__name__)


def process_ticket(data,filename):
    log.info("RAIL_FILE_ACCEPTED bytes=%s",len(data))
    parsed=parse_rail_ticket(data,filename)
    if parsed.parse_status == "UNSUPPORTED":
        log.info("RAIL_UNSUPPORTED")
        return {"source_filename":parsed.source_filename,"processing_status":"UNSUPPORTED",
                "parse_errors":[],"notice":"Не является поддерживаемым билетом РЖД", "match_status":"NOT_FOUND"}
    log.info("RAIL_PARSE_%s", "SUCCESS" if parsed.parse_status=="PARSED" else "ERROR")
    return store_parsed_ticket(hashlib.sha256(data).hexdigest(),parsed)


def process_document(data,filename):
    results=[]
    parsed_tickets=parse_rail_document(data,filename)
    log.info('RAIL_FILE_ACCEPTED bytes=%s pages=%s',len(data),len(parsed_tickets))
    for parsed in parsed_tickets:
        log.info('RAIL_PARSE_%s page=%s',parsed.parse_status,parsed.source_page)
        if parsed.parse_status=='UNSUPPORTED':
            results.append({'source_filename':parsed.source_filename,'source_page':parsed.source_page,
                'processing_status':'UNSUPPORTED','parse_errors':parsed.parse_errors,'match_status':'NOT_FOUND'})
            continue
        identity=data if len(parsed_tickets)==1 else b'rail-page-v1\0'+hashlib.sha256(data).digest()+str(parsed.source_page).encode('ascii')
        try:
            results.append(store_parsed_ticket(hashlib.sha256(identity).hexdigest(),parsed))
        except Exception:
            log.error('RAIL_PAGE_STORAGE_FAILED page=%s',parsed.source_page)
            error=upload_error(filename,'Не удалось сохранить разбор страницы. Повторите загрузку.')
            error['source_page']=parsed.source_page
            results.append(error)
    return results


def upload_error(filename,message):
    return {"id":None,"source_filename":safe_filename(filename),"processing_status":"PARSE_ERROR",
            "parse_errors":[message],"match_status":"NOT_FOUND","duplicate":False}
