import argparse
import email.parser
from six.moves import urllib
import logging
import json
import sys
import os

from esridump import EsriDumper
from esridump.state import DumperState

def _collect_headers(strings):
    headers = {}
    parser = email.parser.Parser()

    for string in strings:
        headers.update(dict(parser.parsestr(string)))

    return headers

def _collect_params(strings):
    params = {}

    for string in strings:
        params.update(dict(urllib.parse.parse_qsl(string)))

    return params

def _parse_args(args):
    parser = argparse.ArgumentParser(
        description="Convert a single Esri feature service URL to GeoJSON")
    parser.add_argument("url",
        help="Esri layer URL")
    parser.add_argument("outfile",
        type=argparse.FileType('a'),
        help="Output file name (use - for stdout)")
    parser.add_argument("--proxy",
        help="Proxy string to send requests through ie: https://example.com/proxy.ashx?<SERVER>")
    parser.add_argument("--jsonlines",
        action='store_true',
        default=False,
        help="Output newline-delimited GeoJSON Features instead of a FeatureCollection")
    parser.add_argument("-v", "--verbose",
        action='store_const',
        dest='loglevel',
        const=logging.DEBUG,
        default=logging.INFO,
        help="Turn on verbose logging")
    parser.add_argument("-q", "--quiet",
        action='store_const',
        dest='loglevel',
        const=logging.WARNING,
        default=logging.INFO,
        help="Turn off most logging")
    parser.add_argument("-f", "--fields",
        help="Specify a comma-separated list of fields to request from the server")
    parser.add_argument("--no-geometry",
        dest='request_geometry',
        action='store_false',
        default=True,
        help="Don't request geometry for the feature so the server returns attributes only")
    parser.add_argument("-H", "--header",
        action='append',
        dest='headers',
        default=[],
        help="Add an HTTP header to send when requesting from Esri server")
    parser.add_argument("-p", "--param",
        action='append',
        dest='params',
        default=[],
        help="Add a URL parameter to send when requesting from Esri server")
    parser.add_argument("-t", "--timeout",
        type=int,
        default=30,
        help="HTTP timeout in seconds, default 30")
    parser.add_argument("-m", "--max-page-size",
        type=int,
        default=-1,
        help="Maximum number of features to pull per batch, "
             "default -1 (means pick from the layer metadata or 1000, whichever is higher)")
    parser.add_argument("--paginate-oid",
        dest='paginate_oid',
        action='store_true',
        default=False,
        help="Turn on paginate by OID regardless of normal pagination support")
    parser.add_argument("--output-format",
        dest='output_format',
        action='store',
        default='geojson',
        help="The JSON output format of the feature data")
    parser.add_argument("-c", "--to-continue",
        action='store_true',
        default=False,
        help="Save the state of retrieval to a file, to allow for download continuation")

    return parser.parse_args(args)

def main():
    args = _parse_args(sys.argv[1:])

    state_filename = None
    state = None
    if args.to_continue:
        if args.outfile is sys.stdout:
            print('ERROR: Download continuation is not allowed when writing to stdout')
            sys.exit(1)

        outfile_name = args.outfile.name
        base_name = os.path.basename(outfile_name)
        dirname = os.path.dirname(outfile_name)
        state_filename = os.path.join(dirname, base_name + '.state')

        if os.path.exists(state_filename):
            with open(state_filename, 'r') as f:
                state = DumperState.decode(f.read())
        elif args.outfile.tell() != 0:
            print('ERROR: Download continuation is enabled and a non empty output file exists '\
                  'but state file is not present, Download was alredy complete?')
            sys.exit(1)
    else:
        if args.outfile.tell() != 0:
            print('ERROR: File already exists and is non empty. Delete it?')
            sys.exit(1)


    headers = _collect_headers(args.headers)
    params = _collect_params(args.params)

    logger = logging.getLogger('cli')
    logger.setLevel(args.loglevel)
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    requested_fields = args.fields.split(',') if args.fields else None

    dumper = EsriDumper(args.url,
        state=state,
        update_state=args.to_continue,
        extra_query_args=params,
        extra_headers=headers,
        fields=requested_fields,
        request_geometry=args.request_geometry,
        proxy=args.proxy,
        timeout=args.timeout,
        max_page_size=args.max_page_size,
        parent_logger=logger,
        paginate_oid=args.paginate_oid,
        output_format=args.output_format)

    try:
        if args.jsonlines:
            for feature in dumper:
                args.outfile.write(json.dumps(feature))
                args.outfile.write('\n')
        else:
            if not args.to_continue or args.outfile.tell() == 0:
                args.outfile.write('{"type":"FeatureCollection","features":[\n')
            feature_iter = iter(dumper)
            try:
                feature = next(feature_iter)
                while True:
                    args.outfile.write(json.dumps(feature))
                    feature = next(feature_iter)
                    args.outfile.write(',\n')
            except StopIteration:
                args.outfile.write('\n')
            args.outfile.write(']}')
        if args.to_continue and os.path.exists(state_filename):
            os.unlink(state_filename)
    except: # noqa
        if args.to_continue:
            logger.info('saving state file')
            with open(state_filename, 'w') as f:
                f.write(dumper._state.encode())
            logger.info('Done saving state file')
        raise


if __name__ == '__main__':
    main()
