# -*- coding: utf-8 -*-

import io
import pickle
from time import time
import functools

from w3lib.http import headers_raw_to_dict, headers_dict_to_raw

from scrapy.http import Headers
from scrapy.responsetypes import responsetypes
from scrapy.utils.request import request_fingerprint

import boto3
import botocore

cache_key_prefix = "CACHE"


def listify(*args):
    """
    >>> l = [1, 2, 3, ]
    >>> listify('a', 'b', *l)
    ['a', 'b', 1, 2, 3]
    """
    return list(args)


def get_s3_text(bucket, key):
    body = io.BytesIO()
    bucket.download_fileobj(key, body)
    body.seek(0)
    text = body.read()
    return text

def send_s3_text(bucket, key, body):
    body = io.BytesIO(body)
    bucket.upload_fileobj(body, key)
    body.close()


class S3CacheStorage(object):
    def __init__(self, settings):
        self.bucket_name = settings['S3CACHE_BUCKET']
        assert self.bucket_name, "No bucket configured"
        s3 = boto3.resource('s3')
        self.bucket = s3.Bucket(self.bucket_name)

    def open_spider(self, spider):
        pass

    def close_spider(self, spider):
        pass

    def retrieve_response(self, spider, request):
        path = functools.partial(storage_path, request)
        try:
            _metadata = get_s3_text(self.bucket, path('pickled_meta'))
            body = get_s3_text(self.bucket, path('response_body'))
            rawheaders = get_s3_text(self.bucket, path('response_headers'))
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == "404":
                return None
            else:
                raise

        metadata = pickle.loads(_metadata)

        url = metadata.get('response_url')
        status = metadata['status']
        headers = Headers(headers_raw_to_dict(rawheaders))
        respcls = responsetypes.from_args(headers=headers, url=url)
        response = respcls(url=url, headers=headers, status=status, body=body)
        return response

    def store_response(self, spider, request, response):
        path = functools.partial(storage_path, request)
        metadata = {
            'url': request.url,
            'method': request.method,
            'status': response.status,
            'response_url': response.url,
            'timestamp': time(),
        }

        pairs = (
            ('meta', repr(metadata).encode('utf8')),
            ('pickled_meta', pickle.dumps(metadata, protocol=2)),
            ('request_headers', headers_dict_to_raw(request.headers)),
            ('request_body', request.body),
            ('response_headers', headers_dict_to_raw(response.headers)),
            ('response_body', response.body),
        )
        for key, body in pairs:
            send_s3_text(self.bucket, path(key), body)

def storage_path(request, *args):
    fingerprint = request_fingerprint(request)
    path = "/".join(listify(cache_key_prefix, get_path(request.url), fingerprint, *args))
    path = path.replace("//", "/")
    return path

def get_path(url):
    without_protocol = url.split("//", 1)[-1]
    without_domain = without_protocol.split("/", 1)[-1]
    return without_domain
