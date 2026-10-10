import json


if __name__ == '__main__':
    import akshare as ak
    dates = ak.tool_trade_date_hist_sina()['trade_date']
    print(json.dumps([str(d)[:10] for d in dates]))
