"""Bounded direct transports for the public endpoints used by AKShare.

No import of pandas/AKShare on each minute request. Endpoint field mappings are
kept explicit and tested against raw captures; no guessed prices or timestamps.
"""
import asyncio
import json
import time
import os
from collections import deque
from datetime import datetime
from decimal import Decimal

from curl_cffi import requests

from app.domain.market import TZ, symbol_id
from app.providers.errors import classify_error


class SourceError(Exception):
    def __init__(self, code, retry_after=0):
        super().__init__(code)
        self.code, self.retry_after = code, retry_after


def get_text(url, params=None, limit=2_000_000):
    try:
        response = requests.get(url, params=params, timeout=12, stream=True,
                                headers={'Accept':'application/json,text/plain,*/*'})
        try:
            if response.status_code == 429:
                retry = response.headers.get('Retry-After', '60')
                raise SourceError('PROVIDER_RATE_LIMITED', min(600,max(10,int(retry))) if retry.isdigit() else 60)
            if response.status_code != 200:
                raise SourceError(f'PROVIDER_HTTP_{response.status_code}')
            pieces, size = [], 0
            for chunk in response.iter_content():
                size += len(chunk)
                if size > limit:
                    raise SourceError('PROVIDER_RESPONSE_TOO_LARGE')
                pieces.append(chunk)
            return b''.join(pieces).decode('utf-8')
        finally:
            response.close()
    except SourceError:
        raise
    except Exception as error:
        raise SourceError(classify_error(error)['error']) from None


def get_json(url, params=None):
    try:
        return json.loads(get_text(url, params))
    except ValueError:
        raise SourceError('PROVIDER_INVALID_JSON') from None


def eastmoney_rows(symbol):
    symbol = symbol_id(symbol)
    data = get_json('https://push2his.eastmoney.com/api/qt/stock/trends2/get', {
        'fields1':'f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13',
        'fields2':'f51,f52,f53,f54,f55,f56,f57,f58', 'ndays':'5','iscr':'0',
        'secid':('1.' if symbol.startswith('SH') else '0.')+symbol[3:]})
    data = data.get('data')
    if not isinstance(data,dict) or str(data.get('code')) != symbol[3:]:
        raise SourceError('SYMBOL_NOT_FOUND')
    trends = data.get('trends')
    if not isinstance(trends,list) or not 0 < len(trends) <= 2000:
        raise SourceError('PROVIDER_ROW_LIMIT')
    keys = ['时间','开盘','收盘','最高','最低','成交量','成交额','均价']
    result = []
    for line in trends:
        values = line.split(',')
        if len(values) != 8:
            raise SourceError('PROVIDER_INVALID_RESPONSE')
        result.append(dict(zip(keys,values)))
    return result


def sina_rows(symbol):
    symbol = symbol_id(symbol)
    raw = get_text('https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData',
                   {'symbol':symbol[:2].lower()+symbol[3:],'scale':'1','ma':'no','datalen':'1970'})
    try:
        data = json.loads(raw.split('=(',1)[1].rsplit(');',1)[0])
        if not isinstance(data,list) or not 0 < len(data) <= 2000:
            raise ValueError()
        if any(not all(k in r for k in ('day','open','high','low','close','volume','amount')) for r in data):
            raise ValueError()
        return data
    except (IndexError,ValueError,TypeError):
        raise SourceError('PROVIDER_INVALID_RESPONSE') from None


def quote(symbol):
    symbol = symbol_id(symbol)
    data = get_json('https://push2.eastmoney.com/api/qt/stock/get', {
        'secid':('1.' if symbol.startswith('SH') else '0.')+symbol[3:], 'fltt':'2',
        'fields':'f57,f58,f189,f51,f52,f43,f60,f86,f292,f47,f48,f170,f59'})
    value = data.get('data')
    if not isinstance(value,dict) or value.get('f57') != symbol[3:]:
        raise SourceError('SYMBOL_NOT_FOUND')
    return value


def instrument(symbol, value, at, calendar):
    symbol = symbol_id(symbol)
    name = str(value['f58']).strip()
    listed = datetime.strptime(str(value['f189']), '%Y%m%d').date()
    quoted = datetime.fromtimestamp(int(value['f86']),TZ)
    upper,lower = Decimal(str(value['f51'])),Decimal(str(value['f52']))
    if not name or len(name)>40 or not upper.is_finite() or not lower.is_finite():
        raise SourceError('METADATA_INVALID')
    days = [d for d in (calendar or {}).get('trading_dates',[]) if listed.isoformat() <= d <= at.date().isoformat()]
    # Old listings predate the calendar range. New listings require actual dates.
    seasoned = listed.isoformat() < (calendar or {}).get('valid_from','') or len(days)>=20
    risk = 'ST' if 'ST' in name.upper() else 'DELISTED' if '退' in name else 'NEW' if name.startswith(('N','C')) or not seasoned else 'NORMAL'
    fresh_trade = quoted.date() == at.date() and 0 <= (at-quoted).total_seconds() <= 90 and Decimal(str(value['f47']))>0
    return {'name':name,'symbol':symbol,'board':'STAR' if symbol[3:].startswith('688') else 'CHINEXT' if symbol[3:].startswith(('300','301')) else 'MAIN',
            'risk_status':risk,'ordinary_a':True,'suspended':False if fresh_trade else None,
            'limits_verified':bool(fresh_trade and upper>lower>0),'upper_limit_cny':str(upper),'lower_limit_cny':str(lower),
            'list_date':listed.isoformat(),'metadata_source':'eastmoney/stock/get','checked_at':at.isoformat(),
            'quote_at':quoted.isoformat(),'eligibility_basis':'recent_trade_and_verified_daily_limits' if fresh_trade else 'awaiting_current_session_trade',
            'previous_close_cny':str(value['f60'])}


def search(query):
    data = get_json('https://searchapi.eastmoney.com/api/suggest/get', {'input':query,'type':'14','count':'12'})
    found = []
    for row in data.get('QuotationCodeTable',{}).get('Data',[]) or []:
        try:
            symbol = symbol_id(str(row['Code']))
            if str(row.get('MktNum')) != ('1' if symbol.startswith('SH') else '0'):
                continue
            found.append({'symbol':symbol,'name':str(row['Name'])})
        except (ValueError,KeyError):
            continue
    return found


class Transport:
    def __init__(self, concurrency=3):
        self.semaphore = asyncio.Semaphore(concurrency)
        self.failures, self.retry_at = {}, {}
        self.request_times = deque()
        self.max_calls = max(1,min(300,int(os.getenv('RADAR_MAX_CALLS_PER_MINUTE','120'))))
        self.budget_lock = asyncio.Lock()

    async def call(self, key, function, *args):
        if self.retry_at.get(key,0)>time.monotonic():
            raise SourceError('PROVIDER_CIRCUIT_OPEN')
        async with self.semaphore:
            while True:
                async with self.budget_lock:
                    instant=time.monotonic()
                    while self.request_times and instant-self.request_times[0]>=60:
                        self.request_times.popleft()
                    if len(self.request_times)<self.max_calls:
                        self.request_times.append(instant)
                        break
                    wait=60-(instant-self.request_times[0])+.01
                await asyncio.sleep(wait)
            try:
                result = await asyncio.to_thread(function,*args)
                self.failures.pop(key,None);self.retry_at.pop(key,None)
                return result
            except SourceError as error:
                count = self.failures.get(key,0)+1
                self.failures[key] = count
                if count>=3 or error.retry_after:
                    self.retry_at[key] = time.monotonic()+max(error.retry_after,min(300,15*2**min(count,4)))
                raise
