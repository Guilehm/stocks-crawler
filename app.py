import logging
import os
import sys

from flask import Flask, jsonify, request, abort

from google_sheets.crawler import SheetCrawler
from stocks_spider import StockSpider

# A GoHorse made app

DEBUG = os.getenv('DEBUG', True)
MONGODB_URI = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/stocksCrawler')
CRAWLER_EMAIL = os.getenv('CRAWLER_EMAIL')
CRAWLER_PASSWORD = os.getenv('CRAWLER_PASSWORD')

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
app = Flask(__name__)

uri_data = MONGODB_URI.rsplit('/', 1)
db_name = uri_data[-1]
mongo_url = ''.join(uri_data[:-1])
SPIDER = StockSpider(
    CRAWLER_EMAIL,
    CRAWLER_PASSWORD,
    mongo_url=MONGODB_URI,
    db_name=db_name,
    retry_writes='false',
)

db = SPIDER.db
stocks_collection = db.stocks
stocks_analysis_collection = db.fundamentalistAnalysis

stocks_sheet_collection = db.stocksSheet

SHEET_SPIDER = SheetCrawler(db=db)

try:
    SHEET_SPIDER._authenticate()
except Exception as e:
    logging.error(e)


def convert_id(document):
    if document.get('_id'):
        document['_id'] = str(document['_id'])
    return document


def add_url(document):
    url_root = request.url_root
    code = document['url'].rsplit('/', 2)[-2]
    document['analysisUrl'] = f'{url_root}stocks/{code}/analysis/'
    return document


@app.route('/')
def index():
    return jsonify({
        'stocks': f'{request.url}stocks/',
    })


@app.route('/stocks/', methods=['GET', 'POST'])
def stocks_list():
    if request.method != 'POST':
        stocks = [stock for stock in stocks_collection.find()]
    else:
        if not CRAWLER_EMAIL or not CRAWLER_PASSWORD:
            return jsonify({
                'error': True,
                'message': 'Credentials not set',
            })
        stocks = SPIDER.parse_stocks(save=True)
    return jsonify([add_url(convert_id(stock)) for stock in stocks])


@app.route('/stocks/sheets/', methods=['GET', 'POST'])
def stocks_sheet_list():
    if not SHEET_SPIDER.authenticated:
        return jsonify({
            'error': True,
            'message': 'Could not authenticate to Sheet Spider',
        })
    if request.method != 'POST':
        stocks = SHEET_SPIDER.get_stock_data(save=False, as_dict=True)
    else:
        logging.info('Fetching data from Google Sheet')
        stocks = SHEET_SPIDER.get_stock_data(save=True, as_dict=True, force_update=True)
    return jsonify([convert_id(stock) for stock in stocks])


@app.route('/stocks/analysis/')
def analysis_list():
    return jsonify([convert_id(a) for a in stocks_analysis_collection.find()])


@app.route('/stocks/<string:stock_code>/analysis/', methods=['GET', 'POST'])
def analysis_detail(stock_code):
    code = stock_code.upper()
    analysis = stocks_analysis_collection.find_one({
        'code': code,
    })
    if not analysis:
        stock = stocks_collection.find_one({'code': code})
        if not stock:
            return abort(404)
    if request.method == 'POST' or not analysis:
        if analysis:
            stocks_analysis_collection.delete_one(analysis)
        analysis = SPIDER.extract_all_fundamentalist_data(code, save=True)
    return jsonify(convert_id(analysis))


@app.route('/stocks/<string:stock_code>/')
def stocks_detail(stock_code):
    code = stock_code.upper()
    stock = stocks_collection.find_one({'code': code})
    if not stock:
        return abort(404)
    return jsonify(convert_id(stock))


if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=DEBUG)
