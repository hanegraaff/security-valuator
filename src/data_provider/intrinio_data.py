import datetime
import intrinio_sdk
from intrinio_sdk.rest import ApiException
import os
import math
from exception.exceptions import DataError, ValidationError
from data_provider import intrinio_util
from support.financial_cache import cache
import logging

"""
This module is a value add to the Intrinio SDK
and implements a number of functions to read current and historical
financial statements
"""

API_KEY = os.environ['INTRINIO_API_KEY']

intrinio_sdk.ApiClient().configuration.api_key['api_key'] = API_KEY

fundamentals_api = intrinio_sdk.FundamentalsApi()
company_api = intrinio_sdk.CompanyApi()
security_api = intrinio_sdk.SecurityApi()


INTRINIO_CACHE_PREFIX = 'intrinio'


def get_daily_stock_close_prices(ticker : str, start_date : object, end_date : object):
      """
        Returns a list of historical daily stock prices given a ticker symbol and
        a range of dates.

        Currently only returns one page of 100 results

        Parameters
        ----------
        ticker : str
          Ticker Symbol
        start_date : object
          The beginning price date as python date object
        end_date : object
          The end price date as python date object
        
        Raises
        -----------
        ValidationError in case of invalid paramters
        DataError in case of any Intrinio errors

        Returns
        -----------
        a dictionary of date->price like this
        {
          '2019-10-01': 100,
          '2019-10-02': 101,
          '2019-10-03': 102,
          '2019-10-04': 103,
        }
      """

      start_date_str = intrinio_util.date_to_string(start_date)
      end_date_str = intrinio_util.date_to_string(end_date)

      price_dict = {}

      cache_key = "%s-%s-%s-%s-%s" % (INTRINIO_CACHE_PREFIX, ticker, start_date_str, end_date_str, "closing-prices")
      api_response = cache.read(cache_key)

      if api_response == None:
        try:
          api_response = security_api.get_security_stock_prices(ticker, start_date=start_date_str, end_date=end_date_str, frequency='daily', page_size=100)
          cache.write(cache_key, api_response)
        except ApiException as ae:
          raise DataError("API Error while reading price data from Intrinio Security API: ('%s', %s - %s)" %
                          (ticker, start_date_str, end_date_str), ae)
        except Exception as e:
          raise ValidationError("Unknown Error while reading price data from Intrinio Security API: ('%s', %s - %s)" %
                          (ticker, start_date_str, end_date_str), e)

      price_list = api_response.stock_prices

      if len(price_list) == 0:
        raise DataError("No prices returned from Intrinio Security API: ('%s', %s - %s)" %
                    (ticker, start_date_str, end_date_str), None)

      for price in price_list:  
        price_dict[intrinio_util.date_to_string(price.date)] = price.close

      return price_dict


def get_historical_revenue(ticker: str, year_from: int, year_to: int):
    '''
      Returns a dictionary of year->"total revenue" for the supplied ticker and 
      range of years.

      Parameters
      ----------
      ticker : str
        Ticker Symbol
      year_from : int
        The beginning year to look up
      end_from : int
        The end year to look up

      Returns
      -----------
      a dictionary of year->"fcff value" like this
      {
        2010: 123,
        2012: 234,
        2013: 345,
        2014: 456,
      }
    '''

    return __read_financial_metrics__(ticker, year_from, year_to, 'totalrevenue')


def get_historical_fcff(ticker: str, year_from: int, year_to: int):
    '''
      Returns a dictionary of year->"fcff value" for the supplied ticker and 
      range of years.

        This is the description from Intrinio documentation:

        Definition
        Free cash flow for the firm (FCFF) is a measure of financial performance that 
        expresses the net amount of cash that is generated for a firm after expenses, 
        taxes and changes in net working capital and investments are deducted. 
        FCFF is essentially a measurement of a company's profitability after all expenses 
        and reinvestments. It's one of the many benchmarks used to compare and analyze 
        financial health.

        Formula
        freecashflow = nopat - investedcapitalincreasedecrease


      Parameters
      ----------
      ticker : str
        Ticker Symbol
      year_from : int
        The beginning year to look up
      end_from : int
        The end year to look up

      Returns
      -----------
      a dictionary of year->"fcff value" like this
      {
        2010: 123,
        2012: 234,
        2013: 345,
        2014: 456,
      }
    '''

    return __read_financial_metrics__(ticker, year_from, year_to, 'freecashflow')


def get_diluted_eps(ticker: str, year: int):
    '''
      Returns Intrinio's adjdilutedeps metric for the given year.
      This value is calcualted the same way as:

        This is the description from Intrinio documentation:

        Diluted EPS is a performance metric used to gauge the quality of a company's
        earnings per share (EPS) if all convertible securities were exercised.
        Convertible securities are all outstanding convertible preferred shares,
        convertible debentures, stock options (primarily employee-based) and warrants.
        Adjusted for stock splits.

      Parameters
      ----------
      ticker : str
        Ticker Symbol
      year : int
        Current or hisorical year to look up

      Returns
      -----------
      A number representing the diluted eps
    '''
    return __read_financial_metric__(ticker, year, 'adjdilutedeps')


def get_bookvalue_per_share(ticker: str, year: int):
    '''
      Returns Intrinio's bookvaluepershare metric for the given year.
      This value is calcualted the same way as:

        totalequity/weightedavedilutedsharesos

        from the income statement.

      Parameters
      ----------
      ticker : str
        Ticker Symbol
      year : int
        Current or hisorical year to look up

      Returns
      -----------
      A number representing the diluted eps
    '''

    return __read_financial_metric__(ticker, year, 'bookvaluepershare')


def get_outstanding_diluted_shares(ticker : str, year: int):
    '''
      Returns the weighted average of diluted outstanding shares.
      
      Here is the intrinio description

      The weighted average of diluted outstanding shares is a calculation that 
      incorporates any changes in the amount of outstanding shares over a reporting period. 
      Diluted shares outstanding includes all shares that would be created upon conversion 
      into shares. Convertible securities are all outstanding convertible preferred shares, 
      convertible debentures, stock options (primarily employee-based) and warrants. 
      Adjusted for stock splits.
       

      Parameters
      ----------
      ticker : str
        Ticker Symbol
      year : int
        Current or hisorical year to look up

      Returns
      -----------
      A number representing the outstanding shares
    '''

    weighted_avg_diluted_shares = __read_financial_metric__(ticker, year, 'weightedavedilutedsharesos')

    return weighted_avg_diluted_shares


def get_historical_income_stmt(ticker: str, year_from: int,
                               year_to: int, tag_filter_list: list):
    """
      returns a dictionary containing partial or complete income statements given
      a ticker symbol, year from, year to and a list of tag filters
      used to narrow the results.

      Parameters
      ----------
      ticker : str
        Ticker Symbol
      year_from : int
        Start year of financial statement list
      year_to : int
        End year of the financial statement list 
      tag_filter_list : list
        List of data tags used to filter results. The name of each tag
        must match an expected one from the Intrinio API

      Returns
      -------
      A dictionary of year=>dict with the filtered results. For example:

      {2010: {
        'netcashfromcontinuingoperatingactivities': 77434000000.0,
        'purchaseofplantpropertyandequipment': -13313000000
      },}

    """

    return __read_historical_financial_statement__(
        ticker.upper(), 'income_statement', year_from, year_to, tag_filter_list)


def get_historical_balance_sheet(ticker: str, year_from: int,
                                 year_to: int, tag_filter_list: list):
    """
      returns a dictionary containing partial or complete balance sheets given
      a ticker symbol, year from, year to and a list of tag filters
      used to narrow the results.

      Parameters
      ----------
      ticker : str
        Ticker Symbol
      year_from : int
        Start year of financial statement list
      year_to : int
        End year of the financial statement list 
      tag_filter_list : list
        List of data tags used to filter results. The name of each tag
        must match an expected one from the Intrinio API

      Returns
      -------
      A dictionary of year=>dict with the filtered results. For example:

      {2010: {
        'netcashfromcontinuingoperatingactivities': 77434000000.0,
        'purchaseofplantpropertyandequipment': -13313000000
      },}

    """
    return __read_historical_financial_statement__(
        ticker.upper(), 'balance_sheet_statement', year_from, year_to, tag_filter_list)


def get_historical_cashflow_stmt(ticker: str, year_from: int,
                                 year_to: int, tag_filter_list: list):
    """
      returns a partial or complete set of cashflow statements given
      a ticker symbol, year from, year to and a list of tag filters
      used to narrow the results.

      Parameters
      ----------
      ticker : str
        Ticker Symbol
      year_from : int
        Start year of financial statement list
      year_to : int
        End year of the financial statement list 
      tag_filter_list : list
        List of data tags used to filter results. The name of each tag
        must match an expected one from the Intrinio API

      Returns
      -------
      A dictionary of year=>dict with the filtered results. For example:

      {2010: {
        'netcashfromcontinuingoperatingactivities': 77434000000.0,
        'purchaseofplantpropertyandequipment': -13313000000
      },}

    """
    return __read_historical_financial_statement__(
        ticker.upper(), 'cash_flow_statement', year_from, year_to, tag_filter_list)


def __transform_financial_stmt__(std_financials_list: list, tag_filter_list: list):
    """
      Helper function that transforms a financial statement stored in
      the raw Intrinio format into a more user friendly one.


      Parameters
      ----------
      std_financials_list : list
        List of standardized financials extracted from the Intrinio API
      tag_filter_list : list
        List of data tags used to filter results. The name of each tag
        must match an expected one from the Intrinio API

      Returns
      -------
      A dictionary of tag=>value with the filtered results. For example:

      {
        'netcashfromcontinuingoperatingactivities': 77434000000.0,
        'purchaseofplantpropertyandequipment': -13313000000
      }

      Note that the name of the tags are specific to the Intrinio API
    """
    results = {}

    for financial in std_financials_list:

        if (tag_filter_list == None or
                financial.data_tag.tag in tag_filter_list):
            results[financial.data_tag.tag] = financial.value

    return results


def __read_historical_financial_statement__(ticker: str, statement_name: str, year_from: int, year_to: int, tag_filter_list: list):
    """
      This helper function will read standardized fiscal year end financials from the Intrinio fundamentals API
      for each year in the supplied range, and normalize the results into simpler user friendly
      dictionary, for example:

      {
        'netcashfromcontinuingoperatingactivities': 77434000000.0,
        'purchaseofplantpropertyandequipment': -13313000000
      }

      results may also be filtered based on the tag_filter_list parameter, which may include
      just the tags that should be returned.

      Parameters
      ----------
      ticker : str
        Ticker Symbol
      statement_name : str
        The name of the statement to read.
      year_from : int
        Start year of financial statement list
      year_to : int
        End year of the financial statement list 
      tag_filter_list : list
        List of data tags used to filter results. The name of each tag
        must match an expected one from the Intrinio API. If "None", then all
        tags will be returned.

      Raises
      -------
      DataError in case of any error calling the intrio API

      Returns
      -------
      A dictionary of tag=>value with the filtered results. For example:

      {
        'netcashfromcontinuingoperatingactivities': 77434000000.0,
        'purchaseofplantpropertyandequipment': -13313000000
      }

      Note that the name of the tags are specific to the Intrinio API

    """
    # return value
    hist_statements = {}
    ticker = ticker.upper()

    statement_type = 'FY'

    try:
      for i in range(year_from, year_to + 1):
          satement_name = ticker + "-" + \
              statement_name + "-" + str(i) + "-" + statement_type

          cache_key = "%s-%s-%s-%s-%s-%d" % (INTRINIO_CACHE_PREFIX, "statement", ticker, statement_name, statement_type, i)
          statement = cache.read(cache_key)

          if statement == None:
            statement = fundamentals_api.get_fundamental_standardized_financials(
                satement_name)

            cache.write(cache_key, statement)

          hist_statements[i] = __transform_financial_stmt__(
              statement.standardized_financials, tag_filter_list)

    except ApiException as ae:
        raise DataError(
            "Error retrieving ('%s', %d - %d) -> '%s' from Intrinio Fundamentals API" % (ticker, year_from, year_to, statement_name), ae)

    return hist_statements


def __read_financial_metrics__(ticker: str, start_year: int, end_year: int, tag: str):
    """
      Helper function that will read the Intrinio company API for the supplied date range
      and convert the resulting list into a more friendly dictionary.

      Specifically a result like this

      [
        {
          'date': datetime.date(2010, 1, 1),
          'value': 123
        },
      ]

      into this:

      [{
        2010: 123,
      }]

      Parameters
      ----------
      ticker : str
        Ticker symbol. E.g. 'AAPL'
      start_year : int
        Start year of the metric data
      end_year : int
        End year of the metric data
      tag : the metric name to retrieve

      Raises
      -------
      DataError in case of any error calling the intrio API
      ValidationError in case of an unknown exception


      Returns
      -------
      A dictionary of year=>value with the filtered results. For example:

      {
        2010: 123,
        2012: 234,
        2013: 345,
        2014: 456,
      }
    """
    (start_date, x) = intrinio_util.get_fiscal_year_period(start_year, 0)
    (x, end_date) = intrinio_util.get_fiscal_year_period(end_year, 0)

    frequency = 'yearly'

    # check the cache first
    cache_key = "%s-%s-%s-%d-%d-%s-%s" % (INTRINIO_CACHE_PREFIX, "metric", ticker, start_year, end_year, frequency, tag)
    api_response = cache.read(cache_key)

    if api_response == None:
      # else call the API directly
      try:
          api_response = company_api.get_company_historical_data(
              ticker, tag, frequency=frequency, start_date=start_date, end_date=end_date)
          cache.write(cache_key, api_response)
      except ApiException as ae:
          raise DataError(
              "Error retrieving ('%s', %d - %d) -> '%s' from Intrinio Company API" % (ticker, start_year, end_year, tag), ae)
      except Exception as e:
          raise ValidationError(
              "Error parsing ('%s', %d - %d) -> '%s' from Intrinio Company API" % (ticker, start_year, end_year, tag), e)

    if len(api_response.historical_data) == 0:
        raise DataError("No Data returned for ('%s', %d - %d) -> '%s' from Intrinio Company API" %
                        (ticker, start_year, end_year, tag), None)

    historical_data = api_response.historical_data
    converted_response = {}

    for datapoint in historical_data:
        converted_response[datapoint.date.year] = datapoint.value

    return converted_response


def __read_financial_metric__(ticker: str, year: int, tag: str):
    """
      Utility method that reads the financial metrics for a single year
    """
    metrics = __read_financial_metrics__(ticker, year, year, tag)
    return metrics[year]

