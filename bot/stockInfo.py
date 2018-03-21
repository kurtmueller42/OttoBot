from webWrapper import RestWrapper

import json
import logging
import datetime
import pytz
import copy

_logger = logging.getLogger()

class StockInfo():
    def __init__(self, webWrapper, api_key):
        self.rest = RestWrapper(webWrapper,
            "https://www.alphavantage.co/query", {'apikey': api_key})
        self.date_format = '%Y-%m-%d'
        self.date_time_format = '%Y-%m-%d %H:%M:00'
        self.error_message_key = 'Error Message'
        self.input_mapping = {
            'live': ('TIME_SERIES_INTRADAY', {'interval': '1min'}, 'Time Series (1min)', self.get_last_minutes, {}, False),
            'daily': ('TIME_SERIES_DAILY', {}, 'Time Series (Daily)', self.get_last_days, {}, False),
            'duration': ('TIME_SERIES_DAILY', {}, 'Time Series (Daily)', self.get_last_days, {'count': 5}, self.accumulate_data),
            'monthly': ('TIME_SERIES_MONTHLY', {}, 'Monthly Time Series', self.get_last_months, {}, None),
            'moving_average': ('TIME_SERIES_DAILY', {}, 'Time Series (Daily)', self.get_last_days, {'count': 30}, self.moving_average),
        }
        self.default_timing = 'live'
        self.open_key = '1. open'
        self.high_key = '2. high'
        self.low_key = '3. low'
        self.close_key = '4. close'
        self.volume_key = '5. volume'
        self.warning_key = '0. warnings'
        self.range_key = '6. ranges'
        self.debug = 'debug'
        self.count = 'count'

    @staticmethod
    def is_market_live(time=None):
        if time is None:
            time = datetime.datetime.now(pytz.timezone('EST5EDT'))
        return (time.hour > 9 or (time.hour == 9 and time.minute >= 30)) and time.hour < 16

    def get_last_minutes(self, **kwargs):
        result = []
        time = datetime.datetime.now(pytz.timezone('EST5EDT'))
        if not self.is_market_live(time):
            #if market is not live, jump back to last live minute from yesterday
            if time.hour <   16:
                time = time + datetime.timedelta(days=-1)
            time = time.replace(hour=16, minute=0)
        result.append(time.strftime(self.date_time_format))
        result.append((time + datetime.timedelta(minutes=-1)).strftime(self.date_time_format))
        
        return result
    
    def get_last_days(self, **kwargs):
        count = 2
        if self.count in kwargs:
            count = kwargs[self.count]
        result = []
        time = datetime.datetime.now(pytz.timezone('EST5EDT'))
        while len(result) < count:
            time = time + datetime.timedelta(days=-1)
            if time.weekday() > 4:
                continue
            result.append(time.strftime(self.date_format))
        
        return result
    
    def get_last_months(self, **kwargs):
        result = []
        time = datetime.datetime.now(pytz.timezone('EST5EDT'))
        result.append(time.strftime(self.date_format))
        time = time.replace(day=1)
        time = time + datetime.timedelta(days=-1)
        result.append(time.strftime(self.date_format))
        
        return result
    
    def accumulate_data(self, data_list, extra=[]):
        # assumes data is sorted newest first
        result = {
            self.open_key: data_list[-1][self.open_key],
            self.close_key: data_list[0][self.close_key],
        }
        high = data_list[0][self.high_key]
        low = data_list[0][self.low_key]
        for data in data_list:
            high = max(high, data[self.high_key])
            low = min(low, data[self.low_key])
        result[self.high_key] = high
        result[self.low_key] = low
        return result
    
    def moving_average(self, data_list, extra=[]):
        to_average = []
        for data in data_list:
            to_average.append(float(data[self.close_key]))

        result = sum(to_average) / len(to_average)
        
        return {
            self.close_key: result
        }

    async def daily_values(self, symbol, timing=None, extra=[]):
        result = {}
        api_stuff = self.input_mapping[self.default_timing]
        if timing:
            timing = timing.lower()
            if timing in self.input_mapping:
                api_stuff = self.input_mapping[timing]
            else:
                result[self.warning_key] = 'recognized timings are (%s). Defaulting to %s' % (', '.join([x for x in self.input_mapping]), self.default_timing)
        
        count = -1
        for e in extra:
            try:
                test = int(e)
                test = max(test, 1)
                test = min(test, 99)
                count = test
                break
            except Exception:
                pass
        
        api_keys = copy.copy(api_stuff[1])
        api_keys['function'] = api_stuff[0]
        api_keys['symbol'] = symbol

        response = await self.rest.request('', api_keys)
        data_wrapper = json.loads(await response.text())
        if self.error_message_key in data_wrapper:
            _logger.error('Error with api call: ' + data_wrapper[self.error_message_key])
            raise Exception('API call failed. Check your symbol?')
        try:
            data = data_wrapper[api_stuff[2]]
        except KeyError as e:
            raise KeyError(e, 'Well, I certainly wasn\'t excpecting that structure')
        # only grab today's data
        params = copy.copy(api_stuff[4])
        if count != -1:
            params['count'] = count
        keys = api_stuff[3](**params)
        cumulative = []
        cumulative_keys = []
        for key in keys:
            if key in data:
                if not api_stuff[5]:
                    result.update(data[key])
                    if self.debug in extra:
                        result[self.range_key] = key
                    del result[self.volume_key]
                    return result
                else:
                    cumulative.append(data[key])
                    cumulative_keys.append(key)
            else:
                _logger.warn("couldn't find key: " + str(key))
        
        result.update(api_stuff[5](cumulative))
        if self.debug in extra:
            result[self.range_key] = ', '.join(cumulative_keys)
        return result